"""Write the API's OpenAPI schema to frontend/openapi.json.

The snapshot is committed so `npm run gen:api` (openapi-typescript) never needs
a running server. Regenerate after any API change:

    .venv/bin/python scripts/gen_openapi.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from aegis.api import ApiConfig, create_api_app
from aegis.approval import ApprovalConfig

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "frontend" / "openapi.json"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        config = ApiConfig(
            approval=ApprovalConfig(
                db_path=f"{tmp}/approvals.db",
                audit_log_path=f"{tmp}/audit.jsonl",
                audit_key_file=f"{tmp}/audit.key",
                policy_path=str(REPO_ROOT / "policies" / "default.yaml"),
            ),
            state_dir=tmp,
        )
        schema = create_api_app(config).openapi()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
