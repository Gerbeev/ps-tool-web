"""Verify that a freshly cloned/installed project has all startup-critical files.

Runs with Python's standard library in --source mode, before dependencies are installed.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_FILES = (
    "app/__init__.py",
    "app/main.py",
    "app/models.py",
    "app/time_utils.py",
    "app/templates/base.html",
    "app/routes/snapshots.py",
    "app/services/snapshot_catalog.py",
    "app/services/snapshot_generation.py",
    "app/templates/snapshots.html",
    "app/templates/browse.html",
    "app/templates/compare.html",
    "app/static/css/custom.css",
    "config/autosys_environments.yaml",
    "config/process_scheduler_environments.yaml",
    "config/identity_map.yaml",
    "config/job_naming_rules.yaml",
    "data/mock/reference_topology_2500.jsonl",
    "data/mock/u1_to_u5_migration_overlay.jsonl",
    ".env.example",
    "requirements.txt",
)


def verify_checkout(*, runtime: bool) -> list[str]:
    errors = [f"Missing required file: {path}" for path in REQUIRED_FILES if not (PROJECT_ROOT / path).is_file()]
    if errors:
        return errors

    # Avoid depending on the current working directory when called from tooling.
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    try:
        from app.time_utils import execution_time_seconds, format_duration_hms

        if format_duration_hms(4233) != "01:10:33" or execution_time_seconds(None, None) is not None:
            errors.append("app.time_utils failed the duration smoke check")
    except (ImportError, AttributeError, TypeError, ValueError) as exc:
        errors.append(f"Cannot import or verify app.time_utils: {exc}")

    if runtime:
        try:
            app_module = importlib.import_module("app.main")
            if not hasattr(app_module, "app"):
                errors.append("app.main has no ASGI 'app' object")
        except Exception as exc:
            errors.append(f"Cannot import app.main: {type(exc).__name__}: {exc}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source", action="store_true", help="Check source checkout before installing dependencies")
    group.add_argument("--runtime", action="store_true", help="Also import the ASGI app after installing dependencies")
    args = parser.parse_args()

    errors = verify_checkout(runtime=args.runtime)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print("Restore missing files from Git or the full project archive.", file=sys.stderr)
        return 1

    print(f"[ps-tool-web] {'Runtime' if args.runtime else 'Source'} checkout verification OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
