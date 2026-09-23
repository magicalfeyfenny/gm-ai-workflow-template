"""Build the narrow macOS Seatbelt boundary for isolated review sessions."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


_RUNTIME_FRAMEWORKS = (
    Path("/System/Library/Frameworks/AppKit.framework"),
    Path("/System/Library/Frameworks/CFNetwork.framework"),
    Path("/System/Library/Frameworks/CoreFoundation.framework"),
    Path("/System/Library/Frameworks/CoreGraphics.framework"),
    Path("/System/Library/Frameworks/CoreServices.framework"),
    Path("/System/Library/Frameworks/Foundation.framework"),
    Path("/System/Library/Frameworks/IOKit.framework"),
    Path("/System/Library/Frameworks/LocalAuthentication.framework"),
    Path("/System/Library/Frameworks/Security.framework"),
    Path("/System/Library/Frameworks/SystemConfiguration.framework"),
)
_RUNTIME_FILES = (
    Path("/bin/bash"),
    Path("/bin/cat"),
    Path("/bin/sh"),
    Path("/usr/bin/git"),
    Path("/usr/bin/grep"),
    Path("/usr/bin/sed"),
    Path("/usr/lib/dyld"),
    Path("/usr/lib/libSystem.B.dylib"),
    Path("/usr/lib/libobjc.A.dylib"),
    Path("/usr/lib/libbz2.1.0.dylib"),
    Path("/usr/lib/libiconv.2.dylib"),
    Path("/usr/lib/liblzma.5.dylib"),
)


def _sbpl_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "\\\\").replace('"', '\\"')


def _session_environment(
    working_directory: Path, auth_directory: Path, runtime_directory: Path
) -> tuple[dict[str, str], Path]:
    configured_home = os.environ.get("CODEX_HOME")
    source_home = (
        Path(configured_home).expanduser().resolve()
        if configured_home
        else Path.home().joinpath(".codex").resolve()
    )
    codex_home = runtime_directory.joinpath("codex-home").resolve()
    codex_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    auth_root = auth_directory.resolve()
    auth_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    source_auth = source_home / "auth.json"
    if source_auth.is_file():
        target_auth = auth_root / "auth.json"
        shutil.copyfile(source_auth, target_auth)
        target_auth.chmod(0o400)
        codex_home.joinpath("auth.json").symlink_to(target_auth)
    environment = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(codex_home),
        "TMPDIR": str(codex_home),
        "CODEX_HOME": str(codex_home),
        "LANG": os.environ.get("LANG", "C"),
        "LC_CTYPE": os.environ.get("LC_CTYPE", "C"),
    }
    return environment, codex_home


def _write_sandbox_profile(
    path: Path,
    working_directory: Path,
    command_path: Path,
    codex_home: Path,
    *,
    authentication_path: Path | None = None,
) -> None:
    lines = [
        "(version 1)",
        "(deny default)",
        '(import "system.sb")',
        "(allow ipc-posix*)",
        "(allow socket-ioctl)",
        "(allow socket-option*)",
        "(allow syscall*)",
        "(allow system-fcntl)",
        "(allow system-mac-syscall)",
        "(allow system-socket)",
        "(allow mach-lookup)",
        "(allow darwin-notification-post)",
        "(allow signal (target self))",
        "(allow network-outbound)",
    ]
    for root in _RUNTIME_FRAMEWORKS:
        encoded = _sbpl_path(root)
        lines.append(f'(allow file-read* (subpath "{encoded}"))')
        lines.append(f'(allow file-map-executable (subpath "{encoded}"))')
    for runtime_file in (command_path, *_RUNTIME_FILES):
        encoded = _sbpl_path(runtime_file)
        lines.append(f'(allow file-read* (literal "{encoded}"))')
        lines.append(f'(allow file-map-executable (literal "{encoded}"))')
        lines.append(
            f'(allow file-read-metadata file-test-existence (path-ancestors "{encoded}"))'
        )
    lines.append(f'(allow process-exec (literal "{_sbpl_path(command_path)}"))')
    try:
        first_line = command_path.read_bytes().splitlines()[0].decode("utf-8")
    except (OSError, IndexError, UnicodeDecodeError):
        first_line = ""
    if first_line.startswith("#!"):
        interpreter = first_line[2:].strip().split(maxsplit=1)[0]
        if interpreter.startswith("/"):
            lines.append(
                f'(allow process-exec (literal "{_sbpl_path(Path(interpreter))}"))'
            )
    workspace = _sbpl_path(working_directory)
    lines.append(
        f'(allow file-read-metadata file-test-existence (path-ancestors "{workspace}"))'
    )
    lines.append(f'(allow file-read* (subpath "{workspace}"))')
    if codex_home.is_dir():
        encoded_home = _sbpl_path(codex_home)
        lines.append(
            f'(allow file-read-metadata file-test-existence (path-ancestors "{encoded_home}"))'
        )
        lines.append(f'(allow file-read* file-write* (subpath "{encoded_home}"))')
        runtime_auth_path = codex_home / "auth.json"
        if runtime_auth_path.is_file():
            lines.append(
                f'(allow file-read* (literal "{_sbpl_path(runtime_auth_path)}"))'
            )
            lines.append(
                f'(deny file-write* (literal "{_sbpl_path(runtime_auth_path)}"))'
            )
    if authentication_path is not None and authentication_path.is_file():
        encoded_auth = _sbpl_path(authentication_path)
        lines.append(
            f'(allow file-read-metadata file-test-existence (path-ancestors "{encoded_auth}"))'
        )
        lines.append(f'(allow file-read* (literal "{encoded_auth}"))')
        lines.append(f'(deny file-write* (literal "{encoded_auth}"))')
    lines.extend(
        [
            '(allow file-read* (literal "/private/etc/ssl/cert.pem"))',
            '(allow file-read* (literal "/private/etc/hosts"))',
            '(allow file-read* (literal "/private/etc/resolv.conf"))',
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
