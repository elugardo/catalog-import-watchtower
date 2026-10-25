"""Run every test layer in order and print one summary line per layer.

This is the entry point of the `test` container (`compose.test.yaml`); the one
command in `_docs/testing.md` -> *The one command* runs it. Every layer runs
even when an earlier one failed. The exit code is non-zero when any layer
failed, and a layer that ran zero tests counts as failed.

Layers, in order:
  unit         pytest tests/unit (no database)
  integration  pytest tests --ignore=tests/unit (the Compose `db`)
  check:api    npm --prefix web run check:api (generated types match openapi.yaml)
  frontend     npm --prefix web test (Vitest + Testing Library)

`python scripts/run_tests.py unit frontend` runs only the named layers.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS = Path(tempfile.mkdtemp(prefix="ciw-test-"))


@dataclass
class Result:
    layer: str
    returncode: int
    tests: int
    failures: int
    errors: int
    skipped: int
    noun: str = "tests"

    @property
    def passed(self) -> bool:
        return self.returncode == 0 and self.tests > 0 and not (self.failures or self.errors)

    def line(self) -> str:
        verdict = "PASSED" if self.passed else "FAILED"
        detail = f"{self.tests} {self.noun}"
        if self.failures or self.errors:
            detail += f", {self.failures} failed, {self.errors} errors"
        if self.skipped:
            detail += f", {self.skipped} skipped"
        if self.tests == 0:
            detail += " (zero tests counts as a failure)"
        if self.returncode != 0:
            detail += f", exit code {self.returncode}"
        return f"{self.layer:<12} {verdict}  {detail}"


def junit_counts(path: Path) -> tuple[int, int, int, int]:
    """(tests, failures, errors, skipped) summed over every <testsuite> in a JUnit file."""
    if not path.is_file():
        return 0, 0, 0, 0
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.iter("testsuite")
    totals = [0, 0, 0, 0]
    for suite in suites:
        for index, key in enumerate(("tests", "failures", "errors", "skipped")):
            totals[index] += int(suite.get(key) or 0)
    return tuple(totals)  # type: ignore[return-value]


def run(command: list[str]) -> int:
    print(f"\n$ {' '.join(command)}", flush=True)
    return subprocess.run(command, cwd=REPO_ROOT, check=False).returncode


def pytest_layer(layer: str, *selection: str) -> Result:
    report = REPORTS / f"{layer}.xml"
    returncode = run(
        [
            sys.executable,
            "-m",
            "pytest",
            *selection,
            "-p",
            "no:cacheprovider",
            f"--junitxml={report}",
        ]
    )
    return Result(layer, returncode, *junit_counts(report))


def check_api() -> Result:
    # One check: the types generated from openapi.yaml equal web/src/api/schema.d.ts.
    returncode = run(["npm", "--prefix", "web", "run", "check:api"])
    return Result("check:api", returncode, 1, int(returncode != 0), 0, 0, noun="check")


def frontend() -> Result:
    report = REPORTS / "frontend.xml"
    returncode = run(
        [
            "npm",
            "--prefix",
            "web",
            "test",
            "--",
            "--reporter=default",
            "--reporter=junit",
            f"--outputFile.junit={report}",
        ]
    )
    return Result("frontend", returncode, *junit_counts(report))


LAYERS = {
    "unit": lambda: pytest_layer("unit", "tests/unit"),
    "integration": lambda: pytest_layer("integration", "tests", "--ignore=tests/unit"),
    "check:api": check_api,
    "frontend": frontend,
}


def main(argv: list[str]) -> int:
    unknown = [name for name in argv if name not in LAYERS]
    if unknown:
        print(f"unknown layer(s) {unknown}; choose from {list(LAYERS)}", file=sys.stderr)
        return 2
    selected = argv or list(LAYERS)
    results = [LAYERS[name]() for name in selected]

    print("\n==== test summary " + "=" * 42)
    for result in results:
        print(result.line())
    failed = [result.layer for result in results if not result.passed]
    print(f"==== {'FAILED: ' + ', '.join(failed) if failed else 'ALL LAYERS PASSED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
