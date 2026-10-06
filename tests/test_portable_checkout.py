"""Regression checks for clean-machine install and Git-ready packaging."""

from pathlib import Path

from scripts.verify_checkout import REQUIRED_FILES, PROJECT_ROOT, verify_checkout


def test_all_required_project_files_are_in_checkout():
    assert not verify_checkout(runtime=False)
    assert "app/time_utils.py" in REQUIRED_FILES
    assert "data/mock/reference_topology_2500.jsonl" in REQUIRED_FILES


def test_windows_install_prefers_python_and_does_not_require_py_launcher():
    content = (PROJECT_ROOT / "setup-env.cmd").read_text(encoding="utf-8")
    assert content.index("python -c") < content.index("py -3 -c")
    assert "-m scripts.verify_checkout --source" in content
    assert '".venv\\Scripts\\python.exe" -m pip install -r requirements.txt' in content
    assert '".venv\\Scripts\\python.exe" -m scripts.verify_checkout --runtime' in content
    assert "if errorlevel 1" in content


def test_server_checks_runtime_before_starting():
    content = (PROJECT_ROOT / "start-server.cmd").read_text(encoding="utf-8")
    assert "-m scripts.verify_checkout --runtime" in content
    assert content.index("-m scripts.verify_checkout --runtime") < content.index("-m uvicorn")


def test_gitignore_does_not_hide_critical_sources_and_mocks():
    content = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    patterns = {line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")}
    assert "data/" not in patterns
    assert "app/" not in patterns
    assert "*.py" not in patterns
    assert (PROJECT_ROOT / "app/time_utils.py").is_file()
    assert all((PROJECT_ROOT / relative).is_file() for relative in REQUIRED_FILES)
