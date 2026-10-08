import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from branchforge.models import BranchMode, BranchResult, Hypothesis, RunConfig, StageSpec
from branchforge.native import BranchForgeTools
from branchforge.orchestrator import BranchForge
from branchforge.providers import MockProvider
from branchforge.repository import SCHEMA_VERSION, BranchRepository
from branchforge.store import EventStore


ROOT = Path(__file__).resolve().parents[1]


class LifecycleCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.tools = BranchForgeTools(self.root)

    def run_with_stage(self, **stage):
        run_id = self.tools.run_create("Goal", **stage.pop("config", {}))["run_id"]
        self.tools.stage_create(run_id, "stage", "Objective", **stage)
        return run_id

    def explored(self, run_id, title="Candidate"):
        branch = self.tools.branch_add(run_id, "stage", title, "Claim", "Difference")
        self.tools.branch_record_result(run_id, branch["branch_id"], "Proposal")
        return branch["branch_id"]

    def verified(self, run_id, title="Candidate"):
        branch_id = self.explored(run_id, title)
        self.tools.branch_verify(run_id, branch_id, verified=True)
        return branch_id


class RunFinalityTests(LifecycleCase):
    def test_run_without_stages_cannot_complete(self):
        run_id = self.tools.run_create("Empty")["run_id"]
        with self.assertRaisesRegex(ValueError, "no stages"):
            self.tools.run_finish(run_id)

    def test_completed_run_rejects_further_changes(self):
        run_id = self.run_with_stage()
        winner = self.verified(run_id)
        self.tools.stage_commit(run_id, "stage", winner, "Best evidence", 0.8)
        self.tools.run_finish(run_id)

        with self.assertRaisesRegex(ValueError, "is completed"):
            self.tools.stage_create(run_id, "late", "Objective")
        with self.assertRaisesRegex(ValueError, "is completed"):
            self.tools.evidence_record(run_id, winner, "Late evidence")
        with self.assertRaisesRegex(ValueError, "is completed"):
            self.tools.run_finish(run_id, error="Changed my mind")
        self.assertEqual(self.tools.run_view(run_id)["run"]["status"], "completed")

    def test_completed_run_rejects_a_late_verification_write(self):
        run_id = self.run_with_stage()
        winner = self.verified(run_id)
        self.tools.stage_commit(run_id, "stage", winner, "Best evidence", 0.8)
        self.tools.run_finish(run_id)
        store = EventStore(self.root / ".branchforge" / "state.db")
        self.addCleanup(store.close)
        repository = BranchRepository(store, self.root / ".branchforge")
        late = BranchResult(Hypothesis("t", "c", "d", [], [], 0.5, id=winner), "p", [], [], 0.5, scores={"correctness": 0.0})
        with self.assertRaisesRegex(ValueError, "is completed"):
            repository.record_verification(run_id, late, [])
        self.assertTrue(repository.get_branch(winner)["verified"])

    def test_artifact_is_not_added_to_a_run_that_finished_during_the_copy(self):
        run_id = self.run_with_stage()
        branch_id = self.explored(run_id)
        store = EventStore(self.root / ".branchforge" / "state.db")
        self.addCleanup(store.close)
        repository = BranchRepository(store, self.root / ".branchforge")
        copy = repository.artifacts.store_bytes

        def finish_while_copying(content):
            repository.finish_run(run_id, error="Stopped by another request")
            return copy(content)

        with mock.patch.object(repository.artifacts, "store_bytes", side_effect=finish_while_copying):
            with self.assertRaisesRegex(ValueError, "is failed"):
                repository.store_artifact(run_id, branch_id, b"log")
        self.assertEqual(repository.records("artifacts", branch_id), [])

    def test_failed_run_closes_open_branches_with_the_reason(self):
        run_id = self.run_with_stage()
        waiting = self.tools.branch_add(run_id, "stage", "Waiting", "Claim", "Difference")
        active = self.tools.branch_add(run_id, "stage", "Active", "Claim", "Difference")
        self.tools.branch_start(run_id, active["branch_id"])

        self.tools.run_finish(run_id, error="Budget exhausted")

        statuses = {item["title"]: item for item in self.tools.branch_list(run_id)}
        self.assertEqual(statuses["Waiting"]["status"], "pruned")
        self.assertEqual(statuses["Active"]["status"], "failed")
        self.assertIn("Budget exhausted", statuses["Waiting"]["rejection_reason"])
        self.assertEqual(waiting["status"], "admitted")


class StageCommitTests(LifecycleCase):
    def test_interrupted_commit_leaves_the_stage_retryable(self):
        run_id = self.run_with_stage()
        winner = self.verified(run_id, "Winner")
        loser = self.verified(run_id, "Loser")

        with mock.patch.object(BranchRepository, "record_finding", side_effect=RuntimeError("disk full")):
            with self.assertRaisesRegex(RuntimeError, "disk full"):
                self.tools.stage_commit(run_id, "stage", winner, "Best evidence", 0.8)

        statuses = {item["branch_id"]: item["status"] for item in self.tools.branch_list(run_id)}
        self.assertEqual(statuses, {winner: "verified", loser: "verified"})
        committed = self.tools.stage_commit(run_id, "stage", winner, "Best evidence", 0.8)
        self.assertEqual(committed["status"], "committed")

    def test_committed_stage_cannot_be_committed_again(self):
        run_id = self.run_with_stage()
        winner = self.verified(run_id)
        self.tools.stage_commit(run_id, "stage", winner, "Best evidence", 0.8)
        with self.assertRaisesRegex(ValueError, "already committed"):
            self.tools.stage_commit(run_id, "stage", winner, "Again", 0.8)


class AdmissionBudgetTests(LifecycleCase):
    def test_admission_stops_at_the_branch_budget(self):
        run_id = self.run_with_stage(config={"max_branches": 2})
        self.tools.branch_add(run_id, "stage", "One", "Claim", "Difference")
        self.tools.branch_add(run_id, "stage", "Two", "Claim", "Difference")
        with self.assertRaisesRegex(ValueError, "max_branches=2"):
            self.tools.branch_add(run_id, "stage", "Three", "Claim", "Difference")
        rejected = self.tools.branch_add(run_id, "stage", "Three", "Claim", "Difference", admit=False)
        self.assertEqual(rejected["status"], "pruned")

    def test_admission_rejects_rounds_beyond_the_budget(self):
        run_id = self.run_with_stage(config={"max_rounds": 1})
        with self.assertRaisesRegex(ValueError, "max_rounds=1"):
            self.tools.branch_add(run_id, "stage", "Late", "Claim", "Difference", round_number=1)

    def test_admission_rejects_a_duplicate_title_in_the_same_round(self):
        run_id = self.run_with_stage()
        self.tools.branch_add(run_id, "stage", "Event sourcing", "Claim", "Difference")
        with self.assertRaisesRegex(ValueError, "already admitted"):
            self.tools.branch_add(run_id, "stage", "  event   Sourcing ", "Claim", "Difference")


class ObservedEvidenceTests(LifecycleCase):
    def test_software_stages_default_to_observed_evidence(self):
        run_id = self.tools.run_create("Goal")["run_id"]
        software = self.tools.stage_create(run_id, "build", "Objective", mode="software")
        research = self.tools.stage_create(run_id, "read", "Objective", mode="research")
        self.assertEqual(software["evidence_policy"], "observed")
        self.assertEqual(research["evidence_policy"], "judged")

    def test_failed_invariant_check_blocks_verification(self):
        run_id = self.run_with_stage(invariants=["Tenant isolation"])
        branch_id = self.explored(run_id)
        self.tools.check_record(run_id, branch_id, "isolation test", False, invariant="Tenant isolation")
        with self.assertRaisesRegex(ValueError, "failed invariant checks.*Tenant isolation"):
            self.tools.branch_verify(run_id, branch_id, verified=True)

    def test_a_later_passing_check_supersedes_the_failure(self):
        run_id = self.run_with_stage(invariants=["Tenant isolation"])
        branch_id = self.explored(run_id)
        self.tools.check_record(run_id, branch_id, "isolation test", False, invariant="Tenant isolation")
        self.tools.check_record(run_id, branch_id, "isolation test", True, invariant="Tenant isolation")
        self.assertEqual(self.tools.branch_verify(run_id, branch_id, verified=True)["status"], "verified")

    def test_observed_stage_needs_a_passing_check_for_every_invariant(self):
        run_id = self.run_with_stage(mode="software", invariants=["Idempotent writes", "Tenant isolation"])
        branch_id = self.explored(run_id)
        self.tools.check_record(run_id, branch_id, "pytest", True, invariant="Idempotent writes", command="pytest", exit_code=0)
        with self.assertRaisesRegex(ValueError, "no passing check.*Tenant isolation"):
            self.tools.branch_verify(run_id, branch_id, verified=True)
        self.tools.check_record(run_id, branch_id, "isolation test", True, invariant="Tenant isolation")
        self.assertEqual(self.tools.branch_verify(run_id, branch_id, verified=True)["status"], "verified")

    def test_observed_stage_without_invariants_still_needs_one_passing_check(self):
        run_id = self.run_with_stage(mode="software")
        branch_id = self.explored(run_id)
        with self.assertRaisesRegex(ValueError, "at least one passing check"):
            self.tools.branch_verify(run_id, branch_id, verified=True)

    def test_check_names_the_valid_invariants_when_given_an_unknown_one(self):
        run_id = self.run_with_stage(invariants=["Tenant isolation"])
        branch_id = self.explored(run_id)
        with self.assertRaisesRegex(ValueError, "Tenant isolation"):
            self.tools.check_record(run_id, branch_id, "test", True, invariant="Tenant isolaton")

    def test_run_status_asks_for_a_check_before_verification_when_none_passed(self):
        run_id = self.run_with_stage(mode="software")
        branch_id = self.explored(run_id)
        actions = " ".join(self.tools.run_status(run_id)["next_actions"])
        self.assertIn("check_record", actions)
        self.assertNotIn(f"Verify or prune explored branch {branch_id}", actions)
        self.tools.check_record(run_id, branch_id, "pytest", True)
        actions = " ".join(self.tools.run_status(run_id)["next_actions"])
        self.assertIn(f"Verify or prune explored branch {branch_id}", actions)

    def test_run_status_names_the_checks_still_missing(self):
        run_id = self.run_with_stage(mode="software", invariants=["Tenant isolation"])
        branch_id = self.explored(run_id)
        actions = " ".join(self.tools.run_status(run_id)["next_actions"])
        self.assertIn("check_record", actions)
        self.assertIn("Tenant isolation", actions)
        self.assertIn(branch_id, actions)


class VerificationScoreTests(LifecycleCase):
    def test_scores_are_weighted_by_the_stage_rubric(self):
        run_id = self.run_with_stage(rubric={"correctness": 0.75, "simplicity": 0.25})
        branch_id = self.explored(run_id)
        result = self.tools.branch_verify(run_id, branch_id, verified=True, scores={"correctness": 1.0, "simplicity": 0.4})
        self.assertAlmostEqual(result["score"], 0.85)

    def test_scores_outside_the_rubric_are_rejected(self):
        run_id = self.run_with_stage(rubric={"correctness": 1.0})
        branch_id = self.explored(run_id)
        with self.assertRaisesRegex(ValueError, "correctness"):
            self.tools.branch_verify(run_id, branch_id, verified=True, scores={"vibes": 0.9})
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            self.tools.branch_verify(run_id, branch_id, verified=True, scores={"correctness": 40})


class ProvenanceTests(LifecycleCase):
    def test_evidence_must_reference_existing_records(self):
        run_id = self.run_with_stage()
        branch_id = self.explored(run_id)
        with self.assertRaisesRegex(ValueError, "Unknown claim"):
            self.tools.evidence_record(run_id, branch_id, "Statement", claim_id="claim_missing")
        with self.assertRaisesRegex(ValueError, "Unknown artifact"):
            self.tools.evidence_record(run_id, branch_id, "Statement", artifact_id="artifact_missing")
        with self.assertRaisesRegex(ValueError, "Unknown evidence"):
            self.tools.finding_record(run_id, branch_id, "Statement", evidence_id="evidence_missing")

    def test_claims_are_written_to_the_event_log(self):
        run_id = self.run_with_stage()
        branch_id = self.explored(run_id)
        claim = self.tools.claim_record(run_id, branch_id, "A durable claim")
        store = EventStore(self.root / ".branchforge" / "state.db")
        self.addCleanup(store.close)
        recorded = [event for event in store.events(run_id) if event["event_type"] == "CLAIM_RECORDED"]
        self.assertEqual(recorded[-1]["payload"]["id"], claim["id"])


class ResponseShapeTests(LifecycleCase):
    def test_branch_list_is_concise_unless_detail_is_requested(self):
        run_id = self.run_with_stage()
        self.explored(run_id)
        concise = self.tools.branch_list(run_id)[0]
        self.assertNotIn("proposal", concise)
        self.assertNotIn("predictions", concise)
        self.assertEqual(self.tools.branch_list(run_id, detail=True)[0]["proposal"], "Proposal")

    def test_unknown_run_is_an_error_not_an_empty_list(self):
        with self.assertRaisesRegex(ValueError, "Unknown run"):
            self.tools.branch_list("run_typo")

    def test_invalid_mode_names_the_valid_choices(self):
        run_id = self.tools.run_create("Goal")["run_id"]
        with self.assertRaisesRegex(ValueError, "research, ideation, software, hybrid"):
            self.tools.stage_create(run_id, "stage", "Objective", mode="sofware")


class DossierTests(LifecycleCase):
    def test_decision_record_lists_checks_and_rejected_alternatives(self):
        run_id = self.run_with_stage(invariants=["Tenant isolation"])
        winner = self.explored(run_id, "Winner")
        self.tools.check_record(run_id, winner, "isolation test", True, invariant="Tenant isolation")
        self.tools.branch_verify(run_id, winner, verified=True)
        loser = self.explored(run_id, "Loser")
        self.tools.branch_prune(run_id, loser, "Recovery exceeded the time objective")
        self.tools.stage_commit(run_id, "stage", winner, "Best evidence", 0.8)

        run_dir = self.root / ".branchforge" / "runs" / run_id
        decision = (run_dir / "DECISION.md").read_text()
        self.assertIn("isolation test", decision)
        self.assertIn("Loser", decision)
        self.assertIn("Recovery exceeded the time objective", decision)
        checks = json.loads((run_dir / "branches" / winner / "CHECKS.json").read_text())
        self.assertEqual(checks[0]["invariant"], "Tenant isolation")


class EvidencePolicyDefaultTests(unittest.TestCase):
    def test_stage_spec_derives_the_policy_from_the_mode(self):
        self.assertEqual(StageSpec("s", "o", mode=BranchMode.SOFTWARE).evidence_policy, "observed")
        self.assertEqual(StageSpec("s", "o", mode=BranchMode.RESEARCH).evidence_policy, "judged")
        self.assertEqual(StageSpec("s", "o").evidence_policy, "judged")

    def test_stage_spec_keeps_an_explicit_policy(self):
        spec = StageSpec("s", "o", mode=BranchMode.SOFTWARE, evidence_policy="judged")
        self.assertEqual(spec.evidence_policy, "judged")

    def headless(self, stage):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store = EventStore(Path(directory.name) / "events.db")
        self.addCleanup(store.close)
        forge = BranchForge(MockProvider(), store, RunConfig(max_rounds=1))
        return forge, store, lambda: asyncio.run(forge.run("Goal", [stage]))

    def test_headless_software_stage_cannot_commit_without_checks(self):
        forge, store, run = self.headless(StageSpec("build", "Objective", mode=BranchMode.SOFTWARE))
        with self.assertRaisesRegex(RuntimeError, "cannot run or record checks"):
            run()
        run_id = store.run_ids()[0]
        self.assertEqual(forge.repository.get_run(run_id)["status"], "failed")
        self.assertEqual(forge.repository.branches(run_id), [])

    def test_headless_software_stage_runs_when_judged_is_chosen_explicitly(self):
        stage = StageSpec("build", "Objective", mode=BranchMode.SOFTWARE, evidence_policy="judged")
        forge, _, run = self.headless(stage)
        self.assertTrue(run()[0].winner.verified)


class StoreTests(unittest.TestCase):
    def test_atomic_block_rolls_back_every_write_on_error(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "events.db")
            self.addCleanup(store.close)
            with self.assertRaises(RuntimeError):
                with store.atomic():
                    store.append("run_1", "FIRST", {})
                    store.append("run_1", "SECOND", {})
                    raise RuntimeError("stop")
            self.assertEqual(store.events("run_1"), [])

    def test_schema_from_the_first_release_is_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.db"
            legacy = sqlite3.connect(path)
            legacy.execute("""CREATE TABLE stages (
                run_id TEXT NOT NULL, name TEXT NOT NULL, objective TEXT NOT NULL,
                deliverable TEXT NOT NULL, invariants TEXT NOT NULL, rubric TEXT NOT NULL,
                mode TEXT NOT NULL, status TEXT NOT NULL, winner_id TEXT,
                rationale TEXT, confidence REAL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(run_id, name))""")
            legacy.execute(
                "INSERT INTO stages VALUES ('run_old', 'stage', 'o', 'd', '[]', '{}', 'hybrid', 'running', NULL, NULL, NULL, 't', 't')"
            )
            legacy.commit()
            legacy.close()

            store = EventStore(path)
            self.addCleanup(store.close)
            repository = BranchRepository(store, Path(directory))
            self.assertEqual(repository.stages("run_old")[0]["evidence_policy"], "judged")
            self.assertEqual(store.query("PRAGMA user_version")[0][0], SCHEMA_VERSION)


class OrchestratorTests(unittest.TestCase):
    def test_weak_later_round_keeps_the_verified_survivors(self):
        class Fading(MockProvider):
            proposals = 0

            async def complete(self, system, prompt):
                if "PROPOSE_BRANCHES" in prompt:
                    self.proposals += 1
                    if self.proposals > 1:
                        return json.dumps({"branches": [
                            {"title": "Tweak", "claim": "c", "difference": "d", "novelty": 0.3},
                        ]})
                return await super().complete(system, prompt)

        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "events.db")
            self.addCleanup(store.close)
            forge = BranchForge(Fading(), store, RunConfig(max_rounds=2))
            outcomes = asyncio.run(forge.run("Goal", [StageSpec("stage", "Objective")]))

            run_id = outcomes[0].run_id
            self.assertEqual(forge.repository.get_run(run_id)["status"], "completed")
            tweak = [item for item in forge.repository.branches(run_id) if item["title"] == "Tweak"]
            self.assertEqual([item["status"] for item in tweak], ["pruned"])


    def test_error_after_completion_is_reported_as_itself(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "events.db")
            self.addCleanup(store.close)
            forge = BranchForge(MockProvider(), store, RunConfig(max_rounds=1))
            real_render = forge.repository.render_run
            calls = {"finished": False}

            def render(run_id):
                # Fail only the render that follows a completed run.
                if forge.repository.get_run(run_id)["status"] == "completed" and not calls["finished"]:
                    calls["finished"] = True
                    raise OSError("No space left on device")
                return real_render(run_id)

            with mock.patch.object(forge.repository, "render_run", side_effect=render):
                with self.assertRaisesRegex(OSError, "No space left"):
                    asyncio.run(forge.run("Goal", [StageSpec("stage", "Objective")]))
            run_id = store.run_ids()[0]
            self.assertEqual(forge.repository.get_run(run_id)["status"], "completed")


class CliTests(unittest.TestCase):
    def cli(self, directory, *arguments):
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run(
            [sys.executable, "-m", "branchforge", *arguments],
            cwd=directory, env=environment, capture_output=True, text=True,
        )

    def test_status_reads_the_agent_native_state_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            run_id = BranchForgeTools(directory).run_create("Agent run")["run_id"]
            result = self.cli(directory, "status")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(run_id, result.stdout)
            self.assertFalse((Path(directory) / "branchforge.db").exists())

    def test_inspection_does_not_create_state_in_an_empty_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.cli(directory, "runs")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_software_run_needs_an_explicit_judged_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            refused = self.cli(directory, "run", "Goal", "--mode", "software")
            self.assertEqual(refused.returncode, 1)
            self.assertIn("cannot run or record checks", refused.stderr)
            allowed = self.cli(directory, "run", "Goal", "--mode", "software", "--evidence-policy", "judged")
            self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_invalid_arguments_print_one_line_without_a_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.cli(directory, "run", "Goal", "--branches", "1")
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)
            self.assertIn("max_branches must be between 2 and 8", result.stderr)


class McpSchemaTests(unittest.TestCase):
    def setUp(self):
        try:
            import mcp  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("optional MCP dependency is not installed")
        from branchforge.mcp_server import build_server

        self.tools = {tool.name: tool for tool in asyncio.run(build_server().list_tools())}

    def test_every_parameter_is_described(self):
        missing = [
            f"{name}.{parameter}"
            for name, tool in self.tools.items()
            for parameter, schema in tool.inputSchema["properties"].items()
            if not schema.get("description")
        ]
        self.assertEqual(missing, [])

    def test_closed_choices_are_published_as_enums(self):
        mode = self.tools["stage_create"].inputSchema["properties"]["mode"]
        self.assertEqual(mode["enum"], ["research", "ideation", "software", "hybrid"])

    def test_read_only_tools_are_annotated(self):
        read_only = {name for name, tool in self.tools.items() if tool.annotations and tool.annotations.readOnlyHint}
        self.assertEqual(read_only, {"run_view", "run_status", "branch_view", "branch_list", "tree_view"})

    def test_check_record_is_exposed(self):
        self.assertIn("check_record", self.tools)

    def test_no_tool_executes_commands(self):
        self.assertNotIn("check_run", self.tools)
        self.assertNotIn("checks", self.tools["stage_create"].inputSchema["properties"])

    def test_tools_that_close_a_run_or_branch_are_marked_destructive(self):
        destructive = {name for name, tool in self.tools.items() if tool.annotations and tool.annotations.destructiveHint}
        self.assertEqual(destructive, {"run_finish", "stage_commit", "branch_prune", "branch_fail"})


if __name__ == "__main__":
    unittest.main()
