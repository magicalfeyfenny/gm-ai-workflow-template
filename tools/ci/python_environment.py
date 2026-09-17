"""Select a bounded Python environment for repository checks."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


MINIMUM_PYTHON = (3, 12)
DEFAULT_REQUIREMENTS = Path("tools/tests/requirements.txt")
PYTHON_VERSION_FILE = Path(".python-version")
_PINNED_REQUIREMENT = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*)==(?P<version>[^\s#;]+)$"
)


class EnvironmentSetupError(RuntimeError):
    """Raised when no usable check environment can be selected."""


@dataclass(frozen=True)
class InterpreterProbe:
    """Describe one interpreter without importing repository dependencies."""

    executable: Path
    version: tuple[int, int, int] | None
    isolated: bool
    missing_dependencies: tuple[str, ...] = ()
    wrong_dependencies: tuple[str, ...] = ()
    error: str | None = None

    @property
    def version_valid(self) -> bool:
        return self.version is not None and self.version >= MINIMUM_PYTHON

    @property
    def dependencies_valid(self) -> bool:
        return not self.missing_dependencies and not self.wrong_dependencies

    @property
    def usable(self) -> bool:
        return self.error is None and self.version_valid and self.dependencies_valid


@dataclass
class EnvironmentSelection:
    """The selected executable and the evidence for choosing it."""

    executable: Path
    route: str
    reason: str
    isolated: bool
    diagnostics: tuple[str, ...] = ()
    temporary_directory: tempfile.TemporaryDirectory[str] | None = None

    def cleanup(self) -> None:
        """Remove a temporary environment after the check has finished."""
        if self.temporary_directory is not None:
            self.temporary_directory.cleanup()
            self.temporary_directory = None

    def __enter__(self) -> "EnvironmentSelection":
        return self

    def __exit__(self, *_: object) -> None:
        self.cleanup()

    def evidence(self) -> str:
        """Return one stable, human-readable routing line."""
        return (
            "python-environment: "
            f"route={self.route} isolated={str(self.isolated).lower()} "
            f"interpreter={self.executable} reason={self.reason}"
        )


def _requirement_file(root: Path, requirements: Path | None) -> Path | None:
    if requirements is None:
        return None
    path = requirements if requirements.is_absolute() else root / requirements
    if not path.is_file():
        raise EnvironmentSetupError(
            f"pinned dependency file is missing: {path}"
        )
    return path.resolve()


def read_pinned_requirements(
    path: Path | None,
) -> tuple[tuple[str, str], ...]:
    """Read the repository's deliberately small exact-pin dependency contract."""
    if path is None:
        return ()

    requirements: list[tuple[str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise EnvironmentSetupError(
            f"cannot read pinned dependency file {path}: {exc}"
        ) from exc

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.split("#", maxsplit=1)[0].strip()
        if not line:
            continue
        match = _PINNED_REQUIREMENT.fullmatch(line)
        if match is None:
            raise EnvironmentSetupError(
                f"dependency file must contain exact pins; "
                f"unsupported line {path}:{line_number}"
            )
        requirements.append((match["name"], match["version"]))

    return tuple(requirements)


def _probe_script() -> str:
    return """
import importlib.metadata
import json
import sys

requirements = json.loads(sys.argv[1])
missing = []
wrong = []
for name, expected in requirements:
    try:
        actual = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        missing.append(f"{name}=={expected}")
    else:
        if actual != expected:
            wrong.append(f"{name}=={expected}; found {actual}")

print(json.dumps({
    "version": list(sys.version_info[:3]),
    "isolated": sys.prefix != sys.base_prefix or hasattr(sys, "real_prefix"),
    "missing": missing,
    "wrong": wrong,
}))
"""


def probe_interpreter(
    executable: Path,
    requirements: Iterable[tuple[str, str]] = (),
) -> InterpreterProbe:
    """Check version, isolation, and exact dependencies using the candidate."""
    command = [
        str(executable),
        "-c",
        _probe_script(),
        json.dumps(list(requirements)),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return InterpreterProbe(
            executable=executable,
            version=None,
            isolated=False,
            error=str(exc),
        )

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        return InterpreterProbe(
            executable=executable,
            version=None,
            isolated=False,
            error=detail or f"exit status {result.returncode}",
        )

    try:
        report = json.loads(result.stdout)
        version = tuple(int(value) for value in report["version"][:3])
        isolated = bool(report["isolated"])
        missing = tuple(str(value) for value in report["missing"])
        wrong = tuple(str(value) for value in report["wrong"])
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return InterpreterProbe(
            executable=executable,
            version=None,
            isolated=False,
            error=f"invalid interpreter probe: {exc}",
        )

    return InterpreterProbe(
        executable=executable,
        version=version,
        isolated=isolated,
        missing_dependencies=missing,
        wrong_dependencies=wrong,
    )


def _python_in_environment(directory: Path) -> Path:
    if os.name == "nt":
        return directory / "Scripts" / "python.exe"
    return directory / "bin" / "python"


def _resolve_interpreter(specification: str, root: Path) -> Path | None:
    value = specification.strip()
    if not value:
        return None
    if value.casefold() in {"system", "ambient"}:
        return Path(sys.executable)

    candidate = Path(value).expanduser()
    repository_candidate = root / candidate
    if candidate.parent == Path(".") and repository_candidate.exists():
        candidate = repository_candidate
    if candidate.is_absolute() or candidate.parent != Path("."):
        if not candidate.is_absolute():
            candidate = root / candidate
        if candidate.is_dir():
            candidate = _python_in_environment(candidate)
        return candidate

    command = value
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", value):
        command = f"python{value}"
    found = shutil.which(command)
    return Path(found) if found else None


def _explicit_specification(root: Path, override: str | None) -> str | None:
    if override is not None:
        return override
    configuration = root / PYTHON_VERSION_FILE
    if not configuration.is_file():
        return None
    try:
        lines = [
            line.strip()
            for line in configuration.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    except (OSError, UnicodeError) as exc:
        raise EnvironmentSetupError(
            f"cannot read explicit Python configuration {configuration}: {exc}"
        ) from exc
    if not lines:
        raise EnvironmentSetupError(
            f"explicit Python configuration is empty: {configuration}"
        )
    return lines[0]


def _probe_reason(probe: InterpreterProbe) -> str:
    if probe.error:
        return f"unusable: {probe.error}"
    if not probe.version_valid:
        version = "unknown" if probe.version is None else ".".join(map(str, probe.version))
        return f"requires Python 3.12 or later; found {version}"
    if probe.missing_dependencies:
        return "missing pinned dependencies: " + ", ".join(probe.missing_dependencies)
    if probe.wrong_dependencies:
        return "wrong pinned dependencies: " + ", ".join(probe.wrong_dependencies)
    return "usable"


def _install_requirements(
    executable: Path,
    requirements: Path,
    root: Path,
) -> str | None:
    """Install only the repository's pinned requirements into an isolated env."""
    try:
        result = subprocess.run(
            [
                str(executable),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-cache-dir",
                "--no-input",
                "-r",
                str(requirements),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    if result.returncode == 0:
        return None
    detail = result.stderr.strip() or result.stdout.strip()
    return detail or f"pip exited with status {result.returncode}"


def _creator(
    root: Path,
    explicit: Path | None,
) -> Path | None:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    versioned = shutil.which("python3.12")
    if versioned:
        candidates.append(Path(versioned))
    if sys.version_info[:2] >= MINIMUM_PYTHON:
        candidates.append(Path(sys.executable))

    checked: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in checked:
            continue
        checked.add(key)
        probe = probe_interpreter(candidate)
        if probe.version_valid:
            return candidate
    return None


def _create_temporary_environment(
    root: Path,
    requirements_path: Path,
    requirements: tuple[tuple[str, str], ...],
    creator: Path,
    diagnostics: tuple[str, ...],
) -> EnvironmentSelection:
    temporary = tempfile.TemporaryDirectory(prefix="workflow-python-")
    environment_root = Path(temporary.name) / "venv"
    try:
        try:
            result = subprocess.run(
                [str(creator), "-m", "venv", str(environment_root)],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise EnvironmentSetupError(
                f"could not create isolated Python environment: {exc}"
            ) from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise EnvironmentSetupError(
                "could not create isolated Python environment: "
                + (detail or f"venv exited with status {result.returncode}")
            )

        executable = _python_in_environment(environment_root)
        install_error = _install_requirements(executable, requirements_path, root)
        if install_error is not None:
            raise EnvironmentSetupError(
                f"could not install pinned dependencies in isolated environment: "
                f"{install_error}"
            )
        probe = probe_interpreter(executable, requirements)
        if not probe.usable or not probe.isolated:
            raise EnvironmentSetupError(
                "new isolated environment failed validation: "
                + _probe_reason(probe)
            )
    except Exception:
        temporary.cleanup()
        raise

    return EnvironmentSelection(
        executable=executable,
        route="temporary-isolated",
        reason="created bounded Python environment after repository candidates failed",
        isolated=True,
        diagnostics=diagnostics,
        temporary_directory=temporary,
    )


def select_environment(
    root: Path,
    *,
    requirements: Path | None = DEFAULT_REQUIREMENTS,
    explicit_interpreter: str | None = None,
    allow_ambient: bool = False,
) -> EnvironmentSelection:
    """Select explicit, repo-local, temporary, or explicitly allowed ambient Python."""
    root = root.resolve()
    requirements_path = _requirement_file(root, requirements)
    pinned = read_pinned_requirements(requirements_path)
    diagnostics: list[str] = []
    explicit_spec = _explicit_specification(root, explicit_interpreter)
    explicit_path: Path | None = None

    if explicit_spec is not None:
        explicit_path = _resolve_interpreter(explicit_spec, root)
        if explicit_path is None:
            diagnostics.append(
                f"explicit interpreter {explicit_spec!r} is not available"
            )
        else:
            probe = probe_interpreter(explicit_path, pinned)
            if explicit_spec.casefold() in {"system", "ambient"}:
                if not probe.version_valid:
                    raise EnvironmentSetupError(
                        "explicit ambient interpreter is unusable: "
                        + _probe_reason(probe)
                    )
                return EnvironmentSelection(
                    executable=explicit_path,
                    route="explicit-ambient",
                    reason="repository explicitly permits the ambient interpreter",
                    isolated=probe.isolated,
                    diagnostics=tuple(diagnostics),
                )
            if probe.usable:
                return EnvironmentSelection(
                    executable=explicit_path,
                    route="explicit",
                    reason=f"selected from explicit repository interpreter {explicit_spec}",
                    isolated=probe.isolated,
                    diagnostics=tuple(diagnostics),
                )
            if probe.version_valid and probe.isolated and requirements_path is not None:
                repair_error = _install_requirements(
                    explicit_path, requirements_path, root
                )
                if repair_error is None:
                    repaired = probe_interpreter(explicit_path, pinned)
                    if repaired.usable and repaired.isolated:
                        return EnvironmentSelection(
                            executable=explicit_path,
                            route="explicit-repaired",
                            reason=(
                                "repaired the explicitly identified isolated "
                                "environment to satisfy pinned dependencies"
                            ),
                            isolated=True,
                            diagnostics=tuple(diagnostics),
                        )
                    diagnostics.append(
                        "explicit environment remained invalid after repair: "
                        + _probe_reason(repaired)
                    )
                else:
                    diagnostics.append(
                        f"explicit environment repair failed: {repair_error}"
                    )
            diagnostics.append(
                f"explicit interpreter {explicit_spec!r}: {_probe_reason(probe)}"
            )

    local_environment = root / ".venv"
    local_executable = _python_in_environment(local_environment)
    if local_executable.is_file():
        probe = probe_interpreter(local_executable, pinned)
        if probe.usable and probe.isolated:
            return EnvironmentSelection(
                executable=local_executable,
                route="repo-local",
                reason="selected validated .venv with the pinned dependency contract",
                isolated=probe.isolated,
                diagnostics=tuple(diagnostics),
            )
        if probe.version_valid and probe.isolated and requirements_path is not None:
            repair_error = _install_requirements(local_executable, requirements_path, root)
            if repair_error is None:
                repaired = probe_interpreter(local_executable, pinned)
                if repaired.usable and repaired.isolated:
                    return EnvironmentSelection(
                        executable=local_executable,
                        route="repo-local-repaired",
                        reason="repaired .venv to satisfy the pinned dependency contract",
                        isolated=True,
                        diagnostics=tuple(diagnostics),
                    )
                diagnostics.append(
                    f".venv remained invalid after repair: {_probe_reason(repaired)}"
                )
            else:
                diagnostics.append(f".venv repair failed: {repair_error}")
        else:
            diagnostics.append(f".venv: {_probe_reason(probe)}")

    if requirements_path is None:
        ambient = probe_interpreter(Path(sys.executable))
        if ambient.version_valid:
            return EnvironmentSelection(
                executable=Path(sys.executable),
                route="ambient-no-dependencies",
                reason="no pinned dependency contract applies to this check",
                isolated=ambient.isolated,
                diagnostics=tuple(diagnostics),
            )
        diagnostics.append(f"ambient interpreter: {_probe_reason(ambient)}")

    creator = _creator(root, explicit_path)
    if creator is not None and requirements_path is not None:
        try:
            return _create_temporary_environment(
                root,
                requirements_path,
                pinned,
                creator,
                tuple(diagnostics),
            )
        except EnvironmentSetupError as exc:
            diagnostics.append(str(exc))
    elif requirements_path is not None:
        diagnostics.append("no Python 3.12-or-later creator is available")

    if allow_ambient:
        ambient = probe_interpreter(Path(sys.executable), pinned)
        if ambient.version_valid:
            return EnvironmentSelection(
                executable=Path(sys.executable),
                route="ambient-fallback",
                reason="isolated routing was unavailable and ambient fallback was explicitly allowed",
                isolated=ambient.isolated,
                diagnostics=tuple(diagnostics),
            )
        diagnostics.append(f"ambient fallback: {_probe_reason(ambient)}")

    detail = "; ".join(diagnostics) or "no candidate was found"
    raise EnvironmentSetupError(
        "no usable Python environment for dependency-sensitive repository checks: "
        + detail
    )
