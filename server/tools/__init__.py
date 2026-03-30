from __future__ import annotations

from pathlib import Path

# Expose both:
# - server/tools/...          -> automation, utils, tool_tester
# - server/tools/tools/...    -> system, web, ai, messaging, etc.
#
# This allows direct imports such as:
#   from tools.system import app
#   from tools.web import WebResearchTool
_package_dir = Path(__file__).resolve().parent
_categories_dir = _package_dir / "tools"

if _categories_dir.exists():
    __path__.append(str(_categories_dir))
