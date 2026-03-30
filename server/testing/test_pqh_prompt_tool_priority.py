import unittest

try:
    from app.prompts.pqh_prompt import build_system_prompt
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment-dependent import gate
    build_system_prompt = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc


@unittest.skipIf(_IMPORT_ERROR is not None, f"PQH prompt imports unavailable: {_IMPORT_ERROR}")
class PQHPromptToolPriorityTests(unittest.TestCase):
    def test_prompt_emphasizes_specific_tool_priority(self):
        prompt = build_system_prompt()

        self.assertIn("Specific beats broad.", prompt)
        self.assertIn("Direct beats indirect.", prompt)
        self.assertIn("Do not choose a generic research/search tool if another available tool already matches the request more closely.", prompt)
        self.assertIn("Use web_research only when the task genuinely needs open-ended live web lookup and no dedicated tool is a clearer fit.", prompt)


if __name__ == "__main__":
    unittest.main()
