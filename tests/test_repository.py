import json
import tempfile
import unittest
from pathlib import Path

from branchforge.models import (
    BranchMode,
    BranchResult,
    BranchStatus,
    Finding,
    Hypothesis,
    RunConfig,
    StageSpec,
)
from branchforge.repository import BranchRepository
from branchforge.store import EventStore


class BranchRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.store = EventStore(root / "branchforge.db")
        self.repository = BranchRepository(self.store, root / "archive")
        self.run_id = "run_test"
        self.repository.create_run(self.run_id, "Test durable branches", RunConfig())
        self.repository.create_stage(
            self.run_id,
            StageSpec("architecture", "Choose architecture", mode=BranchMode.RESEARCH),
        )
        self.repository.create_stage(
            self.run_id,
            StageSpec("implementation", "Implement it", mode=BranchMode.SOFTWARE),
        )

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def hypothesis(self, *, parent_id=None, branch_id="branch_a", round_number=0):
        return Hypothesis(
            "Evidence first",
            "The riskiest assumption should be tested first",
            "Optimizes information gain",
            ["Uncertainty decreases"],
            ["Experiment does not discriminate"],
            0.9,
            id=branch_id,
            parent_id=parent_id,
            round=round_number,
        )

    def test_lifecycle_tree_and_dossier(self):
        hypothesis = self.hypothesis()
        self.repository.create_branch(self.run_id, "architecture", hypothesis, BranchMode.RESEARCH)
        self.repository.transition(self.run_id, hypothesis.id, BranchStatus.ADMITTED)
        self.repository.transition(self.run_id, hypothesis.id, BranchStatus.RUNNING)
        result = BranchResult(hypothesis, "Run a falsification experiment", ["Observed a measurable delta"], ["Small sample"], 0.8)
        self.repository.record_result(self.run_id, result)
        self.repository.transition(self.run_id, hypothesis.id, BranchStatus.EXPLORED)
        result.verified = True
        result.scores = {"correctness": 0.8}
        self.repository.record_verification(self.run_id, result, ["Invariant passed"])
        self.repository.transition(self.run_id, hypothesis.id, BranchStatus.VERIFIED)
        self.repository.record_finding(self.run_id, Finding(hypothesis.id, "The experiment is discriminating"))
        self.repository.transition(self.run_id, hypothesis.id, BranchStatus.COMMITTED)

        child = self.hypothesis(parent_id=hypothesis.id, branch_id="branch_child", round_number=1)
        self.repository.create_branch(self.run_id, "implementation", child, BranchMode.SOFTWARE)
        self.repository.transition(self.run_id, child.id, BranchStatus.PRUNED, reason="Out of budget")

        tree = self.repository.tree(self.run_id)
        self.assertEqual(tree["roots"][0]["branch_id"], hypothesis.id)
        self.assertEqual(tree["roots"][0]["children"][0]["branch_id"], child.id)
        self.assertEqual(tree["roots"][0]["mode"], "research")

        run_dir = self.repository.render_run(self.run_id)
        self.assertTrue((run_dir / "RUN.json").is_file())
        dossier = run_dir / "branches" / hypothesis.id
        self.assertTrue((dossier / "MANIFEST.json").is_file())
        self.assertTrue((dossier / "HYPOTHESIS.md").is_file())
        self.assertTrue((dossier / "OUTCOME.md").is_file())
        self.assertIn("Observed a measurable delta", (dossier / "EVIDENCE.jsonl").read_text())
        manifest = json.loads((dossier / "MANIFEST.json").read_text())
        self.assertEqual(manifest["branch"]["status"], "committed")

    def test_illegal_transition_is_rejected(self):
        hypothesis = self.hypothesis()
        self.repository.create_branch(self.run_id, "architecture", hypothesis, BranchMode.HYBRID)
        with self.assertRaisesRegex(ValueError, "Illegal branch transition"):
            self.repository.transition(self.run_id, hypothesis.id, BranchStatus.COMMITTED)

    def test_orphaned_branch_is_rejected(self):
        hypothesis = self.hypothesis(parent_id="branch_missing", branch_id="branch_orphan")
        with self.assertRaisesRegex(ValueError, "Parent branch does not exist"):
            self.repository.create_branch(self.run_id, "architecture", hypothesis, BranchMode.HYBRID)

    def test_transition_rejects_wrong_run_id(self):
        hypothesis = self.hypothesis()
        self.repository.create_branch(self.run_id, "architecture", hypothesis, BranchMode.HYBRID)
        with self.assertRaisesRegex(ValueError, "different run"):
            self.repository.transition("run_wrong", hypothesis.id, BranchStatus.ADMITTED)

    def test_artifacts_are_content_addressed_and_deduplicated(self):
        hypothesis = self.hypothesis()
        self.repository.create_branch(self.run_id, "architecture", hypothesis, BranchMode.HYBRID)
        first = self.repository.store_artifact(self.run_id, hypothesis.id, b"same content", role="test-output")
        second = self.repository.store_artifact(self.run_id, hypothesis.id, b"same content", role="supporting-evidence")
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.object_path, second.object_path)
        self.assertEqual(Path(first.object_path).read_bytes(), b"same content")
        records = self.store.query("SELECT * FROM artifacts WHERE branch_id = ?", (hypothesis.id,))
        self.assertEqual(len(records), 2)


if __name__ == "__main__":
    unittest.main()
