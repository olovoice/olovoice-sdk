#!/usr/bin/env python3
"""Build and validate Python release artifacts without uploading them."""

from __future__ import annotations

import argparse
import email
import hashlib
import importlib.metadata
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


SDK_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SDK_ROOT / "python"
EXPECTED_BUILD_TOOLS = {
    "build": "1.5.0",
    "hatchling": "1.27.0",
    "twine": "6.2.0",
}


def run(*args: str) -> None:
    subprocess.run(args, check=True, cwd=SDK_ROOT)


parser = argparse.ArgumentParser()
parser.add_argument(
    "--out-dir",
    type=Path,
    required=True,
    help="A new or empty staging directory. Existing artifacts are never reused.",
)
args = parser.parse_args()
out_dir = args.out_dir.expanduser().resolve()

if out_dir in {SDK_ROOT, PROJECT_ROOT, Path.home(), Path("/")}:
    raise SystemExit(f"Refusing unsafe output directory: {out_dir}")
if out_dir.exists() and any(out_dir.iterdir()):
    raise SystemExit(f"Output directory must be empty: {out_dir}")
out_dir.mkdir(parents=True, exist_ok=True)

for distribution, expected_version in EXPECTED_BUILD_TOOLS.items():
    try:
        installed_version = importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError as exc:
        raise SystemExit(
            f"Missing locked build tool {distribution}=={expected_version}. "
            "Run `uv sync --frozen --no-build --extra release "
            "--no-install-project`."
        ) from exc
    if installed_version != expected_version:
        raise SystemExit(
            f"Locked build tool mismatch: {distribution}=={installed_version}; "
            f"expected {expected_version}."
        )

run(sys.executable, str(SDK_ROOT / "scripts" / "check_versions.py"))
run(
    sys.executable,
    "-m",
    "build",
    "--no-isolation",
    "--outdir",
    str(out_dir),
    str(PROJECT_ROOT),
)

artifacts = sorted(path for path in out_dir.iterdir() if path.is_file())
wheels = [path for path in artifacts if path.suffix == ".whl"]
sdists = [path for path in artifacts if path.name.endswith(".tar.gz")]
if len(wheels) != 1 or len(sdists) != 1 or len(artifacts) != 2:
    raise SystemExit(f"Expected exactly one wheel and one sdist, got: {artifacts}")

run(sys.executable, "-m", "twine", "check", *(str(path) for path in artifacts))

with zipfile.ZipFile(wheels[0]) as wheel:
    wheel_files = set(wheel.namelist())
    metadata_files = [
        name for name in wheel_files if name.endswith(".dist-info/METADATA")
    ]
    if len(metadata_files) != 1:
        raise SystemExit(
            f"Wheel must contain exactly one METADATA file, got: {metadata_files}"
        )
    wheel_metadata = email.message_from_bytes(wheel.read(metadata_files[0]))
required_wheel_files = {
    "olovoice/__init__.py",
    "olovoice/_client.py",
    "olovoice/_errors.py",
    "olovoice/_types.py",
    "olovoice/py.typed",
}
missing_wheel_files = required_wheel_files - wheel_files
if missing_wheel_files:
    raise SystemExit(f"Wheel is missing: {sorted(missing_wheel_files)}")
if not any(name.endswith(".dist-info/licenses/LICENSE") for name in wheel_files):
    raise SystemExit("Wheel does not contain the MIT LICENSE file.")

runtime_requirements: dict[str, set[str]] = {}
for raw_requirement in wheel_metadata.get_all("Requires-Dist", []):
    if ";" in raw_requirement:
        continue
    normalized = raw_requirement.replace(" ", "").replace("(", "").replace(")", "")
    for dependency_name in ("httpcore", "httpx"):
        if normalized.startswith(dependency_name):
            runtime_requirements[dependency_name] = set(
                normalized[len(dependency_name) :].split(",")
            )

expected_runtime_requirements = {
    "httpcore": {">=1.0.9", "<2"},
    "httpx": {">=0.28.1", "<1"},
}
if runtime_requirements != expected_runtime_requirements:
    raise SystemExit(
        "Wheel runtime dependency metadata mismatch: "
        f"{runtime_requirements}; expected {expected_runtime_requirements}."
    )

with tarfile.open(sdists[0], "r:gz") as sdist:
    sdist_files = set(sdist.getnames())
if not any(name.endswith("/LICENSE") for name in sdist_files):
    raise SystemExit("Source distribution does not contain the MIT LICENSE file.")

for names in (wheel_files, sdist_files):
    forbidden = [
        name
        for name in names
        if any(
            part in {".venv", ".pytest_cache", "__pycache__"}
            for part in name.split("/")
        )
        or name.endswith(".pyc")
    ]
    if forbidden:
        raise SystemExit(f"Artifact contains development residue: {forbidden}")

manifest_path = out_dir / "SHA256SUMS"
manifest_lines = []
for artifact in artifacts:
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest_lines.append(f"{digest}  {artifact.name}")
manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

for artifact, manifest_line in zip(artifacts, manifest_lines):
    expected_digest = manifest_line.split()[0]
    actual_digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    if actual_digest != expected_digest:
        raise SystemExit(f"SHA256 verification failed for {artifact.name}.")

print("Python release artifacts validated:")
for artifact in artifacts:
    print(f"- {artifact}")
print(f"- {manifest_path}")
