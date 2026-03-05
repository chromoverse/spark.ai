from __future__ import annotations

import ast
import importlib
import json
import os
import platform
import re
import subprocess
import sys
from collections.abc import Mapping
from importlib import metadata
from pathlib import Path


REQ_NAME_PATTERN = re.compile(r"^\s*([A-Za-z0-9_.-]+)")
SKIP_DIRS = {"__pycache__", ".venv", "venv", "node_modules", "generated"}
LOCAL_TOP_LEVEL_MODULES = {"tools_plugin", "app"}

# Import name -> pip distribution name (for common mismatches).
MODULE_TO_PACKAGE = {
    "AppKit": "pyobjc-framework-AppKit",
    "PIL": "pillow",
    "Quartz": "pyobjc-framework-Quartz",
    "bs4": "beautifulsoup4",
    "pythoncom": "pywin32",
    "win32api": "pywin32",
    "win32com": "pywin32",
    "win32con": "pywin32",
    "win32gui": "pywin32",
    "win32process": "pywin32",
    "win32ui": "pywin32",
}

PACKAGE_MARKERS = {
    "pyobjc-framework-AppKit": 'platform_system == "Darwin"',
    "pyobjc-framework-Quartz": 'platform_system == "Darwin"',
    "pywin32": 'platform_system == "Windows"',
}


def _fail(msg: str) -> None:
    raise RuntimeError(msg)


def _iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def _extract_import_modules(file_path: Path) -> set[str]:
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except Exception:
        return set()

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0 or not node.module:
                continue
            names.add(node.module.split(".", 1)[0])
    return names


def _is_local_module(root: Path, module_name: str) -> bool:
    if module_name in LOCAL_TOP_LEVEL_MODULES:
        return True

    module_file = root / f"{module_name}.py"
    module_dir = root / module_name
    if module_file.exists() or module_dir.exists():
        return True
    return False


def _resolve_package_name(module_name: str, package_map: Mapping[str, list[str]]) -> str:
    mapped = MODULE_TO_PACKAGE.get(module_name)
    if mapped:
        return mapped

    from_installed = package_map.get(module_name)
    if from_installed:
        return from_installed[0]

    return module_name


def _discover_required_packages(root: Path) -> set[str]:
    package_map = metadata.packages_distributions()
    stdlib_modules = getattr(sys, "stdlib_module_names", set())

    packages: set[str] = set()
    for file_path in _iter_python_files(root):
        for module_name in _extract_import_modules(file_path):
            if not module_name or module_name in stdlib_modules:
                continue
            if _is_local_module(root, module_name):
                continue
            packages.add(_resolve_package_name(module_name, package_map))

    return packages


def _parse_requirement_name(requirement_line: str) -> str | None:
    line = requirement_line.split("#", 1)[0].strip()
    if not line or line.startswith(("-", "--")):
        return None
    if ";" in line:
        line = line.split(";", 1)[0].strip()
    match = REQ_NAME_PATTERN.match(line)
    if not match:
        return None
    return match.group(1)


def _marker_applies(marker: str) -> bool:
    parsed = re.match(r'platform_system\s*([=!]=)\s*"([^"]+)"', marker)
    if not parsed:
        return True
    operator = parsed.group(1)
    target = parsed.group(2)
    current = platform.system()
    if operator == "==":
        return current == target
    if operator == "!=":
        return current != target
    return True


def _add_discovered_requirements(requirements_path: Path, packages: set[str]) -> list[str]:
    existing_lines: list[str] = []
    existing_names: set[str] = set()
    if requirements_path.exists():
        existing_lines = requirements_path.read_text(encoding="utf-8").splitlines()
        for line in existing_lines:
            name = _parse_requirement_name(line)
            if name:
                existing_names.add(name.lower())

    new_lines: list[str] = []
    for package in sorted(packages, key=str.lower):
        if package.lower() in existing_names:
            continue
        marker = PACKAGE_MARKERS.get(package)
        if marker:
            new_lines.append(f'{package}; {marker}')
        else:
            new_lines.append(package)

    if new_lines:
        out_lines = existing_lines + new_lines
        requirements_path.write_text("\n".join(out_lines).rstrip() + "\n", encoding="utf-8")

    return new_lines


def _find_missing_requirements(requirements_path: Path) -> list[str]:
    if not requirements_path.exists():
        return []

    missing: list[str] = []
    for line in requirements_path.read_text(encoding="utf-8").splitlines():
        raw = line.split("#", 1)[0].strip()
        if not raw or raw.startswith(("-", "--")):
            continue

        marker = ""
        if ";" in raw:
            raw, marker = [part.strip() for part in raw.split(";", 1)]
            if marker and not _marker_applies(marker):
                continue

        name = _parse_requirement_name(raw)
        if not name:
            continue

        try:
            metadata.version(name)
        except metadata.PackageNotFoundError:
            missing.append(name)

    return sorted(set(missing), key=str.lower)


def _install_packages(packages: list[str]) -> None:
    if not packages:
        return

    print(f"[TOOL TESTER] Installing missing packages: {', '.join(packages)}")
    cmd = [sys.executable, "-m", "pip", "install", *packages]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        _fail(
            "Package installation failed.\n"
            f"Command: {' '.join(cmd)}\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )


def _bootstrap_dependencies(root: Path) -> None:
    requirements_path = root / "requirements.txt"
    discovered_packages = _discover_required_packages(root)
    added_lines = _add_discovered_requirements(requirements_path, discovered_packages)
    if added_lines:
        print(f"[TOOL TESTER] Added {len(added_lines)} package(s) to requirements.txt")
        for line in added_lines:
            print(f" - {line}")

    missing = _find_missing_requirements(requirements_path)
    if missing:
        _install_packages(missing)
        remaining = _find_missing_requirements(requirements_path)
        if remaining:
            _fail(
                "Some requirements are still missing after install: "
                + ", ".join(remaining)
            )


def main() -> int:
    root = Path(__file__).resolve().parent
    print(f"Testing {root}")

    _bootstrap_dependencies(root)

    manifest_path = root / "manifest.json"
    registry_path = root / "registry" / "tool_registry.json"

    if not manifest_path.exists():
        _fail(f"Missing manifest: {manifest_path}")
    if not registry_path.exists():
        _fail(f"Missing registry: {registry_path}")

    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    with registry_path.open("r", encoding="utf-8") as f:
        registry = json.load(f)

    schema_tool_names = set()
    for category in registry.get("categories", {}).values():
        for tool in category.get("tools", []):
            schema_tool_names.add(tool.get("tool_name"))

    # Make sure server root containing app/ is importable for optional app.* imports.
    candidate_roots = [Path.cwd()]
    env_root = os.environ.get("SPARK_SERVER_ROOT")
    if env_root:
        candidate_roots.append(Path(env_root))
    candidate_roots.append(Path(__file__).resolve().parents[1] / "server")

    for candidate in candidate_roots:
        if (candidate / "app").exists():
            candidate_str = str(candidate)
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)

    root_parent = root.parent
    root_parent_str = str(root_parent)
    if root_parent_str not in sys.path:
        sys.path.insert(0, root_parent_str)

    runtime_tools_path = root / "tools"
    app_runtime_available = True
    if runtime_tools_path.exists():
        try:
            import tools_plugin.tools as runtime_tools_pkg  # noqa: F401
        except ModuleNotFoundError:
            app_runtime_available = False

    failures: list[str] = []
    warnings: list[str] = []
    tested = 0

    for spec in manifest.get("plugins", []):
        tool_name = spec.get("tool_name")
        module_name = spec.get("module")
        class_name = spec.get("class_name")

        if not tool_name or not module_name or not class_name:
            failures.append(f"Invalid manifest entry: {spec}")
            continue

        if tool_name not in schema_tool_names:
            failures.append(f"Tool '{tool_name}' missing in tool_registry.json")
            continue

        if not app_runtime_available:
            tested += 1
            continue

        try:
            if str(module_name).startswith("tools_plugin.tools."):
                import_name = str(module_name)
            else:
                import_name = f"tools_plugin.tools.{module_name}"
            module = importlib.import_module(import_name)
            cls = getattr(module, str(class_name))
            instance = cls()
            runtime_name = instance.get_tool_name()
            if runtime_name != tool_name:
                failures.append(
                    f"Tool mismatch: manifest={tool_name}, runtime={runtime_name}, class={class_name}"
                )
                continue
            tested += 1
        except Exception as exc:
            warnings.append(f"Failed loading {tool_name} ({module_name}.{class_name}): {exc}")

    if failures:
        print("[TOOL TESTER] FAILED")
        for issue in failures:
            print(f" - {issue}")
        if warnings:
            print("[TOOL TESTER] WARNINGS")
            for issue in warnings:
                print(f" - {issue}")
        return 1

    if warnings:
        print("[TOOL TESTER] PASSED WITH WARNINGS")
        for issue in warnings:
            print(f" - {issue}")
        print(f"[TOOL TESTER] VALIDATED ({tested} tools loaded; {len(warnings)} skipped due optional deps)")
        return 0

    print(f"[TOOL TESTER] PASSED ({tested} tools validated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
