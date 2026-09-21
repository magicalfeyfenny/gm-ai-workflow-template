import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.ci.adversarial_review import (
    ADJUDICATION_RESULT_SCHEMA,
    REVIEW_RESULT_SCHEMA,
    ReviewContractError,
    build_adjudication_packet,
    build_review_packet,
    candidate_identity,
    validate_adjudication_packet,
    validate_review_packet,
)
from tools.ci.adversarial_review_session import (
    ReviewSessionError,
    _run_fresh_codex_session,
    _write_sandbox_profile,
    run_adversarial_review,
    run_review_lifecycle,
)
from tools.ci.adversarial_review_contracts import SESSION_FAILURE_SCHEMA
from tools.ci.adversarial_review_process import (
    ProviderEventDecodeError,
    ProviderHangError,
    run_provider_process,
)


REVISION = "220cc0114ced1c521c25b5f26d3ec0a597469afb50429b1699615497fce0f372"
DIFF = "diff --git a/tools/ci/adversarial_review.py b/tools/ci/adversarial_review.py\n"
INCLUDED = [
    "tools/ci/adversarial_review.py",
    "tools/ci/adversarial_review_session.py",
    "tools/tests/test_adversarial_review.py",
]
SEMANTIC_SOURCE = """
Source-backed semantic evidence fixture:

- The candidate omits a required invariant that the accepted contract requires.
- The Python 3.13+ concern is a bounded same-outcome improvement within this issue.
- The separately meaningful concern is outside the accepted outcome.
- The python3.12 documentation example already uses a supported interpreter.
- The mocked temporary-environment path adds no defect because unit and live integration evidence cover it.
- The compatibility claim has no independent compatibility evidence and no concrete consumer.
- Manual visual observation is not an accepted requirement.
- The unavailable environment capability is not candidate failure because existing evidence passes.
""".strip()


def issue_contract() -> dict:
    return {
        "repository": "owner/game",
        "id": "I_116",
        "number": 116,
        "title": "Add adversarial review and adjudication",
        "body": "Acceptance criteria\nEngineering constraints\nValidation\n",
        "state": "OPEN",
        "work_blocked": False,
        "open_blocker_ids": [],
        "revision": REVISION,
    }


def candidate() -> dict:
    return {
        "base_ref": "origin/dev",
        "head_ref": "work/116-adversarial-review-adjudication",
        "head_sha": "h" * 40,
        "tree_sha": "t" * 40,
        "diff_sha256": hashlib.sha256(DIFF.encode()).hexdigest(),
        "diff": DIFF,
    }


def semantic_packet() -> dict:
    current = candidate()
    return build_review_packet(
        issue_contract(),
        current,
        {
            "sources": [
                {
                    "path": "tools/tests/test_adversarial_review_followup.py",
                    "section": "source-backed semantic evidence fixture",
                    "text": SEMANTIC_SOURCE,
                }
            ],
            "review_doctrine": (
                "Classify from the cited source text; do not infer compatibility "
                "or manual-validation obligations."
            ),
        },
        {
            "issue_contract_revision": REVISION,
            "candidate_identity": candidate_identity(current),
            "checks": [
                {"name": "semantic fixture", "result": "passed", "evidence": ["fixture"]}
            ],
        },
        {"included": INCLUDED, "exclusions": ["readiness", "merge", "release"]},
    )


def finding(finding_id: str, claim: str, severity: str = "medium") -> dict:
    return {
        "finding_id": finding_id,
        "severity": severity,
        "defect_or_invariant": claim,
        "supporting_evidence": ["governance.0"],
        "contract_or_governance": "accepted contract and source-backed fixture",
        "affected_location": INCLUDED[0],
    }


def semantic_findings() -> list[dict]:
    return [
        finding("F-blocker", "candidate omits a required invariant", "high"),
        finding(
            "F-python313",
            "Python 3.13+ concern is a bounded same-outcome improvement",
            "low",
        ),
        finding(
            "F-follow-up",
            "separately meaningful concern is outside the accepted outcome",
        ),
        finding(
            "F-doc-example",
            "python3.12 documentation example is already satisfied",
            "high",
        ),
        finding(
            "F-temp-mock",
            "mocked temporary-environment path adds no defect beyond existing evidence",
            "high",
        ),
        finding(
            "F-compat",
            "old representation must remain compatible without an independent consumer",
            "high",
        ),
        finding(
            "F-manual",
            "manual visual observation should be added despite no contract requirement",
            "high",
        ),
        finding(
            "F-unavailable",
            "unavailable environment capability proves candidate failure",
            "high",
        ),
    ]


def review_result(packet: dict, findings: list[dict]) -> dict:
    return {
        "schema": REVIEW_RESULT_SCHEMA,
        "candidate_identity": candidate_identity(packet["candidate"]),
        "findings": findings,
    }


def correction() -> dict:
    return {
        "summary": "Apply the bounded source-backed correction.",
        "locations": [INCLUDED[0]],
        "validation": ["rerun semantic fixtures"],
    }


def decision(finding_id: str, disposition: str, value: dict | None = None) -> dict:
    return {
        "finding_id": finding_id,
        "disposition": disposition,
        "basis": "source text supports this deterministic fixture disposition",
        "correction": value,
        "correction_accepted": value is not None,
    }


def adjudication_result(packet: dict, decisions: list[dict]) -> dict:
    return {
        "schema": ADJUDICATION_RESULT_SCHEMA,
        "candidate_identity": packet["candidate_identity"],
        "dispositions": decisions,
        "human_handoff": {"required": False, "reason": None},
    }


FIXTURE_EXPECTED = [
    "blocker",
    "patch-now",
    "follow-up",
    "reject",
    "reject",
    "reject",
    "reject",
    "reject",
]
FIXTURE_SOURCE_ASSERTIONS = (
    "accepted contract requires",
    "bounded same-outcome improvement within this issue",
    "outside the accepted outcome",
    "already uses a supported interpreter",
    "unit and live integration evidence cover it",
    "no independent compatibility evidence and no concrete consumer",
    "manual visual observation is not an accepted requirement",
    "existing evidence passes",
)


def fixed_source_fixture_adjudication(packet: dict) -> dict:
    source_text = "\n".join(item["text"] for item in packet["evidence"]["source_items"])
    for assertion in FIXTURE_SOURCE_ASSERTIONS:
        if assertion not in source_text.casefold():
            raise AssertionError(f"semantic source fixture is missing: {assertion}")
    corrections = [correction(), correction(), None, None, None, None, None, None]
    decisions = [
        decision(item["finding_id"], disposition, correction_value)
        for item, disposition, correction_value in zip(
            packet["findings"], FIXTURE_EXPECTED, corrections
        )
    ]
    return adjudication_result(packet, decisions)


class SourceBackedFixtureTests(unittest.TestCase):
    def test_contract_revision_binds_snapshot_contents(self):
        packet = semantic_packet()
        packet["issue_contract"]["body"] += "changed without re-acceptance\n"
        with self.assertRaisesRegex(ReviewContractError, "accepted snapshot"):
            validate_review_packet(packet)

    def test_production_contract_path_covers_fixed_source_classifications(self):
        review_packet = semantic_packet()
        findings = semantic_findings()

        def runner(role, payload, output_schema):
            if role == "reviewer":
                return review_result(payload, findings)
            return fixed_source_fixture_adjudication(payload)

        result = run_adversarial_review(review_packet, session_runner=runner)
        self.assertEqual(
            [item["disposition"] for item in result["dispositions"]],
            [
                "blocker",
                "patch-now",
                "follow-up",
                "reject",
                "reject",
                "reject",
                "reject",
                "reject",
            ],
        )

    def test_material_source_change_exposes_incorrect_fixture_classification(self):
        review_packet = semantic_packet()
        findings = semantic_findings()
        original = build_adjudication_packet(review_packet, findings)
        changed = json.loads(json.dumps(original))
        original_item = original["evidence"]["source_items"][0]
        changed_item = changed["evidence"]["source_items"][0]
        self.assertEqual(original_item["evidence_id"], changed_item["evidence_id"])
        changed_item["text"] = changed_item["text"].replace(
            "bounded same-outcome improvement within this issue",
            "outside the accepted outcome",
        )
        validate_adjudication_packet(changed)
        fixed_source_fixture_adjudication(original)
        with self.assertRaisesRegex(AssertionError, "semantic source fixture"):
            fixed_source_fixture_adjudication(changed)


class SandboxBoundaryTests(unittest.TestCase):
    def test_profile_allows_selected_provider_not_its_siblings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = root / "provider"
            provider.mkdir()
            executable = provider / "fake-codex"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            codex_home = root / "codex-home"
            codex_home.mkdir()
            profile = root / "sandbox.sb"
            _write_sandbox_profile(profile, root, executable, codex_home)
            text = profile.read_text(encoding="utf-8")
        self.assertIn(f'(allow file-read* (literal "{executable.resolve()}"))', text)
        self.assertNotIn(f'(allow file-read* (subpath "{provider.resolve()}"))', text)
        self.assertNotIn('(allow file-read* (subpath "/usr"))', text)
        self.assertIn(
            f'(allow process-exec (literal "{executable.resolve()}"))', text
        )
        self.assertNotIn("(allow process-exec*)", text)
        self.assertNotIn("(allow process-fork)", text)

    @unittest.skipUnless(shutil.which("sandbox-exec"), "requires macOS Seatbelt")
    def test_provider_cannot_spawn_a_tool_to_read_authentication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source-codex-home"
            source_home.mkdir()
            (source_home / "auth.json").write_text(
                '{"access_token":"must-not-be-read-by-a-tool"}', encoding="utf-8"
            )
            executable = root / "fake-codex"
            executable.write_text(
                '#!/bin/bash\n/bin/cat "$CODEX_HOME/auth.json"\n',
                encoding="utf-8",
            )
            executable.chmod(0o755)
            with patch.dict(os.environ, {"CODEX_HOME": str(source_home)}):
                with self.assertRaisesRegex(ReviewSessionError, "exit status"):
                    _run_fresh_codex_session(
                        "reviewer",
                        {},
                        {"type": "object"},
                        executable=str(executable),
                    )

    @unittest.skipUnless(shutil.which("sandbox-exec"), "requires macOS Seatbelt")
    def test_legacy_read_only_runtime_home_fails_before_provider_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "fake-codex"
            executable.write_text(
                "#!/bin/bash\nset -eu\nmkdir \"$CODEX_HOME/runtime-state\"\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            codex_home = root / "codex-home"
            codex_home.mkdir()
            profile = root / "sandbox.sb"
            _write_sandbox_profile(profile, root, executable, codex_home)
            writable_runtime = (
                f'(allow file-read* file-write* (subpath "{codex_home.resolve()}"))'
            )
            profile.write_text(
                profile.read_text(encoding="utf-8").replace(
                    writable_runtime,
                    f'(allow file-read* (subpath "{codex_home.resolve()}"))',
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    shutil.which("sandbox-exec"),
                    "-f",
                    str(profile),
                    "--",
                    str(executable),
                ],
                cwd=root,
                env={"CODEX_HOME": str(codex_home)},
                capture_output=True,
                check=False,
            )
            created = (codex_home / "runtime-state").exists()
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse(created)

    def test_runtime_home_is_writable_but_authentication_stays_external(self):
        calls: list[dict[str, object]] = []

        def fake_process(command, **kwargs):
            profile = Path(command[2]).read_text(encoding="utf-8")
            output_path = Path(command[command.index("--output-last-message") + 1])
            runtime_home = Path(kwargs["environment"]["CODEX_HOME"])
            authentication_link = runtime_home / "auth.json"
            calls.append(
                {
                    "profile": profile,
                    "cwd": Path(kwargs["cwd"]),
                    "runtime_home": runtime_home,
                    "authentication_target": authentication_link.resolve(),
                    "authentication_mode": authentication_link.stat().st_mode & 0o777,
                }
            )
            output_path.write_text("{}", encoding="utf-8")
            return 0

        with tempfile.TemporaryDirectory() as directory:
            source_home = Path(directory) / "source-codex-home"
            source_home.mkdir()
            source_auth = source_home / "auth.json"
            source_auth.write_text('{"access_token":"sentinel"}', encoding="utf-8")
            with patch.dict(os.environ, {"CODEX_HOME": str(source_home)}), patch(
                "tools.ci.adversarial_review_session._sandbox_path",
                return_value="/usr/bin/sandbox-exec",
            ), patch(
                "tools.ci.adversarial_review_session._run_provider_process",
                side_effect=fake_process,
            ):
                _run_fresh_codex_session(
                    "reviewer",
                    {},
                    {"type": "object"},
                    executable="/fake/codex",
                )

        self.assertEqual(len(calls), 1)
        call = calls[0]
        cwd = call["cwd"]
        runtime_home = call["runtime_home"]
        authentication_target = call["authentication_target"]
        self.assertIsInstance(cwd, Path)
        self.assertIsInstance(runtime_home, Path)
        self.assertIsInstance(authentication_target, Path)
        self.assertNotIn(cwd, runtime_home.parents)
        self.assertNotIn(runtime_home, cwd.parents)
        self.assertNotIn(cwd, authentication_target.parents)
        self.assertEqual(runtime_home.name, "codex-home")
        self.assertEqual(call["authentication_mode"], 0o400)
        profile = call["profile"]
        self.assertIn(
            f'(allow file-read* file-write* (subpath "{runtime_home}"))',
            profile,
        )
        self.assertNotIn(
            f'(allow file-read* file-write* (subpath "{cwd}"))',
            profile,
        )
        self.assertIn(
            f'(deny file-write* (literal "{authentication_target}"))',
            profile,
        )

    @unittest.skipUnless(shutil.which("sandbox-exec"), "requires macOS Seatbelt")
    def test_runtime_state_is_writable_without_modifying_copied_authentication(self):
        with tempfile.TemporaryDirectory() as directory:
            source_home = Path(directory) / "source-codex-home"
            source_home.mkdir()
            source_sentinel = source_home / "configured-home-sentinel"
            source_sentinel.write_text("must-remain-unreadable", encoding="utf-8")
            source_auth = source_home / "auth.json"
            original = '{"access_token":"must-remain-unchanged"}'
            source_auth.write_text(original, encoding="utf-8")
            executable = Path(directory) / "fake-codex"
            executable.write_text(
                """#!/bin/bash
set -eu
if [ -r "CONFIGURED_HOME_SENTINEL" ]; then
    exit 97
fi
if : > "$PWD/packet-write-sentinel"; then
    exit 98
fi
printf '%s' runtime-state > "$CODEX_HOME/runtime-state"
if printf '%s' tampered > "$CODEX_HOME/auth.json"; then
    exit 96
fi
output=""
previous=""
for argument in "$@"; do
    if [ "$previous" = "--output-last-message" ]; then
        output="$argument"
    fi
    previous="$argument"
done
[ -n "$output" ]
printf '%s\n' '{"type":"thread.started"}'
printf '%s\n' '{"type":"turn.started"}'
printf '%s' '{}' > "$output"
""",
                encoding="utf-8",
            )
            executable.write_text(
                executable.read_text(encoding="utf-8").replace(
                    "CONFIGURED_HOME_SENTINEL", str(source_sentinel)
                ),
                encoding="utf-8",
            )
            executable.chmod(0o755)
            with patch.dict(os.environ, {"CODEX_HOME": str(source_home)}):
                result = _run_fresh_codex_session(
                    "reviewer",
                    {},
                    {"type": "object"},
                    executable=str(executable),
                )
            self.assertEqual(result, {})
            self.assertEqual(source_auth.read_text(encoding="utf-8"), original)


class ProviderLivenessTests(unittest.TestCase):
    def _provider_command(self, root: Path, body: str) -> tuple[list[str], Path]:
        executable = root / "fake-provider"
        executable.write_text("#!/bin/sh\nset -eu\n" + body, encoding="utf-8")
        executable.chmod(0o755)
        output = root / "last-message.json"
        return [str(executable), "--json", "--output-last-message", str(output)], output

    def test_active_work_is_not_terminated_by_elapsed_wall_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command, output = self._provider_command(
                root,
                """
printf '%s\\n' '{\"type\":\"thread.started\"}'
printf '%s\\n' '{\"type\":\"turn.started\"}'
sleep 0.4
printf '%s' '{}' > \"$3\"
""",
            )
            started = time.monotonic()
            returncode = run_provider_process(
                command,
                cwd=root,
                environment={"PATH": "/usr/bin:/bin"},
                prompt="bounded packet",
                startup_timeout_seconds=0.2,
            )
            elapsed = time.monotonic() - started
            output_exists = output.exists()
        self.assertEqual(returncode, 0)
        self.assertTrue(output_exists)
        self.assertGreaterEqual(elapsed, 0.35)

    def test_unconsumed_large_prompt_is_bounded_during_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command, output = self._provider_command(root, "sleep 2\n")
            started = time.monotonic()
            with self.assertRaises(ProviderHangError) as raised:
                run_provider_process(
                    command,
                    cwd=root,
                    environment={"PATH": "/usr/bin:/bin"},
                    prompt="x" * (2 * 1024 * 1024),
                    startup_timeout_seconds=0.05,
                )
            elapsed = time.monotonic() - started
        self.assertEqual(raised.exception.phase, "pre-turn prompt delivery")
        self.assertLess(elapsed, 1.5)
        self.assertFalse(output.exists())

    def test_continuously_readable_partial_event_data_cannot_bypass_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command, _ = self._provider_command(
                root,
                "while :; do printf x; sleep 0.005; done\n",
            )
            started = time.monotonic()
            with self.assertRaises(ProviderHangError) as raised:
                run_provider_process(
                    command,
                    cwd=root,
                    environment={"PATH": "/usr/bin:/bin"},
                    prompt="bounded packet",
                    startup_timeout_seconds=0.05,
                )
            elapsed = time.monotonic() - started
        self.assertEqual(raised.exception.phase, "pre-turn startup")
        self.assertLess(elapsed, 1.5)
    def test_pre_turn_provider_hang_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command, output = self._provider_command(root, "sleep 2\n")
            started = time.monotonic()
            with self.assertRaises(ProviderHangError) as raised:
                run_provider_process(
                    command,
                    cwd=root,
                    environment={"PATH": "/usr/bin:/bin"},
                    prompt="bounded packet",
                    startup_timeout_seconds=0.05,
                )
            elapsed = time.monotonic() - started
        self.assertEqual(raised.exception.phase, "pre-turn startup")
        self.assertLess(elapsed, 1.5)
        self.assertFalse(output.exists())

    def test_positive_dead_connection_evidence_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command, _ = self._provider_command(
                root,
                """
printf '%s\\n' '{\"type\":\"thread.started\"}'
printf '%s\\n' '{\"type\":\"turn.started\"}'
exec 1>&-
while :; do :; done
""",
            )
            started = time.monotonic()
            with self.assertRaises(ProviderHangError) as raised:
                run_provider_process(
                    command,
                    cwd=root,
                    environment={"PATH": "/usr/bin:/bin"},
                    prompt="bounded packet",
                    startup_timeout_seconds=0.5,
                )
            elapsed = time.monotonic() - started
        self.assertEqual(raised.exception.phase, "closed event stream")
        self.assertLess(elapsed, 1.5)


class SessionFailureTests(unittest.TestCase):
    def test_invalid_session_result_becomes_bounded_handoff(self):
        packet = semantic_packet()

        def invalid_runner(role, payload, output_schema):
            if role == "reviewer":
                return {
                    "schema": REVIEW_RESULT_SCHEMA,
                    "candidate_identity": candidate_identity(payload["candidate"]),
                    "findings": [
                        {
                            **semantic_findings()[0],
                            "supporting_evidence": ["missing-evidence"],
                        }
                    ],
                }
            raise AssertionError("invalid reviewer output must stop before adjudication")

        result = run_review_lifecycle(
            packet, initial=True, session_runner=invalid_runner
        )
        self.assertEqual(result["transition"]["status"], "human-handoff")
        self.assertEqual(result["human_handoff"]["candidate_identity"], candidate_identity(packet["candidate"]))
        self.assertEqual(result["human_handoff"]["finding_dispositions"], [])
        self.assertNotIn("missing-evidence", json.dumps(result))

    def test_provider_failure_becomes_bounded_handoff_without_raw_text(self):
        packet = semantic_packet()

        def failing_runner(role, payload, output_schema):
            raise ReviewSessionError("raw-provider-instruction")

        result = run_review_lifecycle(
            packet, initial=True, session_runner=failing_runner
        )
        self.assertEqual(result["transition"]["status"], "human-handoff")
        self.assertEqual(result["human_handoff"]["finding_dispositions"], [])
        self.assertNotIn("raw-provider-instruction", json.dumps(result))
        self.assertEqual(result["human_handoff"]["session_failure"]["role"], "reviewer")
        self.assertEqual(
            result["human_handoff"]["session_failure"]["failure_class"],
            "startup",
        )
        self.assertIsNone(result["human_handoff"]["session_failure"]["exit_status"])
        self.assertFalse(result["human_handoff"]["session_failure"]["output_exists"])

    def test_provider_failure_handoff_has_sanitized_machine_diagnostics(self):
        packet = semantic_packet()

        def run_case(*, returncode=None, output=None, timeout=False, auth=True):
            def fake_process(command, **kwargs):
                if output is not None:
                    Path(command[command.index("--output-last-message") + 1]).write_text(
                        output, encoding="utf-8"
                    )
                if timeout:
                    raise ProviderHangError("pre-turn startup")
                return returncode

            with tempfile.TemporaryDirectory() as directory:
                source_home = Path(directory) / "source-codex-home"
                source_home.mkdir()
                if auth:
                    (source_home / "auth.json").write_text(
                        '{"access_token":"sentinel"}', encoding="utf-8"
                    )
                with patch.dict(os.environ, {"CODEX_HOME": str(source_home)}), patch(
                    "tools.ci.adversarial_review_session._sandbox_path",
                    return_value="/usr/bin/sandbox-exec",
                ), patch(
                    "tools.ci.adversarial_review_session._run_provider_process",
                    side_effect=fake_process,
                ):
                    result = run_review_lifecycle(
                        packet, initial=True, codex_executable="/fake/codex"
                    )
            return result

        cases = [
            ("sandbox", run_case(returncode=23, auth=True)),
            ("authentication", run_case(returncode=23, auth=False)),
            ("timeout", run_case(timeout=True)),
            ("invalid-output", run_case(returncode=0, output="not-json")),
        ]
        for failure_class, result in cases:
            with self.subTest(failure_class=failure_class):
                diagnostic = result["human_handoff"]["session_failure"]
                self.assertEqual(diagnostic["schema"], SESSION_FAILURE_SCHEMA)
                self.assertEqual(diagnostic["role"], "reviewer")
                self.assertEqual(diagnostic["failure_class"], failure_class)
                self.assertNotIn("raw-secret", json.dumps(result))
                self.assertNotIn("sentinel", json.dumps(result))
                self.assertNotIn("BOUNDARY-PACKET", json.dumps(result))
                self.assertNotIn("pre-turn startup", json.dumps(result))
                if failure_class == "invalid-output":
                    self.assertEqual(diagnostic["validation_stage"], "parse")
                    self.assertEqual(diagnostic["diagnostic_code"], "output_json_parse")
                    self.assertIsNone(diagnostic["diagnostic_detail_code"])
                else:
                    self.assertIsNone(diagnostic["validation_stage"])
                    self.assertIsNone(diagnostic["diagnostic_code"])
                    self.assertIsNone(diagnostic["diagnostic_detail_code"])

    def test_provider_startup_failure_is_classified_without_raw_error_text(self):
        packet = semantic_packet()
        with patch(
            "tools.ci.adversarial_review_session._codex_path",
            side_effect=ReviewSessionError("raw-startup-detail"),
        ):
            result = run_review_lifecycle(
                packet, initial=True, codex_executable="/fake/codex"
            )
        diagnostic = result["human_handoff"]["session_failure"]
        self.assertEqual(diagnostic["role"], "reviewer")
        self.assertEqual(diagnostic["failure_class"], "startup")
        self.assertFalse(diagnostic["output_exists"])
        self.assertNotIn("raw-startup-detail", json.dumps(result))

    def test_adjudicator_failure_identifies_the_adjudicator_role(self):
        packet = semantic_packet()

        def failing_runner(role, payload, output_schema):
            if role == "reviewer":
                return review_result(payload, [])
            raise ReviewSessionError("raw-adjudicator-detail")

        result = run_review_lifecycle(
            packet, initial=True, session_runner=failing_runner
        )
        diagnostic = result["human_handoff"]["session_failure"]
        self.assertEqual(diagnostic["role"], "adjudicator")
        self.assertEqual(diagnostic["failure_class"], "startup")
        self.assertNotIn("raw-adjudicator-detail", json.dumps(result))


class ProviderOutputBoundaryTests(unittest.TestCase):
    def test_invalid_provider_event_encoding_is_bounded_at_process_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = [sys.executable, "-c", "import os; os.write(1, b'\\xff')"]
            with self.assertRaises(ProviderEventDecodeError):
                run_provider_process(
                    command,
                    cwd=root,
                    environment={"PATH": "/usr/bin:/bin"},
                    prompt="bounded packet",
                    startup_timeout_seconds=0.5,
                )

    def test_invalid_provider_stream_encoding_becomes_bounded_handoff(self):
        packet = semantic_packet()
        with patch(
            "tools.ci.adversarial_review_session._sandbox_path",
            return_value="/usr/bin/sandbox-exec",
        ), patch(
            "tools.ci.adversarial_review_session._run_provider_process",
            side_effect=ProviderEventDecodeError(),
        ):
            result = run_review_lifecycle(
                packet, initial=True, codex_executable="/fake/codex"
            )
        self.assertEqual(result["transition"]["status"], "human-handoff")
        self.assertEqual(result["human_handoff"]["candidate_identity"], candidate_identity(packet["candidate"]))
        diagnostic = result["human_handoff"]["session_failure"]
        self.assertEqual(diagnostic["failure_class"], "invalid-output")
        self.assertEqual(diagnostic["validation_stage"], "parse")
        self.assertEqual(diagnostic["diagnostic_code"], "output_event_stream_encoding")
        self.assertIsNone(diagnostic["diagnostic_detail_code"])
        self.assertNotIn("ProviderEventDecodeError", json.dumps(result))

    def test_raw_provider_streams_do_not_enter_session_errors(self):
        for stream in ("stdout", "stderr"):
            raw = "raw-provider-instruction-" + stream
            with self.subTest(stream=stream):
                with patch(
                    "tools.ci.adversarial_review_session._sandbox_path",
                    return_value="/usr/bin/sandbox-exec",
                ), patch(
                    "tools.ci.adversarial_review_session._run_provider_process",
                    return_value=23,
                ):
                    with self.assertRaises(ReviewSessionError) as raised:
                        _run_fresh_codex_session(
                            "reviewer", {}, {}, executable="/fake/codex"
                        )
                self.assertIn("exit status 23", str(raised.exception))
                self.assertNotIn(raw, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
