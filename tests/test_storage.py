from universal_agent_control_plane.storage import StateStore


def test_state_round_trip(tmp_path) -> None:
    store = StateStore(tmp_path)
    result = store.put("tests", "answer", {"value": 42})
    assert result["status"] == "stored"
    assert store.get("tests", "answer") == {"value": 42}


def test_missing_state_returns_none(tmp_path) -> None:
    store = StateStore(tmp_path)
    assert store.get("tests", "missing") is None
