from __future__ import annotations

"""Generate slim tool_index.json and compatibility manifest.json from the registry.

Edit the exclude sets below when a tool should stay in tool_registry.json but
should not be surfaced in the lightweight PQH index or legacy manifest.

Current default:
- web_search
- web_scrape

Those tools still exist in the canonical registry and can still be loaded by the
runtime from the registry. They are simply excluded from the generated helper files.
"""

import argparse
import logging
import sys
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parent.parent
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


# These are the user-facing flags you can edit when a tool should remain in the
# registry but be hidden from generated helper files.
DEFAULT_TOOL_INDEX_EXCLUDE = {
    "web_search",
    "web_scrape",
}

DEFAULT_MANIFEST_EXCLUDE = {
    "web_search",
    "web_scrape",
}


def get_default_generated_file_excludes() -> dict[str, set[str]]:
    return {
        "tool_index": set(DEFAULT_TOOL_INDEX_EXCLUDE),
        "manifest": set(DEFAULT_MANIFEST_EXCLUDE),
    }


def main() -> int:
    from app.plugins.tools.registry_compiler import sync_generated_tool_files

    parser = argparse.ArgumentParser(
        description="Sync tool_index.json and manifest.json from tool_registry.json",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate generated files without writing changes",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger(__name__)

    excludes = get_default_generated_file_excludes()

    try:
        result = sync_generated_tool_files(
            write=not args.check,
            exclude_from_index=excludes["tool_index"],
            exclude_from_manifest=excludes["manifest"],
        )
        logger.info("registry=%s", result["registry_path"])
        logger.info("tool_index=%s count=%s", result["index_path"], result["index_tool_count"])
        logger.info("manifest=%s count=%s", result["manifest_path"], result["manifest_tool_count"])
        logger.info("excluded_from_index=%s", ", ".join(result["excluded_from_index"]) or "none")
        logger.info("excluded_from_manifest=%s", ", ".join(result["excluded_from_manifest"]) or "none")
        logger.info("changed_index=%s changed_manifest=%s", result["changed_index"], result["changed_manifest"])
        return 0
    except Exception as exc:
        logger.exception("Registry sync failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
