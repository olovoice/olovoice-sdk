#!/usr/bin/env python3
"""Fail when SDK package, lockfile, or User-Agent versions drift."""

from __future__ import annotations

import json
import re
from pathlib import Path


SDK_ROOT = Path(__file__).resolve().parents[1]
SEMVER_PATTERN = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def require_match(pattern: str, text: str, label: str, flags: int = 0) -> str:
    match = re.search(pattern, text, flags)
    if not match:
        raise SystemExit(f"Could not read {label} version.")
    return match.group(1)


package_json = json.loads((SDK_ROOT / "typescript" / "package.json").read_text())
package_lock = json.loads((SDK_ROOT / "typescript" / "package-lock.json").read_text())
typescript_client = (SDK_ROOT / "typescript" / "src" / "client.ts").read_text()
python_client = (SDK_ROOT / "python" / "olovoice" / "_client.py").read_text()
python_project = (SDK_ROOT / "python" / "pyproject.toml").read_text()

expected = package_json["version"]
versions = {
    "TypeScript package": expected,
    "TypeScript lockfile": package_lock.get("version"),
    "TypeScript lockfile root package": package_lock.get("packages", {})
    .get("", {})
    .get("version"),
    "TypeScript User-Agent": require_match(
        r"const VERSION\s*=\s*['\"]([^'\"]+)['\"]",
        typescript_client,
        "TypeScript User-Agent",
    ),
    "Python package/User-Agent": require_match(
        r"^__version__\s*=\s*['\"]([^'\"]+)['\"]",
        python_client,
        "Python package/User-Agent",
        re.MULTILINE,
    ),
}

for label, version in versions.items():
    if not isinstance(version, str) or not SEMVER_PATTERN.fullmatch(version):
        raise SystemExit(f"{label} has an invalid SemVer version: {version!r}")
    if version != expected:
        raise SystemExit(f"Version drift: {label} is {version}; expected {expected}.")

if not re.search(r'^dynamic\s*=\s*\[\s*["\']version["\']\s*\]', python_project, re.MULTILINE):
    raise SystemExit("Python pyproject.toml must derive its version dynamically.")
if not re.search(
    r'^path\s*=\s*["\']olovoice/_client\.py["\']\s*$',
    python_project,
    re.MULTILINE,
):
    raise SystemExit("Python Hatch version path must be olovoice/_client.py.")

canonical_license = (SDK_ROOT / "LICENSE").read_bytes()
for license_path in (
    SDK_ROOT / "typescript" / "LICENSE",
    SDK_ROOT / "python" / "LICENSE",
):
    if license_path.read_bytes() != canonical_license:
        raise SystemExit(f"License drift: {license_path} differs from sdk/LICENSE.")

print(f"Cross-language version and license guard passed: {expected}")
