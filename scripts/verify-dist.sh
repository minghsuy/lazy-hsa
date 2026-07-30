#!/usr/bin/env bash
# Verify the package users install, not only the editable source checkout.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if (( $# > 1 )); then
  echo "usage: scripts/verify-dist.sh [ARTIFACT_DIR]" >&2
  exit 2
fi
KEEP_DIST=0
if (( $# == 1 )); then
  mkdir -p "$1"
  DIST_DIR="$(cd "$1" && pwd)"
  [[ -z "$(find "$DIST_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]] || {
    echo "error: artifact directory is not empty: $DIST_DIR" >&2
    exit 1
  }
  KEEP_DIST=1
else
  DIST_DIR="$(mktemp -d)"
fi
VENV_PARENT="$(mktemp -d)"
cleanup() {
  rm -rf "$VENV_PARENT"
  if (( ! KEEP_DIST )); then
    rm -rf "$DIST_DIR"
  fi
}
trap cleanup EXIT

cd "$REPO_DIR"

uv build --out-dir "$DIST_DIR"

mapfile -t wheels < <(find "$DIST_DIR" -maxdepth 1 -type f -name 'lazy_hsa-*.whl' -print)
mapfile -t sdists < <(find "$DIST_DIR" -maxdepth 1 -type f -name 'lazy_hsa-*.tar.gz' -print)
if (( ${#wheels[@]} != 1 || ${#sdists[@]} != 1 )); then
  echo "error: expected exactly one wheel and one sdist" >&2
  exit 1
fi
WHEEL="${wheels[0]}"

uv run python - "$WHEEL" <<'PY'
import sys
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

wheel = Path(sys.argv[1])
with zipfile.ZipFile(wheel) as archive:
    metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
    if len(metadata_names) != 1:
        raise SystemExit(f"expected one METADATA file, found {metadata_names}")
    metadata = Parser().parsestr(archive.read(metadata_names[0]).decode())

with Path("pyproject.toml").open("rb") as handle:
    project = tomllib.load(handle)["project"]

if metadata["Version"] != project["version"]:
    raise SystemExit(
        f"wheel version {metadata['Version']} does not match pyproject {project['version']}"
    )

requirements = [
    canonicalize_name(Requirement(value).name)
    for value in metadata.get_all("Requires-Dist", [])
]
for required_name in ("pillow", "pillow-heif"):
    count = requirements.count(required_name)
    if count != 1:
        raise SystemExit(f"expected one {required_name} requirement, found {count}")

with Path("uv.lock").open("rb") as handle:
    packages = tomllib.load(handle)["package"]
root = next(package for package in packages if package["name"] == "lazy-hsa")
if root["version"] != project["version"]:
    raise SystemExit(
        f"lock root version {root['version']} does not match pyproject {project['version']}"
    )
root_dependencies = {dependency["name"] for dependency in root["dependencies"]}
resolved_names = {package["name"] for package in packages}
if "pillow-heif" not in root_dependencies or "pillow-heif" not in resolved_names:
    raise SystemExit("uv.lock does not preserve pillow-heif as a resolved direct dependency")
PY

uv venv --python 3.12 "$VENV_PARENT/venv"
uv pip install --python "$VENV_PARENT/venv/bin/python" "$WHEEL"
cd "$VENV_PARENT"
"$VENV_PARENT/venv/bin/lazy-hsa" --help >/dev/null
"$VENV_PARENT/venv/bin/python" <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import pillow_heif
from PIL import Image

from src.processors.llm_extractor import VisionExtractor

module_path = Path(
    __import__("src.processors.llm_extractor", fromlist=[""]).__file__
).resolve()
if "site-packages" not in module_path.parts:
    raise SystemExit(
        f"installed-wheel smoke test imported repository code: {module_path}"
    )

pillow_heif.register_heif_opener()
with TemporaryDirectory() as directory:
    source = Path(directory) / "receipt.heic"
    pillow_heif.from_pillow(Image.new("RGB", (2, 2), "white")).save(source)
    extractor = VisionExtractor()
    expected = object()
    extractor.extract_from_image = Mock(return_value=expected)
    actual = extractor._extract_with_conversion(source, ".heic")
    if actual is not expected:
        raise SystemExit("installed-wheel HEIC conversion did not reach image extraction")
PY
