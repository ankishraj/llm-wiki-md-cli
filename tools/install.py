#!/usr/bin/env python3
"""Add this repo's `bin/` directory to the user's PATH so `wiki` is callable
from anywhere — no need to tell agents where the wiki-project root is.

Only `bin/` goes on PATH; it contains just the launchers (`wiki`, `wiki.cmd`,
`wiki.ps1`), which resolve back to `tools/wiki.pyz`. Build artefacts, sources
and hooks stay out of PATH.

Usage:
    python3 tools/install.py              # detect shell, update its rc file
    python3 tools/install.py --shell bash # force a target
    python3 tools/install.py --print-only # just print what to add, change nothing

Idempotent: re-running does not duplicate the entry. Open a new shell (or
source the rc file) afterwards.
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
from pathlib import Path

MARKER = "# >>> project-wiki bin >>>"
MARKER_END = "# <<< project-wiki bin <<<"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def bin_dir() -> Path:
    return repo_root() / "bin"


def _posix_block(bindir: Path) -> str:
    return (
        f"\n{MARKER}\n"
        f'export PATH="{bindir}:$PATH"\n'
        f"{MARKER_END}\n"
    )


def _already_present(text: str) -> bool:
    return MARKER in text


def _rc_for_shell(shell: str) -> Path | None:
    home = Path.home()
    if shell in ("bash",):
        # Prefer .bashrc; on WSL this is the common interactive rc.
        return home / ".bashrc"
    if shell in ("zsh",):
        return home / ".zshrc"
    return None


def _detect_shell() -> str:
    if platform.system() == "Windows":
        return "powershell"
    shell_env = os.environ.get("SHELL", "")
    if shell_env.endswith("zsh"):
        return "zsh"
    if shell_env.endswith("bash"):
        return "bash"
    # Default to bash on POSIX/WSL.
    return "bash"


def install_posix(shell: str, bindir: Path, print_only: bool) -> int:
    rc = _rc_for_shell(shell)
    block = _posix_block(bindir)
    if print_only or rc is None:
        print("Add this to your shell rc file:")
        print(block)
        if rc:
            print(f"(suggested file: {rc})")
        return 0
    text = rc.read_text(encoding="utf-8") if rc.exists() else ""
    if _already_present(text):
        print(f"Already installed in {rc}. Nothing to do.")
        return 0
    rc.parent.mkdir(parents=True, exist_ok=True)
    with open(rc, "a", encoding="utf-8") as f:
        f.write(block)
    print(f"Added {bindir} to PATH in {rc}.")
    print(f"Run:  source {rc}    (or open a new terminal), then: wiki --version")
    return 0


def install_powershell(bindir: Path, print_only: bool) -> int:
    # Determine the user's PowerShell profile path without importing PS.
    documents = Path.home() / "Documents"
    profile = documents / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    win_profile = documents / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1"
    target = profile if profile.parent.exists() else win_profile
    line = (
        f"\n{MARKER}\n"
        f'$env:PATH = "{bindir};" + $env:PATH\n'
        f"{MARKER_END}\n"
    )
    if print_only:
        print("Add this to your PowerShell profile:")
        print(line)
        print(f"(suggested file: {target})")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    text = target.read_text(encoding="utf-8") if target.exists() else ""
    if _already_present(text):
        print(f"Already installed in {target}. Nothing to do.")
        return 0
    with open(target, "a", encoding="utf-8") as f:
        f.write(line)
    print(f"Added {bindir} to PATH in {target}.")
    print("Open a new PowerShell window, then: wiki --version")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Add bin/ to PATH for the wiki CLI.")
    ap.add_argument("--shell", choices=["bash", "zsh", "powershell"],
                    help="Target shell (default: auto-detect).")
    ap.add_argument("--print-only", action="store_true",
                    help="Print the snippet without modifying any file.")
    args = ap.parse_args()

    bindir = bin_dir()
    if not bindir.is_dir():
        print(f"error: {bindir} does not exist.", file=sys.stderr)
        return 1

    shell = args.shell or _detect_shell()
    if shell == "powershell":
        return install_powershell(bindir, args.print_only)
    return install_posix(shell, bindir, args.print_only)


if __name__ == "__main__":
    raise SystemExit(main())
