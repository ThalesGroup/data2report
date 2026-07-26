"""Runs Jest JS unit tests as part of the pytest suite."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def test_js():
    if not (REPO_ROOT / "node_modules").exists():
        subprocess.run(["npm", "ci"], cwd=REPO_ROOT, check=True)
    result = subprocess.run(
        ["npm", "test"], capture_output=True, text=True, cwd=REPO_ROOT
    )
    print(result.stdout)
    print(result.stderr, file=sys.stderr)
    assert result.returncode == 0, "JS tests failed"
