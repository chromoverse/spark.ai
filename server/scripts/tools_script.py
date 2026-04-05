from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.plugins.tools.registry_compiler import sync_generated_tool_files
from app.plugins.tools.registry_loader import load_tool_registry, tool_registry
from app.plugins.tools.tool_instance_loader import load_all_tools
from app.path.manager import PathManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect the direct server/tools runtime")
    parser.add_argument("--load", action="store_true", help="Load tool instances after reading the registry")
    parser.add_argument(
        "--sync-generated",
        action="store_true",
        help="Regenerate tool_index.json and manifest.json from tool_registry.json before inspection",
    )
    args = parser.parse_args()

    try:
        path_manager = PathManager()
        if args.sync_generated:
            result = sync_generated_tool_files(write=True)
            logger.info("generated_index_changed=%s", result["changed_index"])
            logger.info("generated_manifest_changed=%s", result["changed_manifest"])
        load_tool_registry(force_reload=True)
        logger.info("tools_root=%s", path_manager.get_tools_dir())
        logger.info("manifest=%s", path_manager.get_tools_manifest_file())
        logger.info("registry=%s", path_manager.get_tools_registry_file())
        logger.info("tool_index=%s", path_manager.get_tools_index_file())
        logger.info("registry_version=%s tool_count=%s", tool_registry.version, len(tool_registry.tools))
        if args.load:
            instances = load_all_tools()
            logger.info("loaded_tool_instances=%s", instances.count())
        return 0
    except Exception as exc:
        logger.exception("Direct tools runtime inspection failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

