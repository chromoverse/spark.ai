from __future__ import annotations

import re
import platform
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import List


_REQ_NAME_PATTERN = re.compile(r"^\s*([A-Za-z0-9_.-]+)")


@dataclass
class RequirementCheckResult:
    requirements_path: str
    checked: List[str]
    missing: List[str]


def check_requirements(requirements_file: Path) -> RequirementCheckResult:
    checked: List[str] = []
    missing: List[str] = []

    if not requirements_file.exists():
        return RequirementCheckResult(
            requirements_path=str(requirements_file),
            checked=[],
            missing=[],
        )

    for line in requirements_file.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "--")):
            continue
        marker = ""
        if ";" in line:
            line, marker = [part.strip() for part in line.split(";", 1)]
            if marker and not _marker_applies(marker):
                continue
        match = _REQ_NAME_PATTERN.match(line)
        if not match:
            continue

        package = match.group(1)
        checked.append(package)
        try:
            metadata.version(package)
        except metadata.PackageNotFoundError:
            missing.append(package)

    return RequirementCheckResult(
        requirements_path=str(requirements_file),
        checked=checked,
        missing=missing,
    )


def _marker_applies(marker: str) -> bool:
    m = re.match(r'platform_system\s*([=!]=)\s*"([^"]+)"', marker)
    if not m:
        return True
    op = m.group(1)
    target = m.group(2)
    current = platform.system()
    if op == "==":
        return current == target
    if op == "!=":
        return current != target
    return True
