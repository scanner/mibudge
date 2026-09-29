#!/usr/bin/env python
#
"""
Generate the Markdown API reference (`docs/api.md`) from the OpenAPI schema.

Usage:
    python generate_api_docs.py <openapi.yaml> <examples-dir> <output.md>

The reference is written for someone coding against the API:

- The schema's introduction (authentication, pagination, throttling,
  errors) comes first, then one table of the common responses -- the
  error statuses `common.schema.AutoSchema` adds to every endpoint of a
  kind (marked `x-common-response`).  Each endpoint lists which of them
  apply in one line, and describes only its own errors in full.
- Bodies are `jsonc` blocks shaped like the JSON a client sends or
  receives, each field commented with its type and whether it is
  required, optional, read-only or nullable.
- An object used by more than one endpoint (or nested in another) is
  defined once, at the end of the section of the first endpoint that
  uses it, merging its response shape with its writable request shape;
  endpoints link to it.  A body only one endpoint uses is shown inline.
- Worked examples come from `<examples-dir>`: one `<operationId>.json`
  per endpoint (see its README), shown as plain `json` blocks under the
  endpoint.  A file naming no operation in the schema is an error.

Re-running the script overwrites the output file.
"""

# system imports
import json
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 3rd party imports
import yaml

COMMON_RESPONSE = "x-common-response"
REF_PREFIX = "#/components/schemas/"
JSON = "application/json"
METHODS = ("get", "post", "put", "patch", "delete")

# The column trailing field comments line up at, and the widest line a
# comment may extend to before its text moves above the field.
#
COMMENT_COLUMN = 36
LINE_WIDTH = 88

PLACEHOLDERS = {
    "uuid": '"3fa85f64-5717-4562-b3fc-2c963f66afa6"',
    "date": '"2026-09-29"',
    "date-time": '"2026-09-29T14:00:00Z"',
    "decimal": '"125.00"',
    "email": '"user@example.com"',
    "uri": '"https://mibudge.example.com/..."',
}
ENUM_LINE = re.compile(r"^\s*\*\s+`([^`]*)`\s+-\s+(.*)$")


####################################################################
#
def ref_name(schema: dict) -> str | None:
    """The component name `schema` refers to, looking through `allOf`."""
    if "$ref" in schema:
        return schema["$ref"].removeprefix(REF_PREFIX)
    all_of = schema.get("allOf")
    if all_of and len(all_of) == 1 and "$ref" in all_of[0]:
        return all_of[0]["$ref"].removeprefix(REF_PREFIX)
    return None


####################################################################
#
def family_of(name: str) -> str:
    """The object a component describes: `PatchedBudgetRequest` -> `Budget`."""
    return name.removeprefix("Patched").removesuffix("Request") or name


####################################################################
#
def anchor(family: str) -> str:
    """The Markdown link target of an object's definition."""
    return f"#{family.lower()}-object"


####################################################################
#
def split_enum_description(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Separate drf-spectacular's '* `G` - Goal' lines from a description."""
    prose: list[str] = []
    values: list[tuple[str, str]] = []
    for line in text.splitlines():
        if m := ENUM_LINE.match(line):
            values.append((m.group(1), m.group(2)))
        else:
            prose.append(line)
    return " ".join(" ".join(prose).split()), values


########################################################################
########################################################################
#
@dataclass
class Field:
    """One field of an object, as a client sees it."""

    name: str
    schema: dict
    flags: list[str] = field(default_factory=list)


########################################################################
########################################################################
#
class Reference:
    """Renders an OpenAPI spec as the Markdown API reference."""

    ####################################################################
    #
    def __init__(self, spec: dict, examples: dict[str, dict]) -> None:
        self.spec = spec
        self.worked = examples
        self.schemas: dict[str, dict] = spec.get("components", {}).get(
            "schemas", {}
        )
        self.operations = [
            (path, method, op)
            for path, item in spec.get("paths", {}).items()
            for method, op in item.items()
            if method in METHODS
        ]
        self.shared, self.home = self._place_objects()
        known = {op.get("operationId") for _p, _m, op in self.operations}
        if unknown := sorted(set(examples) - known):
            raise ValueError(f"examples for unknown operations: {unknown}")

    ####################################################################
    #
    def is_enum(self, name: str) -> bool:
        """Whether component `name` is an enum (shown inline, never linked)."""
        return "enum" in self.schemas.get(name, {})

    ####################################################################
    #
    def is_error(self, name: str) -> bool:
        """Whether component `name` is an error body (see Common responses)."""
        return name in ("Error", "ValidationError")

    ####################################################################
    #
    def page_item(self, name: str) -> str | None:
        """The item component of a `Paginated*List` component, if it is one."""
        if not name.startswith("Paginated"):
            return None
        results = self.schemas[name].get("properties", {}).get("results", {})
        return ref_name(results.get("items", {}))

    ####################################################################
    #
    def body_refs(self, schema: dict) -> list[str]:
        """The object components a body schema is made of."""
        if (name := ref_name(schema)) is not None:
            if item := self.page_item(name):
                return [item]
            if self.is_enum(name) or self.is_error(name):
                return []
            return [name]
        if schema.get("type") == "array":
            return self.body_refs(schema.get("items", {}))
        return []

    ####################################################################
    #
    def field_refs(self, schema: dict) -> list[str]:
        """The object components a field schema refers to."""
        if schema.get("type") == "array":
            return self.field_refs(schema.get("items", {}))
        if isinstance(schema.get("additionalProperties"), dict):
            return self.field_refs(schema["additionalProperties"])
        name = ref_name(schema)
        if name is None or self.is_enum(name) or self.is_error(name):
            return []
        return [name]

    ####################################################################
    #
    def operation_bodies(self, op: dict) -> list[dict]:
        """The request and success-response JSON schemas of an operation."""
        bodies = []
        request = op.get("requestBody", {}).get("content", {}).get(JSON)
        if request:
            bodies.append(request["schema"])
        for code, response in op.get("responses", {}).items():
            media = response.get("content", {}).get(JSON)
            if code.startswith("2") and media:
                bodies.append(media["schema"])
        return bodies

    ####################################################################
    #
    def _place_objects(self) -> tuple[set[str], dict[str, str]]:
        """Decide which objects are defined once, and in which tag.

        Returns:
            The shared object families, and each one's home tag.
        """
        uses: dict[str, set[int]] = {}
        home: dict[str, str] = {}
        for index, (_path, _method, op) in enumerate(self.operations):
            tag = op.get("tags", ["other"])[0]
            for body in self.operation_bodies(op):
                for name in self.body_refs(body):
                    fam = family_of(name)
                    uses.setdefault(fam, set()).add(index)
                    home.setdefault(fam, tag)

        # An object nested in another is always defined once, in the
        # home of the first object that nests it.
        #
        nested: dict[str, str] = {}
        for name, schema in self.schemas.items():
            for prop in schema.get("properties", {}).values():
                for ref in self.field_refs(prop):
                    nested.setdefault(family_of(ref), family_of(name))
        changed = True
        while changed:
            changed = False
            for fam, parent in nested.items():
                if fam not in home and parent in home:
                    home[fam] = home[parent]
                    changed = True

        shared = {fam for fam, ops in uses.items() if len(ops) > 1}
        shared |= set(nested)
        return shared, home

    ####################################################################
    #
    def fields(self, fam: str) -> list[Field]:
        """The fields of object `fam`, merging its response and request shapes.

        A field only the response has is read-only, one only the request
        has is write-only, and a writable field is required or optional
        as the request (create) shape says.
        """
        response = self.schemas.get(fam)
        request = self.schemas.get(f"{fam}Request")
        out: dict[str, Field] = {}
        if response is not None:
            writable = (request or {}).get("properties", {})
            for name, schema in response.get("properties", {}).items():
                flags = []
                if request is not None and (
                    schema.get("readOnly") or name not in writable
                ):
                    flags.append("read-only")
                out[name] = Field(name, schema, flags)
        if request is not None:
            required = set(request.get("required", []))
            for name, schema in request.get("properties", {}).items():
                wanted = "required" if name in required else "optional"
                if name in out:
                    out[name].flags.append(wanted)
                else:
                    flags = [wanted] if response is None else ["write-only"]
                    out[name] = Field(name, schema, flags)
        return list(out.values())

    ####################################################################
    #
    def type_label(self, schema: dict) -> str:
        """A short type name: `uuid`, `array of Budget`, `decimal | null`."""
        label = self._bare_type(schema)
        if schema.get("nullable"):
            label += " | null"
        return label

    ####################################################################
    #
    def _bare_type(self, schema: dict) -> str:
        if (name := ref_name(schema)) is not None:
            return "enum" if self.is_enum(name) else family_of(name)
        for key in ("oneOf", "anyOf"):
            if key in schema:
                labels = [self._bare_type(v) for v in schema[key]]
                return " | ".join(dict.fromkeys(labels))
        typ = schema.get("type")
        if typ == "array":
            return f"array of {self._bare_type(schema.get('items', {}))}"
        if typ == "object" and isinstance(
            schema.get("additionalProperties"), dict
        ):
            return f"map of {self._bare_type(schema['additionalProperties'])}"
        if typ == "string" and schema.get("format"):
            return schema["format"]
        if "enum" in schema:
            return "enum"
        return typ or "any"

    ####################################################################
    #
    def placeholder(self, schema: dict, key: str = "") -> str:
        """A JSON-looking value of the shape `schema` describes."""
        if (name := ref_name(schema)) is not None:
            target = self.schemas.get(name, {})
            if "enum" in target:
                return json.dumps(next(v for v in target["enum"] if v))
            return "{...}"
        if "enum" in schema:
            return json.dumps(next((v for v in schema["enum"] if v), ""))
        for combinator in ("oneOf", "anyOf"):
            if combinator in schema:
                return self.placeholder(schema[combinator][0], key)
        match schema.get("type"):
            case "array":
                return f"[{self.placeholder(schema.get('items', {}), key)}]"
            case "object":
                values = schema.get("additionalProperties")
                if isinstance(values, dict):
                    return f'{{"<key>": {self.placeholder(values)}}}'
                return "{}"
            case "integer":
                return "0"
            case "number":
                return "0.0"
            case "boolean":
                return "false"
            case "string":
                fmt = schema.get("format", "")
                if fmt in PLACEHOLDERS:
                    return PLACEHOLDERS[fmt]
                if key == "currency" or key.endswith("_currency"):
                    return '"USD"'
                return '"string"'
        return "null"

    ####################################################################
    #
    def field_comment(self, fld: Field) -> tuple[str, str]:
        """A field's type-and-flags summary, and its description."""
        schema = fld.schema
        description = schema.get("description", "")
        prose, values = split_enum_description(description)
        if not values:
            members = [schema, *schema.get("oneOf", []), *schema.get("anyOf", [])]
            for member in members:
                target = self.schemas.get(ref_name(member) or "", {})
                if "enum" in target:
                    values += split_enum_description(
                        target.get("description", "")
                    )[1]
        if values:
            choices = ", ".join(
                f'"{v}"' if label == v else f'"{v}" {label}'
                for v, label in values
                if v
            )
            prose = f"{prose} One of: {choices}." if prose else choices
        summary = " · ".join([self.type_label(schema), *fld.flags])
        return summary, prose.strip()

    ####################################################################
    #
    def object_block(self, fields: list[Field]) -> list[str]:
        """A commented `jsonc` block of an object's fields."""
        lines = ["```jsonc", "{"]
        for i, fld in enumerate(fields):
            comma = "," if i < len(fields) - 1 else ""
            value = self.placeholder(fld.schema, fld.name)
            code = f'  "{fld.name}": {value}{comma}'
            summary, prose = self.field_comment(fld)
            trailing = f"// {summary}" + (f" -- {prose}" if prose else "")
            pad = max(COMMENT_COLUMN, len(code) + 2)
            if pad + len(trailing) <= LINE_WIDTH:
                lines.append(code.ljust(pad) + trailing)
                continue
            for text in textwrap.wrap(prose, LINE_WIDTH - 5):
                lines.append(f"  // {text}")
            lines.append(code.ljust(pad) + f"// {summary}")
        lines += ["}", "```"]
        return lines

    ####################################################################
    #
    def inline_body(self, schema: dict) -> list[str]:
        """A body only one endpoint uses, shown in full at that endpoint."""
        if schema.get("type") == "array":
            items = schema.get("items", {})
            if (name := ref_name(items)) is not None:
                fields = self.fields(family_of(name))
                return self.object_block(fields) + self.nested_line(fields)
            return [
                "```jsonc",
                f"[{self.placeholder(items)}]  // {self.type_label(schema)}",
                "```",
            ]
        if (name := ref_name(schema)) is not None:
            fields = self.fields(family_of(name))
        else:
            required = set(schema.get("required", []))
            fields = [
                Field(
                    name,
                    prop,
                    ["required" if name in required else "optional"],
                )
                for name, prop in schema.get("properties", {}).items()
            ]
        return self.object_block(fields) + self.nested_line(fields)

    ####################################################################
    #
    def nested_line(self, fields: list[Field]) -> list[str]:
        """A line linking the objects a block's fields refer to."""
        refs = sorted(
            {
                family_of(ref)
                for fld in fields
                for ref in self.field_refs(fld.schema)
            }
        )
        if not refs:
            return []
        links = ", ".join(self.object_link(fam) for fam in refs)
        return ["", f"Nested objects: {links}."]

    ####################################################################
    #
    def object_link(self, fam: str) -> str:
        """A Markdown link to object `fam`'s definition."""
        return f"[{fam}]({anchor(fam)})"

    ####################################################################
    #
    def body_lines(self, schema: dict, verb: str) -> list[str]:
        """How an endpoint's request (`Send`) or response body is shown."""
        name = ref_name(schema)
        if name is not None and (item := self.page_item(name)):
            link = self.object_link(family_of(item))
            return [f"{verb} a page of {link} (see Pagination)."]
        if name is not None and family_of(name) in self.shared:
            note = ""
            if verb == "Send":
                note = (
                    " -- any subset of its writable fields"
                    if name.startswith("Patched")
                    else " -- its writable fields"
                )
            return [f"{verb} {self.object_link(family_of(name))}{note}."]
        items = ref_name(schema.get("items", {}))
        if schema.get("type") == "array" and items is not None:
            if family_of(items) in self.shared:
                link = self.object_link(family_of(items))
                return [f"{verb} an array of {link}."]
            return [f"{verb} an array of:", "", *self.inline_body(schema)]
        return [f"{verb}:", "", *self.inline_body(schema)]

    ####################################################################
    #
    def example_block(self, title: str, value: Any) -> list[str]:
        """A worked example value, as a plain `json` block."""
        return [
            "",
            f"*{title}:*",
            "",
            "```json",
            json.dumps(value, indent=2),
            "```",
        ]

    ####################################################################
    #
    def parameters(self, op: dict, paginated: bool) -> list[str]:
        """A table of an operation's parameters.

        The pagination parameters are described once (see Pagination),
        and a path parameter with no description is already in the path.
        """
        params = [
            p
            for p in op.get("parameters", [])
            if not (paginated and p["name"] in ("page", "page_size"))
            and not (p["in"] == "path" and not p.get("description"))
        ]
        if not params:
            return []
        lines = [
            "| Parameter | In | Type | | Description |",
            "|---|---|---|---|---|",
        ]
        for p in params:
            prose, values = split_enum_description(p.get("description", ""))
            if values:
                prose = ", ".join(f"`{v}` {label}" for v, label in values if v)
            flag = "required" if p.get("required") else ""
            typ = self.type_label(p.get("schema", {}))
            lines.append(
                f"| `{p['name']}` | {p['in']} | {typ} | {flag} | {prose} |"
            )
        return lines + [""]

    ####################################################################
    #
    def operation(self, path: str, method: str, op: dict) -> list[str]:
        """One endpoint: summary, parameters, bodies, examples, errors."""
        lines = [f"#### `{method.upper()} {path}`", ""]
        summary = op.get("summary", "")
        description = op.get("description", "")
        if summary:
            lines += [f"**{summary.rstrip('.')}.**", ""]
        if description and description != summary:
            lines += [description, ""]

        responses = op.get("responses", {})
        paginated = any(
            self.page_item(ref_name(r["content"][JSON]["schema"]) or "")
            for code, r in responses.items()
            if code.startswith("2") and JSON in r.get("content", {})
        )
        lines += self.parameters(op, paginated)

        worked = self.worked.get(op.get("operationId", ""), {})
        if worked:
            lines += [f"Example: {worked['summary'].rstrip('.')}."]
            if worked.get("description"):
                lines += ["", worked["description"]]
            lines.append("")

        request = op.get("requestBody", {}).get("content", {}).get(JSON)
        if request:
            lines += self.body_lines(request["schema"], "Send")
            if "request" in worked:
                lines += self.example_block("Example request", worked["request"])
            lines.append("")

        for code, response in responses.items():
            if not code.startswith("2"):
                continue
            media = response.get("content", {}).get(JSON)
            if media is None:
                lines += [f"**{code}** -- no body.", ""]
                continue
            lines += [f"**{code}**", ""]
            lines += self.body_lines(media["schema"], "Returns")
            example = worked.get("response", {})
            if example.get("status") == code:
                title = example.get("summary") or "Example response"
                lines += self.example_block(
                    f"Example response -- {title.rstrip('.')}", example["body"]
                )
            lines.append("")

        own = [
            (code, r)
            for code, r in responses.items()
            if code[0] in "45" and not r.get(COMMON_RESPONSE)
        ]
        if own:
            lines += ["Errors:", ""]
            for code, r in own:
                body = ref_name(
                    r.get("content", {}).get(JSON, {}).get("schema", {})
                )
                lines.append(
                    f"- **{code}** ({body}) -- {r.get('description', '')}"
                )
            lines.append("")
        common = [c for c, r in responses.items() if r.get(COMMON_RESPONSE)]
        if common:
            codes = " · ".join(f"`{c}`" for c in common)
            lines += [f"Common responses: {codes}", ""]
        return lines

    ####################################################################
    #
    def extends(self, fam: str) -> str | None:
        """The largest other object whose fields `fam` has all of, if any."""
        names = {f.name for f in self.fields(fam)}
        bases = [
            other
            for other in self.shared
            if other != fam
            and (other_names := {f.name for f in self.fields(other)})
            and other_names < names
        ]
        return max(bases, key=lambda b: len(self.fields(b)), default=None)

    ####################################################################
    #
    def object_definition(self, fam: str) -> list[str]:
        """An object's single definition, which endpoints link to.

        An object with every field of another shared object (plus some)
        is shown as that object plus its extra fields.  The component's
        own description is the serializer's docstring, written for
        developers of this code rather than its clients, so it is left
        out.
        """
        lines = [f"#### {fam} object", ""]
        fields = self.fields(fam)
        if base := self.extends(fam):
            inherited = {f.name for f in self.fields(base)}
            fields = [f for f in fields if f.name not in inherited]
            lines += [f"Every field of {self.object_link(base)}, plus:", ""]
        lines += self.object_block(fields) + self.nested_line(fields)
        return lines + [""]

    ####################################################################
    #
    def common_responses(self) -> list[str]:
        """The table of the error statuses endpoints share."""
        seen: dict[tuple[str, str], str] = {}
        for _path, _method, op in self.operations:
            for code, r in op.get("responses", {}).items():
                if r.get(COMMON_RESPONSE):
                    body = ref_name(r["content"][JSON]["schema"]) or ""
                    seen.setdefault((code, r.get("description", "")), body)
        lines = [
            "## Common responses",
            "",
            "Error statuses shared by every endpoint of a kind.  Each "
            "endpoint lists the ones that apply to it.",
            "",
            "| Status | Body | Meaning |",
            "|---|---|---|",
        ]
        for (code, description), body in sorted(seen.items()):
            lines.append(f"| `{code}` | {body} | {description} |")
        return lines + [""]

    ####################################################################
    #
    def render(self) -> str:
        """The whole reference."""
        info = self.spec.get("info", {})
        lines = [f"# {info.get('title', 'API Reference')}", ""]
        lines += [f"Version {info.get('version', 'unknown')}.", ""]
        if info.get("description"):
            lines += [info["description"].strip(), ""]
        lines += self.common_responses()
        lines += ["## Endpoints", ""]

        by_tag: dict[str, list[tuple[str, str, dict]]] = {}
        for path, method, op in self.operations:
            tag = op.get("tags", ["other"])[0]
            by_tag.setdefault(tag, []).append((path, method, op))
        for tag, ops in by_tag.items():
            lines += [f"### {tag}", ""]
            for path, method, op in ops:
                lines += self.operation(path, method, op)
            homed = sorted(f for f in self.shared if self.home.get(f) == tag)
            for fam in homed:
                lines += self.object_definition(fam)
        markdown = "\n".join(lines).rstrip() + "\n"
        self.check_links(markdown)
        return markdown

    ####################################################################
    #
    def check_links(self, markdown: str) -> None:
        """Refuse a reference with an object link that goes nowhere.

        Raises:
            ValueError: If a link names an object with no definition.
        """
        defined = {
            anchor(m.group(1))
            for m in re.finditer(r"^#### (\S+) object$", markdown, re.M)
        }
        linked = set(re.findall(r"\]\((#[\w-]+-object)\)", markdown))
        if missing := sorted(linked - defined):
            raise ValueError(f"links to undefined objects: {missing}")


####################################################################
#
def load_examples(directory: Path) -> dict[str, dict]:
    """The worked examples in `directory`, keyed by operationId."""
    return {
        path.stem: json.loads(path.read_text())
        for path in sorted(directory.glob("*.json"))
    }


####################################################################
#
def generate_markdown(
    spec: dict[str, Any], examples: dict[str, dict] | None = None
) -> str:
    """Render an OpenAPI spec dict as the Markdown API reference."""
    return Reference(spec, examples or {}).render()


########################################################################
#
def main() -> None:
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <openapi.yaml> <examples-dir> <output.md>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    examples_dir = Path(sys.argv[2])
    output_path = Path(sys.argv[3])

    with open(input_path) as f:
        spec = yaml.safe_load(f)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(generate_markdown(spec, load_examples(examples_dir)))

    print(f"Generated {output_path} from {input_path}")


if __name__ == "__main__":
    main()
