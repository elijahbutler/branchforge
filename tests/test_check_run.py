import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from branchforge.native import BranchForgeTools


PASSING = [sys.executable, "-c", "print('3 passed')"]
FAILING = [sys.executable, "-c", "import sys; print('1 failed'); sys.exit(3)"]
FLAG = "BRANCHFORGE_CHECKS_FILE"


class CheckRunCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.tools = BranchForgeTools(self.root)
        self.run_id = self.tools.run_create("Goal")["run_id"]
        # The user's checks file lives outside the project the agent works in.
        self.user_config = tempfile.TemporaryDirectory()
        self.addCleanup(self.user_config.cleanup)
        self.checks_file = Path(self.user_config.name) / "checks.json"
        self.allow(PASSING)
        patcher = mock.patch.dict(os.environ, {FLAG: str(self.checks_file)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def allow(self, command, **extra):
        self.checks_file.write_text(json.dumps({"checks": {"isolation": {"command": command, **extra}}}))

    def stage(self, **check):
        return self.tools.stage_create(
            self.run_id, "stage", "Objective", mode="software", invariants=["Tenant isolation"],
            checks=[{"name": "isolation", "invariant": "Tenant isolation", **check}],
        )

    def explored(self, title="Candidate"):
        branch = self.tools.branch_add(self.run_id, "stage", title, "Claim", "Difference")
        self.tools.branch_record_result(self.run_id, branch["branch_id"], "Proposal")
        return branch["branch_id"]


class CommandSourceTests(CheckRunCase):
    def test_stage_cannot_supply_its_own_command(self):
        with self.assertRaisesRegex(ValueError, "checks file"):
            self.stage(command="rm -rf ~")

    def test_stage_can_only_reference_checks_the_user_allowed(self):
        with self.assertRaisesRegex(ValueError, "Allowed checks: isolation"):
            self.tools.stage_create(
                self.run_id, "stage", "Objective", invariants=["Tenant isolation"],
                checks=[{"name": "deploy", "invariant": "Tenant isolation"}],
            )

    def test_declaring_checks_is_refused_without_a_checks_file(self):
        with mock.patch.dict(os.environ):
            del os.environ[FLAG]
            with self.assertRaisesRegex(ValueError, FLAG):
                self.stage()

    def test_checks_file_inside_the_project_is_refused(self):
        inside = self.root / "checks.json"
        inside.write_text(self.checks_file.read_text())
        with mock.patch.dict(os.environ, {FLAG: str(inside)}):
            with self.assertRaisesRegex(ValueError, "outside the project"):
                self.stage()

    def test_command_is_read_from_the_checks_file_at_run_time(self):
        self.stage()
        branch_id = self.explored()
        self.allow(FAILING)
        self.assertEqual(self.tools.check_run(self.run_id, branch_id, "isolation")["exit_code"], 3)

    def test_check_removed_from_the_checks_file_no_longer_runs(self):
        self.stage()
        branch_id = self.explored()
        self.checks_file.write_text(json.dumps({"checks": {}}))
        with self.assertRaisesRegex(ValueError, "no longer in the checks file"):
            self.tools.check_run(self.run_id, branch_id, "isolation")

    def test_command_runs_without_a_shell(self):
        marker = self.root / "injected"
        self.allow([sys.executable, "-c", "print('ok')", f"; touch {marker}"])
        self.stage()
        self.tools.check_run(self.run_id, self.explored(), "isolation")
        self.assertFalse(marker.exists())

    def test_string_command_is_split_into_arguments_not_passed_to_a_shell(self):
        marker = self.root / "injected"
        self.allow(f"{shlex.quote(sys.executable)} -c \"print('ok')\" ; touch {marker}")
        self.stage()
        check = self.tools.check_run(self.run_id, self.explored(), "isolation")
        self.assertTrue(check["passed"])
        self.assertFalse(marker.exists())


class ExecutedCheckTests(CheckRunCase):
    def test_passing_command_is_recorded_with_exit_code_and_log(self):
        self.stage()
        branch_id = self.explored()
        check = self.tools.check_run(self.run_id, branch_id, "isolation")
        self.assertTrue(check["passed"])
        self.assertTrue(check["executed"])
        self.assertEqual(check["exit_code"], 0)
        self.assertIn("3 passed", check["details"])
        artifacts = json.loads(
            (self.root / ".branchforge" / "runs" / self.run_id / "branches" / branch_id / "ARTIFACTS.json").read_text()
        )
        self.assertIn("3 passed", Path(artifacts[0]["object_path"]).read_text())
        self.assertEqual(self.tools.branch_verify(self.run_id, branch_id, verified=True)["status"], "verified")

    def test_failing_command_blocks_verification(self):
        self.allow(FAILING)
        self.stage()
        branch_id = self.explored()
        check = self.tools.check_run(self.run_id, branch_id, "isolation")
        self.assertFalse(check["passed"])
        self.assertEqual(check["exit_code"], 3)
        with self.assertRaisesRegex(ValueError, "failed invariant checks"):
            self.tools.branch_verify(self.run_id, branch_id, verified=True)

    def test_a_reported_result_cannot_stand_in_for_a_declared_command(self):
        self.allow(FAILING)
        self.stage()
        branch_id = self.explored()
        with self.assertRaisesRegex(ValueError, "check_run"):
            self.tools.check_record(self.run_id, branch_id, "isolation", True, invariant="Tenant isolation")

    def test_unknown_check_names_the_declared_ones(self):
        self.stage()
        branch_id = self.explored()
        with self.assertRaisesRegex(ValueError, "Declared checks: isolation"):
            self.tools.check_run(self.run_id, branch_id, "isolaton")

    def test_command_that_outlives_the_timeout_is_recorded_as_failed(self):
        self.allow([sys.executable, "-c", "import time; time.sleep(30)"])
        self.stage()
        branch_id = self.explored()
        check = self.tools.check_run(self.run_id, branch_id, "isolation", timeout_seconds=0.5)
        self.assertFalse(check["passed"])
        self.assertIn("timed out", check["details"])

    def test_command_runs_in_the_given_directory_inside_the_project(self):
        self.allow([sys.executable, "-c", "import os; print(os.path.basename(os.getcwd()))"])
        self.stage()
        branch_id = self.explored()
        (self.root / "candidate").mkdir()
        check = self.tools.check_run(self.run_id, branch_id, "isolation", workdir="candidate")
        self.assertIn("candidate", check["details"])

    def test_directory_outside_the_project_is_refused(self):
        self.stage()
        branch_id = self.explored()
        with tempfile.TemporaryDirectory() as outside:
            with self.assertRaisesRegex(ValueError, "git worktree of the project"):
                self.tools.check_run(self.run_id, branch_id, "isolation", workdir=outside)

    def test_git_worktree_of_the_project_is_accepted(self):
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(self.root)]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
        with tempfile.TemporaryDirectory() as parent:
            worktree = Path(parent) / "candidate"
            subprocess.run([*git, "worktree", "add", "-q", str(worktree)], check=True, capture_output=True)
            self.stage()
            branch_id = self.explored()
            check = self.tools.check_run(self.run_id, branch_id, "isolation", workdir=str(worktree))
            self.assertTrue(check["passed"])

    def test_declared_check_must_name_a_stage_invariant(self):
        with self.assertRaisesRegex(ValueError, "Tenant isolation"):
            self.stage(invariant="Tenant isolaton")


if __name__ == "__main__":
    unittest.main()
