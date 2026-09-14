"""Verify explicit, baseline-bound adoption selection for local and hosted checks."""

import json
import shlex
import tempfile
import unittest
from pathlib import Path

import yaml

from tools.ci.adoption_basis import first_adoption


class AdoptionBasisTests(unittest.TestCase):
    def setUp(self):
        """Keep declarations outside any repository or persistent policy state."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.body_path = self.root / "pr-body.md"
        self.event_path = self.root / "event.json"
        self.baseline = "a" * 40

    def record(self, state="ungoverned", **changes):
        """Use evidence prose without pretending the parser verifies its claims."""
        result = {
            "state": state,
            "baseline": self.baseline,
            "evidence": "The original history predates this framework; see the PR characterization.",
        }
        if state == "independent":
            result["authority_disposition"] = (
                "Retain the project-specific input contract under its independently authored "
                "design decision; reconcile overlapping process rules in current Governance."
            )
        return result | changes

    def body(self, record):
        """Embed comparison selection in the ordinary PR evidence body."""
        return "Summary and characterization.\n\n```framework-adoption\n" + json.dumps(record) + "\n```\n"

    def select(self, body, *, hosted=False, baseline=None):
        """Exercise the same declaration through both supported evidence sources."""
        selected = self.baseline if baseline is None else baseline
        if hosted:
            self.event_path.write_text(json.dumps({
                "pull_request": {"base": {"sha": selected}, "body": body},
            }), encoding="utf-8")
            return first_adoption(None, self.event_path, selected)
        self.body_path.write_text(body, encoding="utf-8")
        return first_adoption(self.body_path, None, selected)

    def test_no_declaration_keeps_historical_comparison(self):
        self.assertFalse(first_adoption(None, None, None))
        for body in ("", "Ordinary policy update with no adoption declaration."):
            for hosted in (False, True):
                with self.subTest(body=body, hosted=hosted):
                    self.assertFalse(self.select(body, hosted=hosted))

    def test_each_resolved_state_selects_its_comparison_locally_and_hosted(self):
        for state, expected in (("ungoverned", True), ("independent", True), ("update", False)):
            for hosted in (False, True):
                with self.subTest(state=state, hosted=hosted):
                    self.assertEqual(self.select(self.body(self.record(state)), hosted=hosted), expected)

    def test_ambiguous_lineage_cannot_select_any_completion_comparison(self):
        for hosted in (False, True):
            with self.subTest(hosted=hosted), self.assertRaisesRegex(ValueError, "ambiguous lineage"):
                self.select(self.body(self.record("ambiguous")), hosted=hosted)

    def test_independent_governance_requires_authority_disposition(self):
        for missing in (None, "", " \n ", [], {}):
            record = self.record("independent", authority_disposition=missing)
            with self.subTest(disposition=missing), self.assertRaisesRegex(ValueError, "authority_disposition"):
                self.select(self.body(record))
        record = self.record("independent")
        del record["authority_disposition"]
        with self.assertRaisesRegex(ValueError, "authority_disposition"):
            self.select(self.body(record))

    def test_evidence_is_required_for_every_explicit_state(self):
        for state in ("ungoverned", "independent", "update", "ambiguous"):
            for missing in (None, "", " \t", [], {}):
                with self.subTest(state=state, evidence=missing), self.assertRaisesRegex(ValueError, "evidence"):
                    self.select(self.body(self.record(state, evidence=missing)))

    def test_every_explicit_state_binds_the_actual_baseline(self):
        for state in ("ungoverned", "independent", "update", "ambiguous"):
            with self.subTest(state=state), self.assertRaisesRegex(ValueError, "does not match"):
                self.select(self.body(self.record(state)), baseline="b" * 40)

    def test_baseline_requires_full_commit_identity(self):
        for identity in (None, "", "origin/dev", "a" * 7, "g" * 40, 123):
            with self.subTest(identity=identity), self.assertRaisesRegex(ValueError, "full commit SHA"):
                self.select(self.body(self.record(baseline=identity)))
        self.body_path.write_text(self.body(self.record()), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "full commit SHA"):
            first_adoption(self.body_path, None, None)

    def test_unknown_states_and_fields_cannot_silently_change_selection(self):
        records = [self.record(state=state) for state in ("bootstrap", "", None, [], {})]
        records.extend([self.record(unrecognized=True), {"state": "ungoverned"}, []])
        for record in records:
            with self.subTest(record=record), self.assertRaises(ValueError):
                self.select(self.body(record))

    def test_duplicate_declarations_and_fields_are_rejected(self):
        body = self.body(self.record())
        with self.assertRaisesRegex(ValueError, "only one declaration"):
            self.select(body + body)
        with self.assertRaisesRegex(ValueError, "duplicate field"):
            self.select(body.replace('"state": "ungoverned"', '"state": "update", "state": "ungoverned"'))

    def test_malformed_declared_blocks_fail_closed(self):
        body = self.body(self.record())
        malformed = (
            body.removesuffix("```\n"),
            body.replace("```framework-adoption", "```framework-adoption unexpected"),
            "```framework-adoption\n{invalid JSON}\n```\n",
        )
        for value in malformed:
            with self.subTest(body=value), self.assertRaises(ValueError):
                self.select(value)

    def test_markdown_whitespace_fence_length_and_json_order_do_not_change_selection(self):
        record = self.record()
        reordered = {key: record[key] for key in reversed(record)}
        for fence in ("```", "````", "~~~"):
            body = f"  {fence} framework-adoption  \r\n{json.dumps(reordered, indent=2)}\r\n {fence}\r\n"
            with self.subTest(fence=fence):
                self.assertTrue(self.select(body))

    def test_quoted_fence_examples_do_not_select_or_duplicate_a_declaration(self):
        for outer in ("````", "~~~~"):
            example = f"{outer}text\n" + self.body(self.record()) + f"{outer}\n"
            for hosted in (False, True):
                with self.subTest(outer=outer, hosted=hosted):
                    self.assertFalse(self.select(example, hosted=hosted))
                    self.assertFalse(self.select(
                        example + self.body(self.record("update")), hosted=hosted,
                    ))
                    self.assertTrue(self.select(
                        self.body(self.record()) + example, hosted=hosted,
                    ))

    def test_other_fences_skip_until_their_matching_closer(self):
        example = (
            "````text\n~~~\n```\n" + self.body(self.record())
            + "`````\n" + self.body(self.record("update"))
        )
        self.assertFalse(self.select(example))

    def test_indented_code_examples_do_not_select_a_declaration(self):
        for indentation in ("    ", "\t", "   \t"):
            example = "".join(
                indentation + line for line in self.body(self.record()).splitlines(keepends=True)
            )
            for hosted in (False, True):
                with self.subTest(indentation=indentation, hosted=hosted):
                    self.assertFalse(self.select(example, hosted=hosted))
                    self.assertTrue(self.select(
                        example + "\n" + self.body(self.record()), hosted=hosted,
                    ))

    def test_unclosed_non_adoption_fence_remains_an_inert_example(self):
        example = "````text\n" + self.body(self.record())
        self.assertFalse(self.select(example))

    def test_event_cannot_select_a_different_base(self):
        self.event_path.write_text(json.dumps({
            "pull_request": {"base": {"sha": "b" * 40}, "body": self.body(self.record())},
        }), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "event base does not match"):
            first_adoption(None, self.event_path, self.baseline)

    def test_event_shape_is_validated_even_without_a_declaration(self):
        invalid = (
            [], {}, {"pull_request": []}, {"pull_request": {"base": []}},
            {"pull_request": {"base": {"sha": "dev"}, "body": ""}},
            {"pull_request": {"base": {"sha": self.baseline}, "body": {}}},
        )
        for event in invalid:
            self.event_path.write_text(json.dumps(event), encoding="utf-8")
            with self.subTest(event=event), self.assertRaises(ValueError):
                first_adoption(None, self.event_path, self.baseline)

    def test_empty_hosted_body_retains_historical_comparison(self):
        self.assertFalse(self.select(None, hosted=True))

    def test_local_and_hosted_inputs_are_mutually_exclusive(self):
        with self.assertRaisesRegex(ValueError, "not both"):
            first_adoption(self.body_path, self.event_path, self.baseline)


class HostedAdoptionBasisTests(unittest.TestCase):
    def test_repository_policy_receives_event_and_candidate_comparison(self):
        """Bind hosted declaration selection to its existing base and candidate."""
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.load(
            (root / ".github/workflows/ci.yml").read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        job = workflow["jobs"]["repository-policy"]
        checks = []
        for step in job["steps"]:
            for line in step.get("run", "").replace("\\\n", " ").splitlines():
                tokens = shlex.split(line)
                if len(tokens) > 1 and tokens[1] == "tools/ci/check_repo.py":
                    checks.append((step, tokens[2:]))
        self.assertEqual(len(checks), 1)
        step, arguments = checks[0]
        for option, value in {
            "--baseline-ref": "$BASE_SHA",
            "--candidate-ref": "$GITHUB_SHA",
            "--event-path": "$GITHUB_EVENT_PATH",
        }.items():
            with self.subTest(option=option):
                self.assertIn(option, arguments)
                self.assertEqual(arguments[arguments.index(option) + 1], value)
        self.assertEqual(
            "".join(step["env"]["BASE_SHA"].split()),
            "${{github.event.pull_request.base.sha}}",
        )


if __name__ == "__main__":
    unittest.main()
