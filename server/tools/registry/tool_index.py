from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List


@lru_cache(maxsize=1)
def get_tools_index() -> List[Dict[str, Any]]:
    path = Path(__file__).resolve().parent / "tool_index.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("tools", [])
