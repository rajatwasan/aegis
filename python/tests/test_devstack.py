"""W6 tests: the deployment records its world in state.json and the console
reads that record instead of carrying addresses of its own (decision D10)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from aegis import devstack
from aegis.api import create_api_app
from aegis.api.agent_runner import parties_from_state
from aegis.devkeys import ACCOUNTS, KEYS
from tests.test_api_chain import chain_config


def test_devstack_records_the_seeded_parties(anvil_url: str, tmp_path: Path) -> None:
    """AC6.1: state.json carries parties.compliant and parties.frozen."""
    assert devstack.run(anvil_url, tmp_path, guardian_key=KEYS[9], operator_key=KEYS[0]) == 0
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["parties"] == {
        "compliant": [ACCOUNTS[1], ACCOUNTS[2], ACCOUNTS[3]],
        "frozen": [ACCOUNTS[4]],
    }
    # what the runner will read is exactly what was recorded
    assert parties_from_state(state) == state["parties"]
    # and the recorded world is the on chain world
    app = create_api_app(chain_config(tmp_path))
    client = TestClient(app)
    for party in state["parties"]["compliant"]:
        assert client.get(f"/compliance/{party}").json()["compliant"] is True
    frozen = client.get(f"/compliance/{state['parties']['frozen'][0]}").json()
    assert frozen["frozen"] is True


def test_devstack_reuse_keeps_a_recorded_world(anvil_url: str, tmp_path: Path) -> None:
    assert devstack.run(anvil_url, tmp_path, guardian_key=KEYS[9], operator_key=KEYS[0]) == 0
    first = json.loads((tmp_path / "state.json").read_text())
    assert (
        devstack.run(anvil_url, tmp_path, guardian_key=KEYS[9], operator_key=KEYS[0], reuse=True)
        == 0
    )
    assert json.loads((tmp_path / "state.json").read_text()) == first


def test_devstack_does_not_reuse_a_state_without_parties(anvil_url: str, tmp_path: Path) -> None:
    """A world recorded before W6 is redeployed rather than driven blind (C1)."""
    assert devstack.run(anvil_url, tmp_path, guardian_key=KEYS[9], operator_key=KEYS[0]) == 0
    state = json.loads((tmp_path / "state.json").read_text())
    del state["parties"]
    (tmp_path / "state.json").write_text(json.dumps(state))
    assert (
        devstack.run(anvil_url, tmp_path, guardian_key=KEYS[9], operator_key=KEYS[0], reuse=True)
        == 0
    )
    redeployed = json.loads((tmp_path / "state.json").read_text())
    assert "parties" in redeployed
    assert redeployed["token_address"] != state["token_address"]
