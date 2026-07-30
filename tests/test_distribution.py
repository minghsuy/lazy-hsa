"""Installed-distribution contract tests."""

import subprocess
from pathlib import Path


def test_built_distribution_contract():
    """The wheel must preserve its runtime dependencies and HEIC path."""
    repo_dir = Path(__file__).resolve().parents[1]
    subprocess.run([repo_dir / "scripts" / "verify-dist.sh"], cwd=repo_dir, check=True)
