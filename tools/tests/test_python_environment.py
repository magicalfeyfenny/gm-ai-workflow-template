"""Check bounded Python routing without invoking repository dependencies."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.ci import python_environment as environment
from tools.ci.run_repository_checks import run_checks


class PythonEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.requirements = self.root / "requirements.txt"
        self.requirements.write_text("PyYAML==6.0.3\n", encoding="utf-8")

    @staticmethod
    def probe(
        executable: Path,
        *,
        isolated: bool = True,
        missing: tuple[str, ...] = (),
    ) -> environment.InterpreterProbe:
        return environment.InterpreterProbe(
            executable=executable,
            version=(3, 12, 1),
            isolated=isolated,
            missing_dependencies=missing,
        )

    def make_local_python(self) -> Path:
        executable = self.root / ".venv/bin/python"
        executable.parent.mkdir(parents=True)
        executable.touch()
        return executable

    def test_explicit_repository_interpreter_precedes_local_candidate(self):
        explicit = self.root / "python-explicit"
        explicit.touch()
        self.make_local_python()
        (self.root / ".python-version").write_text(
            str(explicit), encoding="utf-8"
        )

        with patch.object(
            environment,
            "probe_interpreter",
            return_value=self.probe(explicit, isolated=False),
        ) as probe:
            selected = environment.select_environment(
                self.root, requirements=self.requirements
            )

        self.assertEqual(selected.route, "explicit")
        self.assertEqual(selected.executable, explicit)
        probe.assert_called_once_with(explicit, (("PyYAML", "6.0.3"),))

    def test_valid_repo_local_environment_is_selected_without_ambient_probe(self):
        local = self.make_local_python()

        with patch.object(
            environment,
            "probe_interpreter",
            return_value=self.probe(local),
        ) as probe, patch.object(environment, "_creator") as creator:
            selected = environment.select_environment(
                self.root, requirements=self.requirements
            )

        self.assertEqual(selected.route, "repo-local")
        self.assertEqual(selected.executable, local.resolve())
        creator.assert_not_called()
        probe.assert_called_once_with(local.resolve(), (("PyYAML", "6.0.3"),))

    def test_invalid_explicit_candidate_falls_back_to_valid_local_candidate(self):
        explicit = self.root / "python-explicit"
        explicit.touch()
        local = self.make_local_python()
        (self.root / ".python-version").write_text(
            str(explicit), encoding="utf-8"
        )
        invalid = self.probe(explicit, isolated=False, missing=("PyYAML==6.0.3",))

        with patch.object(
            environment,
            "probe_interpreter",
            side_effect=(invalid, self.probe(local)),
        ):
            selected = environment.select_environment(
                self.root, requirements=self.requirements
            )

        self.assertEqual(selected.route, "repo-local")
        self.assertEqual(selected.executable, local.resolve())
        self.assertIn("explicit interpreter", " ".join(selected.diagnostics))

    def test_missing_dependency_repairs_isolated_local_environment(self):
        local = self.make_local_python()
        invalid = self.probe(local, missing=("PyYAML==6.0.3",))

        with patch.object(
            environment,
            "probe_interpreter",
            side_effect=(invalid, self.probe(local)),
        ), patch.object(
            environment, "_install_requirements", return_value=None
        ) as install:
            selected = environment.select_environment(
                self.root, requirements=self.requirements
            )

        self.assertEqual(selected.route, "repo-local-repaired")
        install.assert_called_once_with(
            local.resolve(), self.requirements.resolve(), self.root.resolve()
        )

    def test_no_dependency_contract_allows_ambient_fallback(self):
        ambient = self.probe(Path(sys.executable), isolated=False)
        with patch.object(
            environment,
            "probe_interpreter",
            return_value=ambient,
        ) as probe:
            selected = environment.select_environment(
                self.root, requirements=None
            )

        self.assertEqual(selected.route, "ambient-no-dependencies")
        self.assertEqual(selected.executable, Path(sys.executable))
        probe.assert_called_once_with(Path(sys.executable))

    def test_explicit_system_route_remains_allowed_even_with_missing_dependency(self):
        (self.root / ".python-version").write_text("system\n", encoding="utf-8")
        ambient = self.probe(
            Path(sys.executable), isolated=False, missing=("PyYAML==6.0.3",)
        )
        with patch.object(environment, "probe_interpreter", return_value=ambient):
            selected = environment.select_environment(
                self.root, requirements=self.requirements
            )

        self.assertEqual(selected.route, "explicit-ambient")
        self.assertIn("explicitly permits", selected.reason)

    def test_isolated_setup_failure_is_distinct_without_ambient_permission(self):
        with patch.object(environment, "_creator", return_value=None):
            with self.assertRaisesRegex(
                environment.EnvironmentSetupError,
                "no usable Python environment",
            ):
                environment.select_environment(
                    self.root, requirements=self.requirements
                )

    def test_router_passes_selected_interpreter_to_the_check(self):
        selected = environment.EnvironmentSelection(
            executable=Path("/isolated/bin/python"),
            route="repo-local",
            reason="fixture",
            isolated=True,
        )
        completed = subprocess.CompletedProcess([], 0, "", "")
        with patch(
            "tools.ci.run_repository_checks.select_environment",
            return_value=selected,
        ), patch(
            "tools.ci.run_repository_checks.subprocess.run",
            return_value=completed,
        ) as runner:
            result = run_checks(
                "tests", root=self.root, requirements=None
            )

        self.assertEqual(result, 0)
        self.assertEqual(
            runner.call_args.args[0][0], "/isolated/bin/python"
        )


if __name__ == "__main__":
    unittest.main()
