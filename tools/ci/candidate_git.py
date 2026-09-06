"""Read one stored Git candidate without checkout filters or ambient Git rules."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


@dataclass(frozen=True)
class GitEntry:
    """Keep stored object identity and size separate from materialized files."""

    mode: str
    oid: str
    size: int | None


def git_environment() -> dict[str, str]:
    """Exclude caller Git overrides and machine-wide attributes and settings."""
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_ATTR_NOSYSTEM="1",
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_OPTIONAL_LOCKS="0",
        GIT_LFS_SKIP_SMUDGE="1",
    )
    return environment


def _git_command(*arguments: str) -> list[str]:
    """Apply the same deterministic rule and hook settings to every Git read."""
    return [
        "git",
        "-c", "core.attributesFile=" + os.devnull,
        "-c", "core.excludesFile=" + os.devnull,
        "-c", "core.hooksPath=" + os.devnull,
        "-c", "core.fsmonitor=false",
        "-c", "core.ignoreCase=false",
        *arguments,
    ]


def _git(
    root: Path,
    *arguments: str,
    environment: dict[str, str],
    data: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    """Run a bounded Git command with binary, NUL-safe input and output."""
    return subprocess.run(
        _git_command(*arguments), cwd=root, env=environment, input=data,
        capture_output=True, check=check,
    )


def _initialize(root: Path, object_format: str, environment: dict[str, str]) -> None:
    """Create an empty repository without templates, copied config, or hooks."""
    root.mkdir()
    _git(
        root, "init", "--quiet", "--template=", f"--object-format={object_format}",
        environment=environment,
    )


def _safe_path(root: Path, path: str) -> Path:
    """Reject tree paths that could escape or overwrite snapshot Git metadata."""
    relative = Path(path)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} or part.casefold() == ".git"
        for part in path.split("/")
    ):
        raise ValueError(f"unsafe Git candidate path: {path!r}")
    return root / relative


def _entries(
    root: Path, tree: str, environment: dict[str, str],
) -> dict[str, GitEntry]:
    """Read blob sizes without loading their contents or walking branch history."""
    result = _git(
        root, "ls-tree", "-r", "--full-tree", "--long", "-z", tree,
        environment=environment,
    )
    entries = {}
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, kind, oid, size = metadata.split()
        path = os.fsdecode(raw_path)
        _safe_path(root, path)
        entries[path] = GitEntry(
            mode.decode("ascii"), oid.decode("ascii"),
            int(size) if kind == b"blob" else None,
        )
    return entries


def _materialize(
    root: Path, entries: dict[str, GitEntry], environment: dict[str, str],
) -> None:
    """Stream raw blobs, representing symlinks by stored target bytes safely."""
    process = subprocess.Popen(
        _git_command("cat-file", "--batch"), cwd=root, env=environment,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    try:
        for path, entry in entries.items():
            if entry.size is None:
                continue
            target = _safe_path(root, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            process.stdin.write(entry.oid.encode("ascii") + b"\n")
            process.stdin.flush()
            header = process.stdout.readline().split()
            expected = [entry.oid.encode("ascii"), b"blob", str(entry.size).encode()]
            if header != expected:
                raise ValueError(f"cannot read candidate blob {path!r}: {header!r}")
            with target.open("xb") as output:
                remaining = entry.size
                while remaining:
                    chunk = process.stdout.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        raise ValueError(f"truncated candidate blob: {path!r}")
                    output.write(chunk)
                    remaining -= len(chunk)
            if process.stdout.read(1) != b"\n":
                raise ValueError(f"invalid candidate blob boundary: {path!r}")
            target.chmod(0o755 if entry.mode == "100755" else 0o644)
        process.stdin.close()
        error = process.stderr.read() if process.stderr is not None else b""
        if process.wait():
            raise ValueError(f"candidate blob materialization failed: {error!r}")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
        if not process.stdin.closed:
            process.stdin.close()
        if process.stderr is not None:
            process.stderr.close()


@dataclass
class GitCandidate:
    """Expose stored objects and Git rule matching for exactly one candidate."""

    root: Path
    tree: str
    entries: dict[str, GitEntry]
    environment: dict[str, str]
    _ignore_root: Path
    _object_format: str

    def read_blob(self, path: str, limit: int | None = None) -> bytes:
        """Read stored bytes or a bounded prefix, including symlink target bytes."""
        entry = self.entries[path]
        if entry.size is None:
            raise ValueError(f"candidate path is not a blob: {path!r}")
        if limit is not None and limit < 0:
            raise ValueError("blob prefix limit must be nonnegative")
        # Only this module writes the raw snapshot; no link targets are followed.
        with _safe_path(self.root, path).open("rb") as source:
            return source.read(-1 if limit is None else limit)

    def attributes(
        self, paths: Iterable[str], names: Iterable[str],
    ) -> dict[str, dict[str, str]]:
        """Resolve nested attributes and macros exclusively from the stored index."""
        paths, names = list(paths), list(names)
        values: dict[str, dict[str, str]] = {path: {} for path in paths}
        if not paths or not names:
            return values
        result = _git(
            self.root, "check-attr", "--cached", "-z", "--stdin", *names,
            environment=self.environment,
            data=b"".join(os.fsencode(path) + b"\0" for path in paths),
        )
        fields = result.stdout.split(b"\0")[:-1]
        for offset in range(0, len(fields), 3):
            path, name, value = map(os.fsdecode, fields[offset:offset + 3])
            values[path][name] = value
        return values

    def _ignored_by(self, root: Path, paths: Iterable[str]) -> set[str]:
        """Ask Git for ignored paths, allowing an empty match result."""
        paths = list(paths)
        if not paths:
            return set()
        result = _git(
            root, "check-ignore", "--no-index", "-z", "--stdin",
            environment=self.environment,
            data=b"".join(os.fsencode(path) + b"\0" for path in paths), check=False,
        )
        if result.returncode not in {0, 1}:
            raise subprocess.CalledProcessError(
                result.returncode, result.args, result.stdout, result.stderr,
            )
        return {os.fsdecode(path) for path in result.stdout.split(b"\0") if path}

    def ignored(self, paths: Iterable[str]) -> set[str]:
        """Evaluate only regular tracked ignore files, excluding machine rules."""
        return self._ignored_by(self._ignore_root, paths)

    def match_patterns(self, paths: Iterable[str], patterns: Iterable[str]) -> set[str]:
        """Apply policy patterns with Git semantics independently of tracked ignores."""
        with tempfile.TemporaryDirectory(prefix="candidate-patterns-") as temporary:
            root = Path(temporary) / "rules"
            _initialize(root, self._object_format, self.environment)
            (root / ".gitignore").write_text("\n".join(patterns) + "\n", encoding="utf-8")
            return self._ignored_by(root, paths)


@contextmanager
def candidate_snapshot(root: Path, ref: str | None = None) -> Iterator[GitCandidate]:
    """Capture the index or an explicit tree without modifying the source checkout."""
    root = root.resolve()
    environment = git_environment()
    tree_arguments = ("write-tree",) if ref is None else (
        "rev-parse", "--verify", "--end-of-options", f"{ref}^{{tree}}",
    )
    tree = _git(root, *tree_arguments, environment=environment).stdout.decode().strip()
    object_format = _git(
        root, "rev-parse", "--show-object-format", environment=environment,
    ).stdout.decode().strip()
    objects = os.fsdecode(_git(
        root, "rev-parse", "--path-format=absolute", "--git-path", "objects",
        environment=environment,
    ).stdout).strip()
    if "\n" in objects or "\r" in objects:
        raise ValueError("Git object directories containing newlines are unsupported")
    with tempfile.TemporaryDirectory(prefix="git-candidate-") as temporary:
        checkout = Path(temporary) / "candidate"
        _initialize(checkout, object_format, environment)
        # A plain absolute line also works with Git LFS's native object scanner.
        # Spaces are literal here; its parser does not support Git's C quoting.
        (checkout / ".git/objects/info/alternates").write_text(
            objects + "\n", encoding="utf-8",
        )
        _git(checkout, "read-tree", tree, environment=environment)
        entries = _entries(checkout, tree, environment)
        _materialize(checkout, entries, environment)
        ignore_root = Path(temporary) / "ignores"
        _initialize(ignore_root, object_format, environment)
        candidate = GitCandidate(
            checkout, tree, entries, environment, ignore_root, object_format,
        )
        for path, entry in entries.items():
            if Path(path).name == ".gitignore" and entry.mode in {"100644", "100755"}:
                target = _safe_path(ignore_root, path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(candidate.read_blob(path))
        yield candidate


def parse_lfs_pointer(text: str) -> dict[str, int | str] | None:
    """Parse canonical stored LFS v1 pointers, including ordered extension records."""
    if len(text.encode("utf-8")) >= 1024:
        return None
    match = re.fullmatch(
        r"version https://git-lfs.github.com/spec/v1\n"
        r"(?P<extensions>(?:ext-(?:0|[1-9][0-9]*)-[a-z0-9.-]+ "
        r"sha256:[0-9a-f]{64}\n)*)"
        r"oid sha256:(?P<oid>[0-9a-f]{64})\n"
        r"size (?P<size>0|[1-9][0-9]*)\n",
        text,
    )
    if match is None:
        return None
    keys = [line.split(" ", 1)[0] for line in match["extensions"].splitlines()]
    priorities = [key.split("-", 2)[1] for key in keys]
    if keys != sorted(keys) or len(priorities) != len(set(priorities)):
        return None
    return {"oid": match["oid"], "size": int(match["size"])}


def is_lfs_pointer(text: str) -> bool:
    """Recognize pointer content through the same parser used for object integrity."""
    return parse_lfs_pointer(text) is not None
