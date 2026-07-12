"""Run the Guardian Console API: ``python -m aegis.api``.

Host/port come from AEGIS_API_HOST / AEGIS_API_PORT; everything else from the
AEGIS_* variables read by :class:`aegis.api.config.ApiConfig`.
"""

from __future__ import annotations

import os

import uvicorn

from aegis.api import ApiConfig, create_api_app


def main() -> int:
    app = create_api_app(ApiConfig.from_env())
    uvicorn.run(
        app,
        host=os.environ.get("AEGIS_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("AEGIS_API_PORT", "8000")),
        log_level=os.environ.get("AEGIS_API_LOG_LEVEL", "info"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
