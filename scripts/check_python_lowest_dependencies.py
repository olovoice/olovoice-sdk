#!/usr/bin/env python3
"""Resolve and audit the lowest supported Python runtime dependency set."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any


SDK_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SDK_ROOT / "python"
EXPECTED_DECLARATIONS = {
    "httpcore": "httpcore>=1.0.9,<2",
    "httpx": "httpx>=0.28.1,<1",
}
EXPECTED_LOWEST_VERSIONS = {
    "h11": "0.16.0",
    "httpcore": "1.0.9",
    "httpx": "0.28.1",
}


def run(*args: str, capture: bool = False) -> str:
    result = subprocess.run(
        args,
        check=True,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE if capture else None,
        text=True,
    )
    return result.stdout.strip() if capture else ""


parser = argparse.ArgumentParser()
parser.add_argument(
    "--python",
    default="3.11",
    help="Python interpreter or version used for the lowest-supported environment.",
)
parser.add_argument(
    "--uv",
    default="uv",
    help="Path to the reviewed uv executable (CI pins uv 0.12.3).",
)
args = parser.parse_args()

pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
dependencies = pyproject["project"]["dependencies"]
if not isinstance(dependencies, list) or not all(
    isinstance(dependency, str) for dependency in dependencies
):
    raise SystemExit("project.dependencies must be a list of requirement strings.")

for dependency_name, expected_declaration in EXPECTED_DECLARATIONS.items():
    matching = [
        dependency
        for dependency in dependencies
        if dependency.lower().startswith(dependency_name)
    ]
    if matching != [expected_declaration]:
        raise SystemExit(
            f"Expected exactly {expected_declaration!r} in project.dependencies; "
            f"got {matching!r}."
        )

with tempfile.TemporaryDirectory(prefix="olovoice-lowest-dependencies-") as temp_dir:
    environment = Path(temp_dir) / ".venv"
    environment_python = environment / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    run(args.uv, "venv", "--python", args.python, str(environment))
    run(
        args.uv,
        "pip",
        "install",
        "--python",
        str(environment_python),
        "--resolution",
        "lowest-direct",
        "--only-binary",
        ":all:",
        *dependencies,
        "h11==0.16.0",
    )

    inspection_code = """
import importlib.metadata
import json
import sysconfig

print(json.dumps({
    "versions": {
        name: importlib.metadata.version(name)
        for name in ("h11", "httpcore", "httpx")
    },
    "paths": sorted({
        sysconfig.get_paths()["purelib"],
        sysconfig.get_paths()["platlib"],
    }),
}))
"""
    inspection: dict[str, Any] = json.loads(
        run(str(environment_python), "-c", inspection_code, capture=True)
    )
    if inspection["versions"] != EXPECTED_LOWEST_VERSIONS:
        raise SystemExit(
            "Lowest dependency resolution drifted: "
            f"{inspection['versions']}; expected {EXPECTED_LOWEST_VERSIONS}."
        )

    audit_args = [
        sys.executable,
        "-m",
        "pip_audit",
        "--strict",
        "--progress-spinner",
        "off",
    ]
    for installation_path in inspection["paths"]:
        audit_args.extend(("--path", installation_path))
    run(*audit_args)

print(
    "Lowest supported dependency gate passed: "
    "httpx==0.28.1, httpcore==1.0.9, h11==0.16.0."
)
