"""Verify that the test command wrapper only reports failed commands."""

import subprocess
from pathlib import Path

WRAPPER = Path(__file__).resolve().parents[1] / "scripts" / "quiet-check.sh"


def run_check(command):
    return subprocess.run(
        ["sh", WRAPPER, "sh", "-c", command],
        capture_output=True,
        text=True,
        check=False,
    )


def test_success_is_silent():
    result = run_check("echo diagnostic; echo warning >&2")
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_failure_reports_diagnostics_and_preserves_status():
    result = run_check("echo context; echo failure >&2; exit 23")
    assert (result.returncode, result.stdout, result.stderr) == (
        23,
        "",
        "context\nfailure\n",
    )
