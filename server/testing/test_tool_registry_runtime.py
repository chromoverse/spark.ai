import json
import unittest
from pathlib import Path

try:
    from app.plugins.tools.registry_compiler import (
        build_tool_index_document,
        load_registry_document,
        sync_generated_tool_files,
        validate_registry_document,
    )
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - import gate
    build_tool_index_document = None  # type: ignore[assignment]
    load_registry_document = None  # type: ignore[assignment]
    sync_generated_tool_files = None  # type: ignore[assignment]
    validate_registry_document = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc


@unittest.skipIf(_IMPORT_ERROR is not None, f"Registry runtime imports unavailable: {_IMPORT_ERROR}")
class ToolRegistryRuntimeTests(unittest.TestCase):
    def test_registry_validates_and_generated_index_matches_file(self):
        document = load_registry_document()
        errors = validate_registry_document(document)
        self.assertEqual(errors, [])

        expected_index = build_tool_index_document(document)
        actual_index = json.loads(Path("tools/registry/tool_index.json").read_text(encoding="utf-8"))
        self.assertEqual(expected_index, actual_index)
        self.assertEqual(expected_index["total_tools"], 65)
        tool_catalog_entry = next(tool for tool in actual_index["tools"] if tool["name"] == "tool_catalog")
        self.assertEqual(
            sorted(tool_catalog_entry.keys()),
            ["description", "example_triggers", "name"],
        )
        index_names = {tool["name"] for tool in actual_index["tools"]}
        self.assertNotIn("web_search", index_names)
        self.assertNotIn("web_scrape", index_names)

    def test_generated_files_are_in_sync(self):
        result = sync_generated_tool_files(write=False)
        self.assertEqual(result["tool_count"], 67)
        self.assertEqual(result["index_tool_count"], 65)
        self.assertEqual(result["manifest_tool_count"], 65)
        self.assertFalse(result["changed_index"])
        self.assertFalse(result["changed_manifest"])
        self.assertEqual(result["excluded_from_index"], ["web_scrape", "web_search"])
        self.assertEqual(result["excluded_from_manifest"], ["web_scrape", "web_search"])


if __name__ == "__main__":
    unittest.main()
