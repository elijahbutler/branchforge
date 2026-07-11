import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "branching-deliberation"


class SkillPackageTests(unittest.TestCase):
    def test_portable_skill_metadata(self):
        content = (SKILL / "SKILL.md").read_text()
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        self.assertIsNotNone(match)
        frontmatter = match.group(1)
        self.assertIn("name: branching-deliberation", frontmatter)
        self.assertIn("description:", frontmatter)
        self.assertLess(len(content.splitlines()), 500)

    def test_host_discovery_links_resolve_to_canonical_skill(self):
        canonical = SKILL.resolve()
        for path in (
            ROOT / ".agents" / "skills" / "branching-deliberation",
            ROOT / ".claude" / "skills" / "branching-deliberation",
        ):
            self.assertTrue(path.is_symlink())
            self.assertEqual(path.resolve(), canonical)

    def test_skill_has_trigger_and_non_trigger_evaluations(self):
        data = json.loads((SKILL / "evals" / "evals.json").read_text())
        self.assertEqual(data["skill"], "branching-deliberation")
        self.assertGreaterEqual(len(data["cases"]), 3)
        behaviors = " ".join(
            behavior
            for case in data["cases"]
            for behavior in case["expected_behavior"]
        ).lower()
        self.assertIn("does not create", behaviors)


if __name__ == "__main__":
    unittest.main()
