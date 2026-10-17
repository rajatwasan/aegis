"""Enforce the coverage floors of AGENTS.md R26 from a coverage.py JSON report.

    pytest python/tests --cov=aegis --cov-branch --cov-report=json:coverage.json
    python scripts/check_coverage.py coverage.json

Floors: aegis/policy/engine.py 100% branch; aegis/approval/, aegis/audit/ and
aegis/guardian_touch/ 95% line. A missing file in the report is a failure,
never a pass (AGENTS.md R11).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

LINE_FLOORS = {"aegis/approval/": 95.0, "aegis/audit/": 95.0, "aegis/guardian_touch/": 95.0}
BRANCH_FLOORS = {"aegis/policy/engine.py": 100.0}


def _pct(covered: int, total: int) -> float:
    return 100.0 if total == 0 else 100.0 * covered / total


def main(argv: list[str]) -> int:
    report = json.loads(Path(argv[1] if len(argv) > 1 else "coverage.json").read_text())
    files = {k.replace("\\", "/"): v["summary"] for k, v in report["files"].items()}
    failures: list[str] = []

    for prefix, floor in LINE_FLOORS.items():
        members = {k: v for k, v in files.items() if prefix in k}
        if not members:
            failures.append(f"{prefix}: no files in the coverage report")
            continue
        covered = sum(v["covered_lines"] for v in members.values())
        total = sum(v["num_statements"] for v in members.values())
        pct = _pct(covered, total)
        status = "ok" if pct >= floor else "BELOW FLOOR"
        print(f"{prefix:<24} line {pct:6.2f}% (floor {floor}%) {status}")
        if pct < floor:
            failures.append(f"{prefix} line coverage {pct:.2f}% < {floor}%")

    for suffix, floor in BRANCH_FLOORS.items():
        match = next((v for k, v in files.items() if k.endswith(suffix)), None)
        if match is None or "num_branches" not in match:
            failures.append(f"{suffix}: no branch data in the coverage report (run --cov-branch)")
            continue
        pct = _pct(match["covered_branches"], match["num_branches"])
        status = "ok" if pct >= floor else "BELOW FLOOR"
        print(f"{suffix:<24} branch {pct:6.2f}% (floor {floor}%) {status}")
        if pct < floor:
            failures.append(f"{suffix} branch coverage {pct:.2f}% < {floor}%")

    for failure in failures:
        print(f"coverage: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
