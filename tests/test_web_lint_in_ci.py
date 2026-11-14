"""The web code is linted by ESLint: an npm script and a config (the CI step that runs it is checked in
tests/private/test_web_lint_in_ci.py, which reads this repository's own workflow)."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_lint_script_and_its_config_exist_and_allow_no_warnings():
    scripts = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))["scripts"]
    assert "eslint" in scripts["lint"] and "--max-warnings 0" in scripts["lint"]
    assert (ROOT / "web" / "eslint.config.js").is_file()
