from copy import deepcopy
from pathlib import Path
import unittest
from tests import skill_contract


def claim_result(applied: bool) -> dict[str, object]:
    return {"ok": True, "command": "claim", "applied": applied,
            "vault": "/synthetic/vault", "changes": [{"action": "create_file",
            "path": "daily/2042-04-03.md",
            "status": "completed" if applied else "planned"}], "issues": []}


def success_events() -> list[dict[str, object]]:
    return [{"kind": "preview", "exit": 0, "result": claim_result(False)},
            {"kind": "apply", "exit": 0, "result": claim_result(True)},
            {"kind": "verify", "identity": [1, 7], "regular": True, "size": 0},
            {"kind": "verify", "identity": [1, 7], "regular": True, "size": 0},
            {"kind": "native-edit", "ok": True}]


class ClaimWorkflowTests(unittest.TestCase):
    def test_success_and_missing_invalid_unsupported_capability(self):
        validate = getattr(skill_contract, "validate_claim_trace", None)
        self.assertTrue(callable(validate), "claim trace validator is required")
        self.assertEqual(validate(success_events()), ())
        for code, payload in ((127, None), (2, None), (0, "invalid JSON"),
                              (0, {}), (5, {"ok": False})):
            failed = {"kind": "preview", "exit": code, "result": payload}
            self.assertEqual(validate([failed, {"kind": "stop", "partial": False}]), ())
            self.assertIn("claim.unsafe-continuation",
                          validate([failed, {"kind": "native-edit", "ok": True}]))

    def test_identity_collision_and_partial_failure_gates(self):
        validate = getattr(skill_contract, "validate_claim_trace", None)
        self.assertTrue(callable(validate), "claim trace validator is required")
        for field, value in (("identity", [1, 8]), ("size", 1), ("regular", False)):
            events = success_events()
            events[3][field] = value
            self.assertIn("claim.unsafe-continuation", validate(events))
            self.assertEqual(validate(events[:4] + [{"kind": "stop", "partial": True}]), ())
        events = success_events()
        events[1] = {"kind": "apply", "exit": 6, "result": {"ok": False}}
        self.assertIn("claim.unsafe-continuation", validate(events))
        self.assertEqual(validate(events[:2] + [{"kind": "stop", "partial": False}]), ())
        events = success_events()
        events[-1]["ok"] = False
        self.assertEqual(validate(events + [{"kind": "stop", "partial": True}]), ())
        self.assertIn("claim.unsafe-continuation", validate(events + [{"kind": "delete"}]))

    def test_mismatched_claim_payloads_stop_before_edit(self):
        validate = getattr(skill_contract, "validate_claim_trace", None)
        self.assertTrue(callable(validate), "claim trace validator is required")
        for stage in (0, 1):
            for field, value in (("command", "init"), ("vault", "/synthetic/other"),
                                 ("applied", stage == 0), ("ok", False),
                                 ("changes", []), ("issues", [{}])):
                with self.subTest(stage=stage, field=field):
                    events = success_events()
                    events[stage]["result"][field] = value
                    self.assertIn("claim.unsafe-continuation", validate(events))
                    self.assertEqual(validate(events[:stage+1] + [{"kind": "stop", "partial": stage == 1}]), ())
            for field in ("action", "path", "status"):
                events = success_events()
                events[stage]["result"]["changes"][0][field] = "mismatch"
                self.assertIn("claim.unsafe-continuation", validate(events))
            for mutation in ("missing", "extra"):
                events = success_events()
                if mutation == "missing":
                    del events[stage]["result"]["vault"]
                else:
                    events[stage]["result"]["extra"] = True
                self.assertIn("claim.unsafe-continuation", validate(events))
        for value in (None, [], [1], [1, "7"], [True, 7]):
            events = success_events()
            events[2]["identity"] = value
            self.assertIn("claim.unsafe-continuation", validate(events))
        for field, value in (("size", None), ("size", False), ("regular", 1)):
            events = success_events()
            events[2][field] = value
            self.assertIn("claim.unsafe-continuation", validate(events))

    def test_forbidden_native_fallbacks_are_rejected(self):
        validate = getattr(skill_contract, "validate_claim_trace", None)
        self.assertTrue(callable(validate), "claim trace validator is required")
        for kind in ("native-write", "mkdir", "delete", "rollback", "retry-existing"):
            with self.subTest(kind=kind):
                self.assertIn("claim.unsafe-continuation", validate([{"kind": kind}]))
                self.assertIn("claim.unsafe-continuation", validate(success_events()[:2] + [{"kind": kind}]))
        events = success_events()
        events[0]["exit"] = True
        self.assertIn("claim.unsafe-continuation", validate(events))

    def test_completed_apply_failure_preserves_partial_state(self):
        validate = getattr(skill_contract, "validate_claim_trace", None)
        self.assertTrue(callable(validate), "claim trace validator is required")
        for code, payload in ((6, claim_result(True)), (0, None), (0, "invalid JSON")):
            events = success_events()[:1] + [{"kind": "apply", "exit": code, "result": payload}]
            self.assertEqual(validate(events + [{"kind": "stop", "partial": True}]), ())
            self.assertIn("claim.unsafe-continuation", validate(events + [{"kind": "stop", "partial": False}]))
        self.assertEqual(validate(success_events(), expected_vault="/synthetic/vault",
                                  expected_path="daily/2042-04-03.md"), ())
        self.assertIn("claim.unsafe-continuation",
                      validate(success_events(), expected_vault="/synthetic/other"))

    def test_all_five_skills_declare_claim_protocol(self):
        from tests.test_skills import BASE_INVARIANTS, CORE_COMMANDS
        for name in ("recording", "daily-wrap-up", "weekly-review", "project-kickoff", "decision-log"):
            with self.subTest(name=name):
                contract = skill_contract.load_effective_contract(
                    Path("skills") / name / "SKILL.md", CORE_COMMANDS[name])
                for key, value in BASE_INVARIANTS.items():
                    self.assertEqual(dict(contract.invariants)[key], value)
                self.assertEqual(len([line for line in contract.commands if line.startswith("threadroot claim ")]), 2)
