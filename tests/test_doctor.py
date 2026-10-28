import json
import sys
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
                        "command": sys.executable,
                        "args": ["mcp"],
                    }
                }
            }))

            result = run_doctor("claude-desktop", home=home, platform="darwin")
            self.assertTrue(result["ok"])
            statuses = {check["name"]: check["status"] for check in result["checks"]}
            self.assertEqual(statuses["claude_desktop_config"], "ok")

    def write_config(self, home, content):
        config = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps(content))

    def desktop_check(self, home):
        result = run_doctor("claude-desktop", home=home, platform="darwin")
        return next(check for check in result["checks"] if check["name"] == "claude_desktop_config")

    def test_claude_desktop_config_that_is_not_an_object_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write_config(Path(directory), [])
            check = self.desktop_check(Path(directory))
            self.assertEqual(check["status"], "error")
            self.assertIn("JSON object", check["detail"])

    def test_claude_desktop_command_that_does_not_exist_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = str(Path(directory) / "gone" / "branchforge")
            self.write_config(Path(directory), {"mcpServers": {"branchforge": {"command": missing, "args": ["mcp"]}}})
            check = self.desktop_check(Path(directory))
            self.assertEqual(check["status"], "error")
            self.assertIn(missing, check["detail"])

    def test_claude_desktop_config_path_follows_the_platform(self):
        with tempfile.TemporaryDirectory() as directory:
            windows = run_doctor("claude-desktop", home=directory, platform="win32")
            check = next(item for item in windows["checks"] if item["name"] == "claude_desktop_config")
            self.assertIn("AppData", check["detail"])
            linux = run_doctor("claude-desktop", home=directory, platform="linux")
            check = next(item for item in linux["checks"] if item["name"] == "claude_desktop_config")
            self.assertIn("macOS and Windows", check["detail"])

    def test_claude_desktop_missing_config_is_actionable(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_doctor("claude-desktop", home=directory, platform="darwin")
            self.assertFalse(result["ok"])
            config_check = next(check for check in result["checks"] if check["name"] == "claude_desktop_config")
            self.assertEqual(config_check["status"], "error")
            self.assertIn("install-agent.sh", config_check["action"])


if __name__ == "__main__":
    unittest.main()
