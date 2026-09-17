"""Check bounded Python routing without invoking repository dependencies."""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.ci import python_environment as environment
from tools.ci.run_repository_checks import main as run_repository_checks_main
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
        version: tuple[int, int, int] = (3, 12, 1),
        isolated: bool = True,
        missing: tuple[str, ...] = (),
        wrong: tuple[str, ...] = (),
    ) -> environment.InterpreterProbe:
        return environment.InterpreterProbe(
            executable=executable,
            version=version,
            isolated=isolated,
            missing_dependencies=missing,
            wrong_dependencies=wrong,
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
        probe.assert_called_once_with(Path(sys.executable), ())

    def test_explicit_system_missing_dependency_is_setup_failure_without_system_install(self):
        (self.root / ".python-version").write_text("system\n", encoding="utf-8")
        ambient = self.probe(
            Path(sys.executable), isolated=False, missing=("PyYAML==6.0.3",)
        )
        with patch.object(
            environment, "probe_interpreter", return_value=ambient
        ), patch.object(environment, "_creator", return_value=None), patch.object(
            environment, "_install_requirements"
        ) as install:
            with self.assertRaisesRegex(
                environment.EnvironmentSetupError,
                "missing pinned dependencies",
            ):
                environment.select_environment(
                    self.root, requirements=self.requirements
                )

        install.assert_not_called()

    def test_ambient_python_with_valid_pins_is_selected_before_creation(self):
        ambient = self.probe(
            Path(sys.executable),
            version=(3, 13, 2),
            isolated=False,
        )
        with patch.object(
            environment, "probe_interpreter", return_value=ambient
        ) as probe, patch.object(environment, "_creator") as creator:
            selected = environment.select_environment(
                self.root, requirements=self.requirements
            )

        self.assertEqual(selected.route, "ambient")
        self.assertEqual(selected.executable, Path(sys.executable))
        self.assertIn("pinned dependency contract", selected.reason)
        creator.assert_not_called()
        probe.assert_called_once_with(
            Path(sys.executable), (("PyYAML", "6.0.3"),)
        )

    def test_python_313_is_accepted_as_bounded_creation_base(self):
        creator_path = self.root / "python3.13"
        ambient = self.probe(
            Path(sys.executable),
            version=(3, 13, 2),
            isolated=False,
            missing=("PyYAML==6.0.3",),
        )
        creator_probe = self.probe(
            creator_path,
            version=(3, 13, 2),
            isolated=False,
        )
        temporary_selection = environment.EnvironmentSelection(
            executable=self.root / "temporary/bin/python",
            route="temporary-isolated",
            reason="fixture",
            isolated=True,
        )
        with patch.object(
            environment,
            "probe_interpreter",
            side_effect=(ambient, creator_probe),
        ), patch.object(
            environment.shutil, "which", return_value=str(creator_path)
        ) as which, patch.object(
            environment,
            "_create_temporary_environment",
            return_value=temporary_selection,
        ) as create:
            selected = environment.select_environment(
                self.root, requirements=self.requirements
            )

        self.assertIs(selected, temporary_selection)
        self.assertEqual(create.call_args.args[3], creator_path)
        which.assert_called_once_with("python3")

    def test_ambient_missing_pins_is_setup_failure_without_a_project_check(self):
        ambient = self.probe(
            Path(sys.executable),
            version=(3, 13, 2),
            isolated=False,
            missing=("PyYAML==6.0.3",),
        )
        with patch.object(
            environment, "probe_interpreter", return_value=ambient
        ), patch.object(environment, "_creator", return_value=None), patch.object(
            environment, "_install_requirements"
        ) as install:
            with self.assertRaisesRegex(
                environment.EnvironmentSetupError,
                "ambient interpreter: missing pinned dependencies",
            ):
                environment.select_environment(
                    self.root, requirements=self.requirements
                )

        install.assert_not_called()

    def test_setup_failure_is_reported_separately_from_project_check_failure(self):
        setup_error = environment.EnvironmentSetupError(
            "ambient interpreter: missing pinned dependencies: PyYAML==6.0.3"
        )
        with patch(
            "tools.ci.run_repository_checks.select_environment",
            side_effect=setup_error,
        ), patch("tools.ci.run_repository_checks._run_check") as check, patch(
            "sys.stderr", new_callable=io.StringIO
        ) as stderr:
            result = run_repository_checks_main(
                ["--root", str(self.root), "tests"]
            )

        self.assertEqual(result, 2)
        self.assertIn("python-environment: setup failed", stderr.getvalue())
        check.assert_not_called()

    def test_temporary_environment_creation_is_isolated_and_executable(self):
        empty_requirements = self.root / "empty-requirements.txt"
        empty_requirements.write_text("", encoding="utf-8")

        with environment._create_temporary_environment(
            self.root,
            empty_requirements,
            (),
            Path(sys.executable),
            (),
        ) as selected:
            completed = subprocess.run(
                [
                    str(selected.executable),
                    "-c",
                    "import sys; raise SystemExit(sys.prefix == sys.base_prefix)",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(selected.route, "temporary-isolated")
        self.assertTrue(selected.isolated)
        self.assertEqual(completed.returncode, 0)

    def test_repaired_environment_runs_dependency_sensitive_check(self):
        local = self.make_local_python()
        invalid = self.probe(local, missing=("PyYAML==6.0.3",))
        repaired = self.probe(local)
        completed = subprocess.CompletedProcess([], 0, "", "")
        with patch.object(
            environment,
            "probe_interpreter",
            side_effect=(invalid, repaired),
        ), patch.object(
            environment, "_install_requirements", return_value=None
        ) as install, patch(
            "tools.ci.run_repository_checks.subprocess.run",
            return_value=completed,
        ) as runner:
            result = run_checks(
                "tests", root=self.root, requirements=self.requirements
            )

        self.assertEqual(result, 0)
        install.assert_called_once_with(
            local.resolve(), self.requirements.resolve(), self.root.resolve()
        )
        self.assertEqual(runner.call_args.args[0][0], str(local.resolve()))

    def test_temporary_creation_failure_is_an_environment_setup_failure(self):
        ambient = self.probe(
            Path(sys.executable),
            isolated=False,
            missing=("PyYAML==6.0.3",),
        )
        with patch.object(
            environment, "probe_interpreter", return_value=ambient
        ), patch.object(
            environment, "_creator", return_value=Path("/python3")
        ), patch.object(
            environment,
            "_create_temporary_environment",
            side_effect=environment.EnvironmentSetupError(
                "could not create isolated Python environment: venv unavailable"
            ),
        ):
            with self.assertRaisesRegex(
                environment.EnvironmentSetupError,
                "could not create isolated Python environment",
            ):
                environment.select_environment(
                    self.root, requirements=self.requirements
                )

    def test_local_repair_failure_is_an_environment_setup_failure(self):
        local = self.make_local_python()
        invalid_local = self.probe(local, missing=("PyYAML==6.0.3",))
        invalid_ambient = self.probe(
            Path(sys.executable),
            isolated=False,
            missing=("PyYAML==6.0.3",),
        )
        with patch.object(
            environment,
            "probe_interpreter",
            side_effect=(invalid_local, invalid_ambient),
        ), patch.object(
            environment,
            "_install_requirements",
            return_value="pip unavailable",
        ) as install, patch.object(
            environment, "_creator", return_value=None
        ):
            with self.assertRaisesRegex(
                environment.EnvironmentSetupError,
                ".venv repair failed",
            ):
                environment.select_environment(
                    self.root, requirements=self.requirements
                )

        install.assert_called_once_with(
            local.resolve(), self.requirements.resolve(), self.root.resolve()
        )

    def test_isolated_setup_failure_is_distinct_without_ambient_permission(self):
        ambient = self.probe(
            Path(sys.executable),
            isolated=False,
            missing=("PyYAML==6.0.3",),
        )
        with patch.object(
            environment, "probe_interpreter", return_value=ambient
        ), patch.object(environment, "_creator", return_value=None):
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
