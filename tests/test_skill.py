import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "branching-deliberation"
NATIVE_SKILLS = {
    "branchforge",
    "branchforge-orchestrator",
    "branchforge-research",
    "branchforge-ideation",
    "branchforge-software",
    "branchforge-evaluate",
    "branchforge-report",
}


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
        for name in NATIVE_SKILLS | {"branching-deliberation"}:
            canonical = (ROOT / "skills" / name).resolve()
            for host in (".agents", ".claude"):
                path = ROOT / host / "skills" / name
                self.assertTrue(path.is_symlink(), path)
                self.assertEqual(path.resolve(), canonical)

    def test_all_native_skills_have_valid_minimal_frontmatter(self):
        for name in NATIVE_SKILLS:
            content = (ROOT / "skills" / name / "SKILL.md").read_text()
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            self.assertIsNotNone(match, name)
            frontmatter = match.group(1)
            self.assertIn(f"name: {name}", frontmatter)
            self.assertIn("description:", frontmatter)

    def test_plugin_skill_bundle_points_to_canonical_suite(self):
        path = ROOT / "plugins" / "branchforge" / "skills"
        self.assertTrue(path.is_symlink())
        self.assertEqual(path.resolve(), (ROOT / "skills").resolve())

    def test_plugin_and_marketplace_manifests_are_well_formed(self):
        codex = json.loads(
            (ROOT / "plugins" / "branchforge" / ".codex-plugin" / "plugin.json").read_text()
        )
        self.assertEqual(codex["name"], "branchforge")
        self.assertIn("mcpServers", codex)
        marketplace = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text())
        self.assertTrue(any(plugin["name"] == "branchforge" for plugin in marketplace["plugins"]))
        claude = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(claude["name"], "branchforge")
        for path in (ROOT / ".mcp.json", ROOT / "plugins" / "branchforge" / ".mcp.json"):
            config = json.loads(path.read_text())
            self.assertIn("branchforge", config["mcpServers"])

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
