#!/usr/bin/env python3
"""Build a reproducible wiki.pyz zipapp.

Assembles the wikicli package plus its pure-Python runtime dependency
(portalocker) into a single executable zipapp, then records a SHA-256 checksum
that CI can verify. JSON Schema validation inside the pyz uses the bundled
pure-Python validator (wikicli.core._minijsonschema), so no compiled
dependencies are required.

Reproducibility: every file is written into the zip with a fixed timestamp and
deterministic ordering, so the same inputs yield a byte-identical pyz (and
therefore a stable checksum) across machines.

Usage:
    python tools/build_pyz.py [--out tools/wiki.pyz]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

FIXED_DATE = (1980, 1, 1, 0, 0, 0)  # zip epoch; deterministic
SHEBANG = b"#!/usr/bin/env python3\n"


def _copy_package(src_pkg: Path, dest_root: Path):
    for path in sorted(src_pkg.rglob("*")):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        rel = path.relative_to(src_pkg.parent)
        target = dest_root / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _vendor_portalocker(dest_root: Path) -> bool:
    try:
        import portalocker
    except Exception:
        return False
    src = Path(portalocker.__file__).parent
    dest = dest_root / "portalocker"
    for path in sorted(src.rglob("*")):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        rel = path.relative_to(src)
        target = dest / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    return True


def _write_main(dest_root: Path):
    (dest_root / "__main__.py").write_text(
        "import sys\n"
        "from wikicli.__main__ import main\n"
        "if __name__ == '__main__':\n"
        "    sys.exit(main())\n",
        encoding="utf-8",
    )


def _deterministic_zip(staging: Path, out_path: Path):
    files = []
    for path in staging.rglob("*"):
        if path.is_file():
            files.append(path)
    files.sort(key=lambda p: p.relative_to(staging).as_posix())

    buf = out_path.with_suffix(".pyz.tmp")
    with open(buf, "wb") as raw:
        raw.write(SHEBANG)
        with zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in files:
                arcname = path.relative_to(staging).as_posix()
                info = zipfile.ZipInfo(arcname, date_time=FIXED_DATE)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                zf.writestr(info, path.read_bytes())
    os.replace(buf, out_path)
    out_path.chmod(0o755)


def _self_test(out_path: Path):
    """Run the freshly built pyz in a throwaway repo to prove it actually works
    end to end with whatever is (or isn't) bundled. A green build must never
    ship a pyz that cannot lock and mutate. Runs with an EMPTY PYTHONPATH and no
    site-packages access so we exercise exactly what the zipapp carries."""
    import subprocess

    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ)
        # Force isolation: ignore the developer's site-packages so the test
        # reflects a bare end-user runtime (this is what caught the original
        # silent portalocker defect).
        env["PYTHONPATH"] = ""
        env["PYTHONNOUSERSITE"] = "1"
        cmd_init = [sys.executable, "-S", str(out_path), "init"]
        cmd_doctor = [sys.executable, "-S", str(out_path), "doctor"]
        r1 = subprocess.run(cmd_init, cwd=tmp, env=env, capture_output=True, text=True)
        r2 = subprocess.run(cmd_doctor, cwd=tmp, env=env, capture_output=True, text=True)
        if r1.returncode != 0 or r2.returncode != 0:
            sys.stderr.write(
                "build self-test FAILED: the pyz does not run in an isolated "
                "runtime.\n"
                f"  init   exit={r1.returncode}\n{_indent(r1.stderr)}\n"
                f"  doctor exit={r2.returncode}\n{_indent(r2.stderr or r2.stdout)}\n"
            )
            sys.exit(1)
        if "[FAIL]" in r2.stdout:
            sys.stderr.write(
                "build self-test FAILED: `wiki doctor` reported a failing "
                f"check in an isolated runtime:\n{_indent(r2.stdout)}\n"
            )
            sys.exit(1)


def _indent(text: str) -> str:
    return "\n".join("    " + line for line in (text or "").splitlines())


def build(out_path: Path, *, self_test: bool = True) -> str:
    here = Path(__file__).resolve().parent
    src_pkg = here / "wiki-src" / "wikicli"
    if not src_pkg.is_dir():
        print(f"error: cannot find wikicli package at {src_pkg}", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp)
        _copy_package(src_pkg, staging)
        # portalocker is an OPTIONAL accelerator. The CLI locks with stdlib
        # primitives (fcntl / msvcrt) when it is absent, so a missing
        # portalocker is informational, not a build failure.
        if _vendor_portalocker(staging):
            print("vendored portalocker (optional accelerator).")
        else:
            print("note: portalocker not bundled; using stdlib locking "
                  "(fcntl/msvcrt). This is fully supported.")
        _write_main(staging)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _deterministic_zip(staging, out_path)

    if self_test:
        _self_test(out_path)

    checksum = hashlib.sha256(out_path.read_bytes()).hexdigest()
    (out_path.parent / "wiki.pyz.sha256").write_text(
        f"{checksum}  {out_path.name}\n", encoding="utf-8"
    )
    return checksum


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "wiki.pyz"))
    ap.add_argument("--no-self-test", action="store_true",
                    help="skip the post-build isolated run (not recommended).")
    args = ap.parse_args()
    out = Path(args.out)
    checksum = build(out, self_test=not args.no_self_test)
    print(f"built {out}")
    print(f"sha256 {checksum}")


if __name__ == "__main__":
    main()
