#!/usr/bin/env python
#
"""
Generate a Markdown API reference document from an OpenAPI YAML spec.

Usage:
    python generate_api_docs.py <openapi.yaml> <output.md>

The generated markdown is a starting point intended to be reviewed and
refined.  Re-running the script overwrites the output file.
"""

# system imports
import sys
from pathlib import Path

# 3rd party imports
import yaml


########################################################################
#
def _schema_ref_name(ref: str) -> str:
    """Extract the component name from a $ref string."""
    return ref.rsplit("/", 1)[-1]


########################################################################
#
def _resolve_schema(schema: dict, components: dict) -> dict:
    """Resolve a $ref to its component schema, or return as-is."""
    if "$ref" in schema:
        name = _schema_ref_name(schema["$ref"])
        return components.get("schemas", {}).get(name, schema)
    return schema


########################################################################
#
def _format_schema_properties(
    schema: dict, components: dict, indent: int = 0
) -> list[str]:
    """
    Render a schema's properties as a markdown list.
    """
    lines: list[str] = []
    resolved = _resolve_schema(schema, components)

    # Handle oneOf / anyOf (polymorphic)
    for key in ("oneOf", "anyOf"):
        if key in resolved:
            lines.append(f"{'  ' * indent}One of:")
            for variant in resolved[key]:
                name = _schema_ref_name(variant.get("$ref", "?"))
                lines.append(f"{'  ' * indent}- `{name}`")
            return lines

    props = resolved.get("properties", {})
    required = set(resolved.get("required", []))
    for prop_name, prop_schema in props.items():
        prop_resolved = _resolve_schema(prop_schema, components)
        typ = prop_resolved.get("type", "")
        read_only = prop_resolved.get("readOnly", False)
        description = prop_resolved.get("description", "")
        enum = prop_resolved.get("enum")

        qualifiers = []
        if prop_name in required:
            qualifiers.append("required")
        if read_only:
            qualifiers.append("read-only")
        qualifier_str = f" *({', '.join(qualifiers)})*" if qualifiers else ""

        enum_str = ""
        if enum:
            enum_str = f" Enum: {enum}"

        desc_str = f" — {description}" if description else ""
        lines.append(
            f"{'  ' * indent}- **`{prop_name}`** "
            f"(`{typ}`){qualifier_str}{desc_str}{enum_str}"
        )
    return lines


########################################################################
#
def generate_markdown(spec: dict) -> str:
    """
    Convert an OpenAPI spec dict into a Markdown string.
    """
    info = spec.get("info", {})
    components = spec.get("components", {})
    paths = spec.get("paths", {})

    sections: list[str] = []

    # Title and description
    #
    sections.append(f"# {info.get('title', 'API Reference')}")
    sections.append("")
    if info.get("description"):
        sections.append(info["description"])
        sections.append("")
    sections.append(f"**Version:** {info.get('version', 'unknown')}")
    sections.append("")

    # Authentication
    #
    security_schemes = components.get("securitySchemes", {})
    if security_schemes:
        sections.append("## Authentication")
        sections.append("")
        for scheme_name, scheme in security_schemes.items():
            scheme_type = scheme.get("type", "")
            location = scheme.get("in", "")
            name = scheme.get("name", "")
            sections.append(
                f"- **{scheme_name}**: `{scheme_type}` "
                f"(in: `{location}`, name: `{name}`)"
            )
        sections.append("")

    # Group paths by tag
    #
    tag_paths: dict[str, list[tuple[str, str, dict]]] = {}
    for path, methods in paths.items():
        for method, operation in methods.items():
            if method in ("parameters", "servers", "summary", "description"):
                continue
            tags = operation.get("tags", ["Other"])
            for tag in tags:
                tag_paths.setdefault(tag, []).append(
                    (path, method.upper(), operation)
                )

    # Endpoints by tag
    #
    sections.append("## Endpoints")
    sections.append("")

    for tag, operations in tag_paths.items():
        sections.append(f"### {tag}")
        sections.append("")
        for path, method, operation in operations:
            op_id = operation.get("operationId", "")
            summary = operation.get("description", operation.get("summary", ""))
            sections.append(f"#### `{method} {path}`")
            sections.append("")
            if op_id:
                sections.append(f"**Operation:** `{op_id}`")
                sections.append("")
            if summary:
                sections.append(summary)
                sections.append("")

            # Parameters
            #
            params = operation.get("parameters", [])
            if params:
                sections.append("**Parameters:**")
                sections.append("")
                for p in params:
                    p_name = p.get("name", "")
                    p_in = p.get("in", "")
                    p_required = p.get("required", False)
                    p_desc = p.get("description", "")
                    req_str = "required" if p_required else "optional"
                    sections.append(
                        f"- `{p_name}` ({p_in}, {req_str})"
                        + (f" — {p_desc}" if p_desc else "")
                    )
                sections.append("")

            # Request body
            #
            request_body = operation.get("requestBody", {})
            if request_body:
                content = request_body.get("content", {})
                for content_type, media in content.items():
                    schema = media.get("schema", {})
                    sections.append(f"**Request Body** (`{content_type}`):")
                    sections.append("")
                    lines = _format_schema_properties(schema, components)
                    sections.extend(lines)
                    sections.append("")

            # Responses
            #
            responses = operation.get("responses", {})
            for resp_code, resp in responses.items():
                desc = resp.get("description", "")
                sections.append(f"**Response {resp_code}:** {desc}")
                content = resp.get("content", {})
                for _content_type, media in content.items():
                    schema = media.get("schema", {})
                    lines = _format_schema_properties(schema, components)
                    if lines:
                        sections.append("")
                        sections.extend(lines)
                sections.append("")

    # Schemas
    #
    schemas = components.get("schemas", {})
    if schemas:
        sections.append("## Schemas")
        sections.append("")
        for schema_name, schema in schemas.items():
            sections.append(f"### {schema_name}")
            sections.append("")
            if schema.get("description"):
                sections.append(schema["description"])
                sections.append("")
            lines = _format_schema_properties(schema, components)
            sections.extend(lines)
            sections.append("")

    return "\n".join(sections)


########################################################################
#
def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <openapi.yaml> <output.md>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    with open(input_path) as f:
        spec = yaml.safe_load(f)

    markdown = generate_markdown(spec)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(markdown)
        f.write("\n")

    print(f"Generated {output_path} from {input_path}")


if __name__ == "__main__":
    main()
