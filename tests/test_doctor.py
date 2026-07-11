import json
import tempfile
import unittest
from pathlib import Path

from branchforge.doctor import run_doctor


class DoctorTests(unittest.TestCase):
    def test_local_doctor_reports_no_errors(self):
        result = run_doctor("local")
        self.assertEqual(result["host"], "local")
        self.assertTrue(result["ok"])
        statuses = {check["name"]: check["status"] for check in result["checks"]}
        self.assertEqual(statuses["python_version"], "ok")
        self.assertEqual(statuses["branchforge_import"], "ok")
        self.assertIn(statuses["mcp_extra"], {"ok", "warn"})

    def test_doctor_rejects_unknown_host(self):
        with self.assertRaisesRegex(ValueError, "host must be one of"):
            run_doctor("unknown")

    def test_claude_desktop_config_is_checked_in_fake_home(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({
                "mcpServers": {
                    "branchforge": {
                        "command": "/tmp/branchforge",
                        "args": ["mcp"],
                    }
                }
            }))

            result = run_doctor("claude-desktop", home=home)
            self.assertTrue(result["ok"])
            statuses = {check["name"]: check["status"] for check in result["checks"]}
            self.assertEqual(statuses["claude_desktop_config"], "ok")

    def test_claude_desktop_missing_config_is_actionable(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_doctor("claude-desktop", home=directory)
            self.assertFalse(result["ok"])
            config_check = next(check for check in result["checks"] if check["name"] == "claude_desktop_config")
            self.assertEqual(config_check["status"], "error")
            self.assertIn("install-agent.sh", config_check["action"])


if __name__ == "__main__":
    unittest.main()
