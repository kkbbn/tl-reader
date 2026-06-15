from __future__ import annotations

import shlex
import subprocess


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print(f"+ {shlex.join(cmd)}", flush=True)
    return subprocess.run(cmd, text=True, check=check)


def capture(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True)
