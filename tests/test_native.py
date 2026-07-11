import json
import tempfile
import unittest
from pathlib import Path

from branchforge.native import BranchForgeTools


class NativeToolsTests(unittest.TestCase):
    def test_complete_agent_native_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = BranchForgeTools(root)
            run = tools.run_create("Choose an event-processing architecture")
            run_id = run["run_id"]
            tools.stage_create(
                run_id,
                "architecture",
                "Choose the architecture",
                mode="software",
                invariants=["At-least-once delivery", "Tenant isolation"],
            )
            first = tools.branch_add(
                run_id,
                "architecture",
                "Event sourced",
                "An event log should be authoritative",
                "Optimizes auditability",
                predictions=["State can be replayed"],
                falsifiers=["Recovery exceeds the RTO"],
                novelty=0.9,
            )
            second = tools.branch_add(
                run_id,
                "architecture",
                "Relational audit journal",
                "Mutable state plus an audit journal is sufficient",
                "Optimizes operational simplicity",
                predictions=["Recovery is predictable"],
                falsifiers=["Audit reconstruction is incomplete"],
                novelty=0.85,
            )
            for branch in (first, second):
                tools.branch_record_result(
                    run_id,
                    branch["branch_id"],
                    f"Implement {branch['title']}",
                    evidence=["A reproducible test was specified"],
                    risks=["Scale remains untested"],
                    confidence=0.75,
                )
                tools.branch_verify(
                    run_id,
                    branch["branch_id"],
                    verified=True,
                    scores={"correctness": 0.8, "feasibility": 0.7},
                    notes=["Hard invariants addressed"],
                )

            tools.stage_commit(
                run_id,
                "architecture",
                first["branch_id"],
                "Better audit reconstruction",
                0.82,
                votes={first["branch_id"]: 1},
            )
            completed = tools.run_finish(run_id)

            self.assertEqual(completed["run"]["status"], "completed")
            branches = tools.branch_list(run_id)
            self.assertEqual({branch["status"] for branch in branches}, {"committed", "pruned"})
            tree = tools.tree_view(run_id, fmt="json")
            self.assertEqual(len(tree["roots"]), 2)
            run_dir = root / ".branchforge" / "runs" / run_id
            self.assertTrue((run_dir / "RUN.json").is_file())
            self.assertTrue((run_dir / "DECISION.md").is_file())
            self.assertIn("Better audit reconstruction", (run_dir / "DECISION.md").read_text())

    def test_artifact_must_remain_inside_project(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            tools = BranchForgeTools(root)
            run_id = tools.run_create("Store evidence")["run_id"]
            tools.stage_create(run_id, "research", "Research", mode="research")
            branch = tools.branch_add(run_id, "research", "A", "Claim", "Difference")
            external = Path(outside) / "secret.txt"
            external.write_text("not authorized")
            with self.assertRaisesRegex(ValueError, "inside the target project"):
                tools.artifact_store(run_id, branch["branch_id"], str(external))

    def test_incomplete_run_cannot_finish(self):
        with tempfile.TemporaryDirectory() as directory:
            tools = BranchForgeTools(directory)
            run_id = tools.run_create("Incomplete")["run_id"]
            tools.stage_create(run_id, "stage", "Still active")
            with self.assertRaisesRegex(ValueError, "unfinished stages"):
                tools.run_finish(run_id)

    def test_stage_rejects_unfinished_branch_and_accepts_recorded_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            tools = BranchForgeTools(directory)
            run_id = tools.run_create("Handle explorer failures")["run_id"]
            tools.stage_create(run_id, "stage", "Select a robust approach")
            winner = tools.branch_add(run_id, "stage", "Winner", "Works", "Reliable")
            failed = tools.branch_add(run_id, "stage", "Risky", "Might work", "Experimental")
            tools.branch_record_result(run_id, winner["branch_id"], "A verified proposal")
            tools.branch_verify(run_id, winner["branch_id"], verified=True)

            with self.assertRaisesRegex(ValueError, "unfinished branches"):
                tools.stage_commit(run_id, "stage", winner["branch_id"], "Best evidence", 0.8)

            result = tools.branch_fail(run_id, failed["branch_id"], "Prototype crashed")
            self.assertEqual(result["status"], "failed")
            tools.stage_commit(run_id, "stage", winner["branch_id"], "Best evidence", 0.8)

    def test_optional_mcp_server_exposes_native_tools(self):
        try:
            import mcp  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("optional MCP dependency is not installed")

        from branchforge.mcp_server import build_server

        server = build_server()
        names = {tool.name for tool in server._tool_manager.list_tools()}
        self.assertEqual(len(names), 19)
        self.assertIn("branch_fail", names)
        prompts = {prompt.name for prompt in server._prompt_manager.list_prompts()}
        self.assertIn("branchforge", prompts)


if __name__ == "__main__":
    unittest.main()
