"""
Seed provider category aliases from a reviewed YAML file.

Loads the reviewed output of importers/harvest_bofa_categories.py (or a
hand-written file in the same shape) and upserts TransactionCategoryAlias
rows so the resolver maps each provider category string to the chosen
mibudge category.  Any target category that does not yet exist is created
as a global row.

This is a management command rather than a migration because the alias
table evolves as providers add categories -- re-run it whenever the
reviewed file changes.  It is idempotent: existing aliases are updated
in place, unchanged ones are left alone.

Input format::

    provider: bofa            # default provider for entries below
    categories:
    - alias_key: 'groceries:groceries'      # normalized provider key
      category: 'Food & Drink : Groceries'  # target full name
      # 'raw', 'count', 'samples', 'match', 'confidence' are ignored
    - raw: 'Travel : Travel'   # alias_key derived from raw when omitted
      category: 'Travel : Travel'

Entries missing a 'category' are skipped (nothing to map to).  An entry
may set its own 'provider' to override the top-level default.

Usage:

    uv run python app/manage.py seed_category_aliases reviewed.yaml
    uv run python app/manage.py seed_category_aliases reviewed.yaml --dry-run
    uv run python app/manage.py seed_category_aliases reviewed.yaml --provider bofa
"""

# system imports
#
from typing import Any

# 3rd party imports
#
import yaml
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction

# Project imports
#
from moneypools.models import TransactionCategory, TransactionCategoryAlias
from moneypools.service import categories as categories_svc


########################################################################
########################################################################
#
def _get_or_create_global(
    group: str, name: str
) -> tuple[TransactionCategory, bool]:
    """Get or create a global category by exact (case-insensitive) name.

    Unlike the resolver, this does no sub-name fuzzy matching: the
    reviewed file names the exact target, so we honor it verbatim.

    Args:
        group: The target group.
        name: The target name.

    Returns:
        A (category, created) tuple.
    """
    existing = TransactionCategory.objects.filter(
        owner__isnull=True, group__iexact=group, name__iexact=name
    ).first()
    if existing is not None:
        return existing, False
    return (
        TransactionCategory.objects.create(group=group, name=name),
        True,
    )


########################################################################
########################################################################
#
class Command(BaseCommand):
    help = "Seed provider category aliases from a reviewed YAML file."

    ####################################################################
    #
    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "path",
            metavar="FILE",
            help="Path to the reviewed alias YAML file.",
        )
        parser.add_argument(
            "--provider",
            default=None,
            help=(
                "Override the provider for all entries (otherwise the "
                "file's top-level 'provider' is used)."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )

    ####################################################################
    #
    def handle(self, *args: Any, **options: Any) -> None:
        path: str = options["path"]
        try:
            with open(path, encoding="utf-8") as fh:
                doc = yaml.safe_load(fh)
        except OSError as exc:
            raise CommandError(f"Could not read {path}: {exc}") from exc

        if not isinstance(doc, dict):
            raise CommandError(f"{path}: expected a mapping at the top level.")

        default_provider = options["provider"] or doc.get("provider")
        entries = doc.get("categories") or []
        if not entries:
            self.stderr.write("No 'categories' entries found; nothing to do.")
            return

        dry_run: bool = options["dry_run"]
        created_categories = 0
        created_aliases = 0
        updated_aliases = 0
        unchanged = 0
        skipped = 0

        with db_transaction.atomic():
            for entry in entries:
                provider = entry.get("provider") or default_provider
                if not provider:
                    raise CommandError(
                        "No provider set (neither top-level, --provider, "
                        f"nor on the entry): {entry!r}"
                    )

                target = entry.get("category")
                if not target:
                    skipped += 1
                    continue

                # Determine the alias key: explicit, else derived from raw.
                if entry.get("alias_key"):
                    alias_key = str(entry["alias_key"]).casefold()
                elif entry.get("raw"):
                    alias_key = categories_svc.alias_key(
                        *categories_svc.normalize_category(str(entry["raw"]))
                    )
                else:
                    raise CommandError(
                        f"Entry needs 'alias_key' or 'raw': {entry!r}"
                    )

                group, name = categories_svc.normalize_category(str(target))
                category, cat_created = _get_or_create_global(group, name)
                if cat_created:
                    created_categories += 1
                    self.stdout.write(f"  + category {category.full_name!r}")

                existing = TransactionCategoryAlias.objects.filter(
                    provider=provider, alias_key=alias_key
                ).first()
                if existing is None:
                    TransactionCategoryAlias.objects.create(
                        provider=provider,
                        alias_key=alias_key,
                        category=category,
                    )
                    created_aliases += 1
                    self.stdout.write(
                        f"  + alias {provider}:{alias_key} -> "
                        f"{category.full_name!r}"
                    )
                elif existing.category_id != category.id:
                    existing.category = category
                    existing.save(update_fields=["category", "modified_at"])
                    updated_aliases += 1
                    self.stdout.write(
                        f"  ~ alias {provider}:{alias_key} -> "
                        f"{category.full_name!r}"
                    )
                else:
                    unchanged += 1

            if dry_run:
                db_transaction.set_rollback(True)

        prefix = "DRY RUN -- " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}{created_aliases} alias(es) created, "
                f"{updated_aliases} updated, {unchanged} unchanged, "
                f"{skipped} skipped; {created_categories} new global "
                f"categor{'y' if created_categories == 1 else 'ies'}."
            )
        )
