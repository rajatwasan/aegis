"""Entry point for the adversarial eval harness.

The implementation lives in the installable package (``aegis.evals_harness``) so
it is importable and unit-testable; this file is the CLI the repo layout expects
under ``evals/``. Run it with ``make evals`` or ``python evals/harness.py``.
"""

from __future__ import annotations

from aegis.evals_harness import main

if __name__ == "__main__":
    raise SystemExit(main())
