#!/usr/bin/env python3
"""Interactive, standalone console front end for the job log analyzer."""

from __future__ import annotations

import codecs
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Callable, TextIO

import analyze

TOOL_DIR = Path(__file__).resolve().parent
BASE_CONFIG = TOOL_DIR / "config.json"
LOCAL_CONFIG = TOOL_DIR / "config.local.json"
ENV_CODE = re.compile(r"^[A-Z][A-Z0-9_-]{0,15}$")


def active_config_path() -> Path:
    return LOCAL_CONFIG if LOCAL_CONFIG.is_file() else BASE_CONFIG


def read_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        config = json.load(stream)
    if not isinstance(config, dict) or not isinstance(config.get("environments"), dict):
        raise ValueError("Expected a JSON object with an 'environments' object")
    if not config["environments"]:
        raise ValueError("At least one environment must be configured")
    for name, entry in config["environments"].items():
        if not isinstance(name, str) or not ENV_CODE.fullmatch(name):
            raise ValueError(f"Invalid environment code: {name!r}")
        if not isinstance(entry, dict) or not isinstance(entry.get("logs_root"), str):
            raise ValueError(f"Environment {name} requires a string logs_root")
    encoding = config.get("encoding", "utf-8-sig")
    if not isinstance(encoding, str):
        raise ValueError("encoding must be a string")
    codecs.lookup(encoding)
    return config


def save_local_config(config: dict, *, destination: Path = LOCAL_CONFIG) -> None:
    """Persist user-edited settings, keeping the version-controlled template untouched."""
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
        config_source: Path | None = None,
        config_destination: Path | None = None,
    ) -> None:
        self.read = read if read is not None else input
        self.output = output if output is not None else sys.stdout
        self.config_source = config_source
        self.config_destination = config_destination if config_destination is not None else LOCAL_CONFIG

    def show(self, message: str = "") -> None:
        print(message, file=self.output)

    def ask(self, prompt: str) -> str:
        try:
            return self.read(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            self.show("\nInput cancelled.")
            return "0"

    def load(self) -> tuple[Path, dict]:
        path = self.config_source or active_config_path()
        return path, read_config(path)

    def save(self, config: dict) -> None:
        # Validate the edited data before altering any file.
        # A temporary validation file isn't needed: the changes below only
        # mutate an already validated structure and validate new fields.
        save_local_config(config, destination=self.config_destination)
        self.config_source = self.config_destination
        self.show(f"Settings saved: {self.config_destination}")

    def list_environments(self, config: dict) -> list[str]:
        names = list(config["environments"])
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

    def run_analysis(self) -> None:
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
        output = analyze.DEFAULT_OUTPUT_DIR / f"{environment}_jobs.csv"
        self.show(f"\nEnvironment : {environment}")
        self.show(f"Logs root   : {root}")
        self.show("Scope       : All business dates and subfolders (*.log)")
        self.show(f"CSV output  : {output}")
        self.show("Existing CSV for this environment will be replaced after a successful scan.")
        if self.ask("Start parsing? [y/N]: ").lower() not in {"y", "yes"}:
            self.show("Parsing cancelled.")
            return
        self.show("\nScanning logs...")
        result = analyze.main(["--config", str(path), "--env", environment])
        if result == 0:
            self.show("Parsing completed successfully.")
        elif result == 2:
            self.show("Parsing finished with skipped files. Review the messages above.")
        else:
            self.show("Parsing failed. The previous CSV (if any) was preserved.")
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

    def add_environment(self, config: dict) -> None:
        name = self.ask("New environment code (0 = cancel): ").upper()
        if name == "0":
            return
        if not ENV_CODE.fullmatch(name):
            self.show("Use 1-16 characters: A-Z, 0-9, underscore or hyphen (first must be A-Z).")
            return
        if name in config["environments"]:
            self.show("This environment already exists.")
            return
        root = self.ask("Logs root (may be empty for now): ").strip('"')
        description = self.ask("Description (optional): ")
        config["environments"][name] = {"logs_root": root, "description": description}
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

    def settings(self) -> None:
        while True:
            try:
                _, config = self.load()
            except (OSError, ValueError, json.JSONDecodeError, LookupError) as exc:
                self.show(f"ERROR: Cannot load configuration: {exc}")
                return
            self.show("\n=== Settings ===")
            self.show(f"Config: {self.config_source or active_config_path()}")
            self.show("1. Edit environment log path")
            self.show("2. Edit environment description")
            self.show("3. Add environment")
            self.show("4. Change log file encoding")
            self.show("0. Back")
            action = self.ask("Select: ")
            if action == "0":
                return
            operations = {
                "1": self.edit_root, "2": self.edit_description,
                "3": self.add_environment, "4": self.edit_encoding,
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
            self.show("1. Select environment / Parse logs")
            self.show("9. Settings")
            self.show("0. Exit")
            choice = self.ask("Select: ")
            if choice == "0":
                self.show("Goodbye.")
                return 0
            if choice == "1":
                self.run_analysis()
            elif choice == "9":
                self.settings()
            else:
                self.show("Invalid option.")


def main(argv: list[str] | None = None) -> int:
    if argv == ["--check"]:
        path = active_config_path()
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
