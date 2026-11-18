import asyncio
import threading

import pytest

from universal_agent_control_plane.tool_gateway import ToolGateway, ToolSpec
from universal_agent_control_plane.tool_mcp import GatewayMCPServer

SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "integer"}},
    "required": ["value"],
    "additionalProperties": False,
}


def gateway(tmp_path, **kwargs):
    instance = ToolGateway(database=tmp_path / "tools.sqlite3", **kwargs)
    instance.register(
        ToolSpec(
            "double",
            "Double a number",
            SCHEMA,
            lambda value: value * 2,
            replay_safe=True,
            output_schema={"type": "integer"},
        )
    )
    return instance


def test_validated_execution_persistence_and_replay(tmp_path):
    events = []
    instance = gateway(tmp_path, event=events.append)
    result = instance.execute("double", {"value": 21})
    assert result["ok"] and result["result"] == 42
    assert [item["status"] for item in events] == ["queued", "running", "succeeded"]
    assert (
        ToolGateway(database=tmp_path / "tools.sqlite3").get(result["execution_id"])
        == result
    )
    replay = instance.replay(result["execution_id"])
    assert replay["result_sha256"] == result["result_sha256"]
    assert replay["replay_of"] == result["execution_id"]


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"value": True},
        {"value": "21"},
        {"value": 1, "extra": 2},
        [],
        {"value": float("nan")},
    ],
)
def test_invalid_arguments_do_not_execute(tmp_path, arguments):
    instance = gateway(tmp_path)
    instance.tools["double"].handler = lambda **kw: pytest.fail(
        "Invalid input executed"
    )
    assert instance.execute("double", arguments)["error"]["code"] == "invalid_arguments"


def test_failure_classification_and_limits(tmp_path):
    instance = gateway(tmp_path)
    assert instance.execute("missing", {})["error"]["code"] == "unknown_tool"
    instance.tools["double"].readiness = lambda: {
        "ready": False,
        "message": "missing dependency",
    }
    assert instance.execute("double", {"value": 1})["error"]["code"] == "not_ready"
    instance.tools["double"].readiness = None
    instance.tools["double"].handler = lambda **kw: '{"ok":false,"error":"bad"}'
    assert instance.execute("double", {"value": 1})["error"]["code"] == "tool_error"
    instance.tools["double"].handler = lambda **kw: "wrong output type"
    assert instance.execute("double", {"value": 1})["error"]["code"] == "invalid_output"
    instance.tools["double"].handler = lambda **kw: "x" * 1048577
    assert instance.execute("double", {"value": 1})["error"]["code"] == "output_limit"


def test_timeout_holds_capacity_and_writes_cannot_replay(tmp_path):
    release = threading.Event()
    instance = gateway(tmp_path)
    instance.tools["double"].handler = lambda **kw: release.wait(2)
    try:
        result = instance.execute("double", {"value": 1}, timeout=0.01)
        assert result["status"] == "timed_out" and result["may_still_be_running"]
        assert instance.execute("double", {"value": 1})["error"]["code"] == "busy"
        instance.tools["double"].replay_safe = False
        with pytest.raises(ValueError, match="replay-safe"):
            instance.replay(result["execution_id"])
    finally:
        release.set()


def test_redacted_records_and_untrusted_schema(tmp_path):
    def redact(value):
        if isinstance(value, str):
            return value.replace("private", "[REDACTED]")
        if isinstance(value, dict):
            return {k: redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [redact(v) for v in value]
        return value

    instance = ToolGateway(redact=redact)
    instance.register(
        ToolSpec("echo", "echo", {"type": "object"}, lambda **kw: kw, replay_safe=True)
    )
    result = instance.execute("echo", {"text": "private"})
    assert result["arguments_redacted"] and result["result"]["text"] == "[REDACTED]"
    with pytest.raises(ValueError, match="non-redacted"):
        instance.replay(result["execution_id"])
    with pytest.raises(ValueError, match="External schema"):
        ToolSpec("bad", "bad", {"$ref": "https://example.org/schema"}, lambda: None)


def test_official_mcp_client_roundtrip(tmp_path):
    from mcp.client import Client

    async def run():
        async with Client(GatewayMCPServer(gateway(tmp_path))) as client:
            catalog = await client.list_tools()
            assert catalog.tools[0].input_schema == SCHEMA
            result = await client.call_tool("double", {"value": 21})
            assert not result.is_error and result.structured_content["result"] == 42
            invalid = await client.call_tool("double", {"value": "bad"})
            assert (
                invalid.is_error
                and invalid.structured_content["error"]["code"] == "invalid_arguments"
            )

    asyncio.run(run())


def test_validation_feedback_names_missing_fields_without_echoing_values(tmp_path):
    instance = gateway(tmp_path)
    assert "value" in instance.execute("double", {})["error"]["message"]
    result = instance.execute("double", {"value": "private-synthetic-input"})
    assert "expected integer" in result["error"]["message"]
    assert "private-synthetic-input" not in result["error"]["message"]
