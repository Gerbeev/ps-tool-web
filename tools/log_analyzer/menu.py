#!/usr/bin/env python3
"""Interactive, standalone console front end for the job log analyzer."""

from __future__ import annotations

import codecs
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Callable, TextIO

import analyze

TOOL_DIR = Path(__file__).resolve().parent
BASE_CONFIG = TOOL_DIR / "config.json"


def read_config(path: Path) -> dict:
    config = analyze.load_config(path)
    if not config["environments"]:
        raise ValueError("At least one approved environment must be configured")
    return config


def save_config(config: dict, *, destination: Path = BASE_CONFIG) -> None:
    """Atomically persist user-edited settings in the single config file."""
    config = analyze.validate_config(config)
    if not config["environments"]:
        raise ValueError("At least one approved environment must be configured")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", prefix=".config-",
            suffix=".tmp", dir=destination.parent, delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            json.dump(config, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, destination)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


class ConsoleMenu:
    def __init__(
        self, *, read: Callable[[str], str] | None = None,
        output: TextIO | None = None,
        config_path: Path | None = None,
    ) -> None:
        self.read = read if read is not None else input
        self.output = output if output is not None else sys.stdout
        self.config_path = config_path if config_path is not None else BASE_CONFIG

    def show(self, message: str = "") -> None:
        print(message, file=self.output)

    def ask(self, prompt: str) -> str:
        try:
            return self.read(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            self.show("\nInput cancelled.")
            return "0"

    def load(self) -> tuple[Path, dict]:
        return self.config_path, read_config(self.config_path)

    def save(self, config: dict) -> None:
        # Validate the edited data before altering any file.
        # A temporary validation file isn't needed: the changes below only
        # mutate an already validated structure and validate new fields.
        save_config(config, destination=self.config_path)
        self.show(f"Settings saved: {self.config_path}")

    def list_environments(self, config: dict) -> list[str]:
        names = [name for name in analyze.ALLOWED_ENVIRONMENTS if name in config["environments"]]
        self.show("\nConfigured environments:")
        for number, name in enumerate(names, 1):
            entry = config["environments"][name]
            root = entry.get("logs_root", "").strip()
            detail = entry.get("description", "")
            self.show(f"  {number}. {name:<6} {'[configured]' if root else '[path missing]'}  {detail}")
        return names

    def choose_environment(self, config: dict) -> str | None:
        names = self.list_environments(config)
        choice = self.ask("Environment number/code (0 = back): ").upper()
        if choice == "0" or not choice:
            return None
        if choice.isdecimal() and 1 <= int(choice) <= len(names):
            return names[int(choice) - 1]
        if choice in config["environments"]:
            return choice
        self.show("Invalid environment selection.")
        return None

    def run_analysis(self, mode: str = "inventory") -> None:
        try:
            path, config = self.load()
        except (OSError, ValueError, json.JSONDecodeError, LookupError) as exc:
            self.show(f"ERROR: Cannot load configuration: {exc}")
            return
        environment = self.choose_environment(config)
        if environment is None:
            return
        entry = config["environments"][environment]
        root = entry["logs_root"].strip()
        if not root:
            self.show(f"No log path configured for {environment}. Use Settings (9) first.")
            return
        output = analyze.DEFAULT_OUTPUT_DIR / environment / "<COB_YYYYMMDD>" / "jobs.csv"
        self.show(f"\nEnvironment : {environment}")
        self.show(f"Logs root   : {root}")
        policy = analyze.policy_from_config(config)
        if mode == "inventory":
            self.show("Scope       : Metadata inventory only (never reads log contents)")
        else:
            self.show("Scope       : Enrich pending/stale/changed logs (read-only SMB)")
        self.show(f"COB window  : Latest {policy.cob_scan_limit} root-level COB folders")
        self.show(f"Retention   : Minimum {policy.min_active_days} days + {policy.quiet_hours}h without changes")
        self.show(f"SMB readers : {policy.read_workers} (bounded concurrent read-only handles)")
        self.show(f"CSV output  : {output}")
        self.show("Unchanged CSVs remain untouched. Closed COBs are skipped.")
        prompt = "Start inventory? [y/N]: " if mode == "inventory" else "Start enrichment? [y/N]: "
        if self.ask(prompt).lower() not in {"y", "yes"}:
            self.show("Parsing cancelled.")
            return
        self.show("\nScanning metadata..." if mode == "inventory" else "\nEnriching logs...")
        result = analyze.main(["--config", str(path), "--env", environment, "--mode", mode])
        if result == 0:
            self.show("Inventory completed successfully." if mode == "inventory" else "Enrichment completed successfully.")
        elif result == 2:
            self.show("Operation finished with skipped files. Review the messages above.")
        else:
            self.show("Parsing failed. Check errors above; reports not yet published were preserved.")
        self.ask("Press Enter to return to the main menu...")

    def edit_root(self, config: dict) -> None:
        environment = self.choose_environment(config)
        if environment is None:
            return
        entry = config["environments"][environment]
        self.show(f"Current log root: {entry['logs_root'] or '(not set)'}")
        root = self.ask("New Logs root (empty = cancel): ").strip('"')
        if not root or root == "0":
            self.show("No changes made.")
            return
        entry["logs_root"] = root
        self.save(config)

    def edit_description(self, config: dict) -> None:
        environment = self.choose_environment(config)
        if environment is None:
            return
        entry = config["environments"][environment]
        self.show(f"Current description: {entry.get('description', '')}")
        value = self.ask("New description (empty = cancel): ")
        if not value or value == "0":
            self.show("No changes made.")
            return
        entry["description"] = value
        self.save(config)

    def edit_encoding(self, config: dict) -> None:
        self.show(f"Current encoding: {config.get('encoding', 'utf-8-sig')}")
        encoding = self.ask("Python text encoding (empty = cancel): ")
        if not encoding or encoding == "0":
            return
        try:
            codecs.lookup(encoding)
        except LookupError:
            self.show("Unknown text encoding.")
            return
        config["encoding"] = encoding
        self.save(config)

    def edit_incremental(self, config: dict, key: str, prompt: str) -> None:
        defaults = {
            "min_active_days": 7, "quiet_hours": 72, "recent_minutes": 5,
            "read_workers": 4, "cob_scan_limit": 7,
        }
        max_allowed = 16 if key == "read_workers" else (10000 if key == "cob_scan_limit" else 87600)
        current = config.get("incremental", {}).get(key, defaults[key])
        self.show(f"Current {key}: {current}")
        value = self.ask(f"{prompt} (1-{max_allowed}, empty = cancel): ")
        if not value or value == "0":
            return
        try:
            number = int(value)
        except ValueError:
            self.show("Enter a whole number.")
            return
        if not 1 <= number <= max_allowed:
            self.show(f"Value must be between 1 and {max_allowed}.")
            return
        config.setdefault("incremental", {})[key] = number
        self.save(config)

    def settings(self) -> None:
        while True:
            try:
                _, config = self.load()
            except (OSError, ValueError, json.JSONDecodeError, LookupError) as exc:
                self.show(f"ERROR: Cannot load configuration: {exc}")
                return
            self.show("\n=== Settings ===")
            self.show(f"Config: {self.config_path}")
            self.show("1. Edit environment log path")
            self.show("2. Edit environment description")
            self.show("3. Change log file encoding")
            self.show("4. Minimum active COB days")
            self.show("5. Quiet hours before COB finalization")
            self.show("6. Recent log activity window (minutes)")
            self.show("7. Concurrent SMB readers (1-16)")
            self.show("8. Latest COB folders to scan")
            self.show("0. Back")
            action = self.ask("Select: ")
            if action == "0":
                return
            operations = {
                "1": self.edit_root, "2": self.edit_description,
                "3": self.edit_encoding,
                "4": lambda cfg: self.edit_incremental(cfg, "min_active_days", "Minimum active days"),
                "5": lambda cfg: self.edit_incremental(cfg, "quiet_hours", "Quiet hours"),
                "6": lambda cfg: self.edit_incremental(cfg, "recent_minutes", "Recent activity (minutes)"),
                "7": lambda cfg: self.edit_incremental(cfg, "read_workers", "Concurrent SMB readers"),
                "8": lambda cfg: self.edit_incremental(cfg, "cob_scan_limit", "Latest COB folders to scan"),
            }
            handler = operations.get(action)
            if handler is None:
                self.show("Invalid option.")
                continue
            try:
                handler(config)
            except OSError as exc:
                self.show(f"ERROR: Cannot save settings: {exc}")

    def run(self) -> int:
        while True:
            self.show("\n================================")
            self.show("       JOB LOG ANALYZER")
            self.show("================================")
            self.show("1. Inventory logs (metadata only)")
            self.show("2. Enrich reports (parse log contents)")
            self.show("9. Settings")
            self.show("0. Exit")
            choice = self.ask("Select: ")
            if choice == "0":
                self.show("Goodbye.")
                return 0
            if choice == "1":
                self.run_analysis("inventory")
            elif choice == "2":
                self.run_analysis("enrich")
            elif choice == "9":
                self.settings()
            else:
                self.show("Invalid option.")


def main(argv: list[str] | None = None) -> int:
    if argv == ["--check"]:
        path = BASE_CONFIG
        try:
            config = read_config(path)
        except (OSError, ValueError, json.JSONDecodeError, LookupError) as exc:
            print(f"ERROR: Invalid config at {path}: {exc}", file=sys.stderr)
            return 1
        print(f"Python: {sys.version.split()[0]}")
        print(f"Configuration: {path}")
        print(f"Environments: {', '.join(config['environments'])}")
        print("Dependencies: Python standard library only; no pip install required.")
        return 0
    if argv:
        print("Usage: menu.py [--check]", file=sys.stderr)
        return 2
    return ConsoleMenu().run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
