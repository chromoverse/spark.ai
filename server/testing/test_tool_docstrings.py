import unittest
from pathlib import Path


class ToolDocstringConventionTests(unittest.TestCase):
    def test_tool_modules_do_not_use_params_heading(self):
        offenders = []

        for path in Path("tools/tools").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "Params:" in text:
                offenders.append(str(path).replace("\\", "/"))

        self.assertEqual(
            offenders,
            [],
            f"Use 'Inputs:'/'Outputs:' headings in tool docstrings, not 'Params:': {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
