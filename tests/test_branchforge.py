import asyncio
import tempfile
import unittest
from pathlib import Path

from branchforge.models import BranchResult, Hypothesis, RunConfig, StageSpec
from branchforge.orchestrator import BranchForge
from branchforge.policy import BranchPolicy
from branchforge.providers import MockProvider
from branchforge.store import EventStore


class PolicyTests(unittest.TestCase):
    def test_policy_deduplicates_and_prunes_low_novelty(self):
        policy = BranchPolicy(RunConfig(max_branches=2, novelty_threshold=0.6))
        items = [
            Hypothesis("Alpha", "a", "a", [], [], 0.9),
            Hypothesis(" alpha ", "b", "b", [], [], 0.8),
            Hypothesis("Beta", "c", "c", [], [], 0.5),
            Hypothesis("Gamma", "d", "d", [], [], 0.7),
        ]
        self.assertEqual([item.title for item in policy.admit(items)], ["Alpha", "Gamma"])

    def test_weighted_score_is_sum(self):
        result = BranchResult(Hypothesis("A", "a", "a", [], [], 1), "", [], [], 1, scores={"a": 0.4, "b": 0.3})
        self.assertAlmostEqual(result.score, 0.7)


class StoreTests(unittest.TestCase):
    def test_event_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "events.db")
            store.append("run_1", "TEST", {"answer": 42})
            events = store.events("run_1")
            self.assertEqual(events[0]["payload"], {"answer": 42})
            store.close()


class OrchestratorTests(unittest.TestCase):
    def test_mock_run_is_replayable_and_multiround(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "events.db")
            forge = BranchForge(MockProvider(), store, RunConfig(max_branches=3, survivor_width=2, max_rounds=2))
            outcomes = asyncio.run(forge.run("Design a safe cache", [StageSpec("architecture", "Choose an approach")]))
            self.assertEqual(len(outcomes), 1)
            self.assertTrue(outcomes[0].winner.verified)
            events = store.events(outcomes[0].run_id)
            counts = [event for event in events if event["event_type"] == "ROUND_COMPLETED"]
            self.assertEqual(len(counts), 2)
            self.assertEqual(events[-1]["event_type"], "RUN_COMPLETED")
            branches = forge.repository.branches(outcomes[0].run_id)
            self.assertEqual(len(branches), 6)
            self.assertEqual(sum(branch["status"] == "committed" for branch in branches), 1)
            second_round = [branch for branch in branches if branch["round"] == 1]
            self.assertTrue(all(branch["parent_id"] for branch in second_round))
            run_dir = forge.repository.workspace / "runs" / outcomes[0].run_id
            self.assertTrue((run_dir / "TREE.json").is_file())
            self.assertEqual(len(list((run_dir / "branches").iterdir())), 6)
            self.assertEqual(forge.repository.get_run(outcomes[0].run_id)["status"], "completed")
            self.assertEqual(forge.repository.stages(outcomes[0].run_id)[0]["status"], "committed")
            self.assertTrue((run_dir / "RUN.json").is_file())
            store.close()

    def test_unverified_run_fails_but_preserves_dossiers(self):
        class RejectingVerifier(MockProvider):
            async def complete(self, system, prompt):
                if "VERIFY_BRANCH" in prompt:
                    return '{"verified": false, "scores": {}, "notes": ["No objective evidence"]}'
                return await super().complete(system, prompt)

        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "events.db")
            forge = BranchForge(RejectingVerifier(), store, RunConfig(max_branches=3, survivor_width=2, max_rounds=1))
            with self.assertRaisesRegex(RuntimeError, "no verified candidate"):
                asyncio.run(forge.run("Test an uncertain claim", [StageSpec("research", "Verify the claim")]))
            run_id = store.run_ids()[0]
            run_dir = forge.repository.workspace / "runs" / run_id
            self.assertTrue((run_dir / "TREE.json").is_file())
            self.assertEqual(len(list((run_dir / "branches").iterdir())), 3)
            self.assertEqual(store.events(run_id)[-1]["event_type"], "RUN_FAILED")
            self.assertEqual(forge.repository.get_run(run_id)["status"], "failed")
            self.assertEqual(forge.repository.stages(run_id)[0]["status"], "failed")
            store.close()


if __name__ == "__main__":
    unittest.main()
