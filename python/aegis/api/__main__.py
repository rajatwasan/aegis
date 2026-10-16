"""Run the Guardian Console API: ``python -m aegis.api``.

Host/port come from AEGIS_API_HOST / AEGIS_API_PORT; everything else from the
AEGIS_* variables read by :class:`aegis.api.config.ApiConfig`.
"""

from __future__ import annotations

import os
import sys

import uvicorn

from aegis.api import ApiConfig, create_api_app
from aegis.errors import AegisError


def main() -> int:
    try:
        app = create_api_app(ApiConfig.from_env())
    except AegisError as exc:
        # one readable line, no traceback: a missing key or a guardian mismatch
        # is an operator problem, and the process must not come up (AGENTS.md C3, C8)
        print(f"aegis.api: refusing to start: {exc}", file=sys.stderr)
        return 2
    uvicorn.run(
        app,
        host=os.environ.get("AEGIS_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("AEGIS_API_PORT", "8000")),
        log_level=os.environ.get("AEGIS_API_LOG_LEVEL", "info"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
