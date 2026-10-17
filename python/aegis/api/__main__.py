"""Run the Guardian Console API: ``python -m aegis.api``.

Host/port come from AEGIS_API_HOST / AEGIS_API_PORT; everything else from the
AEGIS_* variables read by :class:`aegis.api.config.ApiConfig`.

Startup fails closed: a missing or malformed setting, or a guardian key that is
not the guardian of the deployed token, exits 1 with the reason instead of
serving approvals whose signatures could never execute.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn

from aegis.anchoring import StateError
from aegis.api import ApiConfig, create_api_app
from aegis.api.config import load_chain_state
from aegis.config import ConfigError


def main() -> int:
    try:
        config = ApiConfig.from_env()
        app = create_api_app(config)
        if load_chain_state(Path(config.state_dir)) is not None:
            # chain state exists: prove our key is the token's guardian before serving
            app.state.runner.runtime()
    except (ConfigError, StateError) as exc:
        print(f"aegis.api: refusing to start: {exc}", file=sys.stderr)
        return 1
    uvicorn.run(
        app,
        host=os.environ.get("AEGIS_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("AEGIS_API_PORT", "8000")),
        log_level=os.environ.get("AEGIS_API_LOG_LEVEL", "info"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
