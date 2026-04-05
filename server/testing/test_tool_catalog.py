import unittest

try:
    from app.plugins.tools.catalog_service import get_tool_catalog_service
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - import gate
    get_tool_catalog_service = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc


@unittest.skipIf(_IMPORT_ERROR is not None, f"Tool catalog imports unavailable: {_IMPORT_ERROR}")
class ToolCatalogTests(unittest.TestCase):
    def test_summary_counts_and_includes_generated_tools(self):
        summary = get_tool_catalog_service().summary()
        self.assertEqual(summary["total_tools"], 67)
        self.assertIn("artifacts", summary["categories"])
        tool_names = {tool["name"] for tool in summary["tools"]}
        self.assertIn("tool_catalog", tool_names)
        self.assertIn("shell_agent", tool_names)

    def test_params_for_app_open_include_target(self):
        params = get_tool_catalog_service().params("app_open", include_examples=True)
        self.assertIsNotNone(params)
        assert params is not None
        self.assertIn("target", params["params_schema"])
        self.assertIn("destination", params["params_schema"])
        self.assertIn("web_fallback_policy", params["params_schema"])
        self.assertTrue(params["params_schema"]["target"]["required"])
        self.assertTrue(params["examples"])


if __name__ == "__main__":
    unittest.main()
