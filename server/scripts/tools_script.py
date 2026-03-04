from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.plugins.tools.scripts.runtime_sync import get_tools_runtime_sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync runtime tools to AppData runtime folder")
    parser.add_argument("--force", action="store_true", help="Force resync even when versions match")
    parser.add_argument(
        "--prefer-cdn",
        action="store_true",
        help="Prefer CDN sync when TOOLS_CDN_ENABLED is true (falls back to seed copy).",
    )
    args = parser.parse_args()

    sync = get_tools_runtime_sync()
    try:
        result = sync.sync(force=args.force, prefer_cdn=args.prefer_cdn)
        logger.info(
            "sync=%s reason=%s runtime_version=%s seed_version=%s source=%s healthy=%s runtime_root=%s",
            result.synced,
            result.reason,
            result.runtime_version,
            result.seed_version,
            result.source_used,
            result.healthy,
            result.runtime_root,
        )
        return 0
    except Exception as exc:
        logger.exception("Runtime tools sync failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

