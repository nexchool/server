"""CLI: seed a tenant's academic foundation from a per-school config file.

Usage (from server/, with PYTHONPATH including the server root):
    PYTHONPATH=. python scripts/seed_school.py scripts/schools/<subdomain>.yaml
    PYTHONPATH=. python scripts/seed_school.py scripts/schools/<sub>.yaml --dry-run
    PYTHONPATH=. python scripts/seed_school.py <path> --tenant <subdomain> --no-complete

With Docker Compose (from school-erp-infra/, stack running):
    docker compose --env-file .env.production exec api \
        python scripts/seed_school.py scripts/schools/<subdomain>.yaml

The tenant MUST already exist; the script aborts if the subdomain is not found.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app import create_app
from core.models import Tenant
from modules.school_setup.seed_service import SeedValidationError, seed_school


def _load_config(path: Path) -> dict:
    # Validate the extension before reading so an unsupported type fails with a
    # clear message rather than an incidental read error.
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        import yaml  # PyYAML

        return yaml.safe_load(path.read_text(encoding="utf-8"))
    if suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    raise SystemExit(f"Unsupported config extension '{suffix}' (use .yaml/.yml/.json)")


def _resolve_tenant(subdomain: str) -> Tenant:
    tenant = Tenant.query.filter_by(subdomain=subdomain).first()
    if not tenant:
        raise SystemExit(
            f'Tenant with subdomain "{subdomain}" not found. Create it before seeding.'
        )
    return tenant


def _print_summary(subdomain: str, result: dict) -> None:
    print("\n" + "=" * 60)
    print(f"School seed - tenant '{subdomain}'")
    print("=" * 60)
    if result.get("dry_run"):
        print("DRY RUN (no writes). Plan:")
        for key, value in result["plan"].items():
            print(f"  {key:16} {value}")
        print("=" * 60 + "\n")
        return
    print(f"Academic year id:    {result['academic_year_id']}")
    print(
        f"Classes:             +{result['classes']['created']} created, "
        f"{result['classes']['skipped']} existed"
    )
    print(
        f"Class-subjects:      +{result['class_subjects']['created']} created, "
        f"{result['class_subjects']['skipped']} existed"
    )
    overall = result["status"]["overall"]
    print(f"Setup ready:         {overall['ready']}")
    print(f"Setup complete:      {result['setup_complete']}")
    if not overall["ready"]:
        print("Not ready - unmet modules:")
        for module, data in result["status"].items():
            if module == "overall" or data.get("ready"):
                continue
            print(f"  - {module}: {data.get('blockers')}")
    print("=" * 60 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed a tenant's academic foundation.")
    parser.add_argument("config", help="Path to the school config (.yaml/.yml/.json)")
    parser.add_argument("--tenant", help="Expected tenant subdomain (guard; must match config)")
    parser.add_argument("--dry-run", action="store_true", help="Validate + print plan; no writes")
    parser.add_argument("--no-complete", action="store_true", help="Do not flip is_setup_complete")
    args = parser.parse_args()

    config = _load_config(Path(args.config))
    subdomain = (config.get("tenant") or {}).get("subdomain")
    if not subdomain:
        raise SystemExit("config.tenant.subdomain is required")
    if args.tenant and args.tenant != subdomain:
        raise SystemExit(f"--tenant '{args.tenant}' != config subdomain '{subdomain}'")

    app = create_app()
    with app.app_context():
        tenant = _resolve_tenant(subdomain)
        try:
            result = seed_school(
                tenant.id,
                config,
                dry_run=args.dry_run,
                complete=not args.no_complete,
            )
        except SeedValidationError as exc:
            print("Validation failed:")
            for err in exc.errors:
                print(f"  - {err}")
            return 1

    _print_summary(subdomain, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
