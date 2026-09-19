from __future__ import annotations

import asyncio

from universal_agent_control_plane.server import mcp


def _tool_schemas() -> dict[str, dict]:
    async def list_schemas() -> dict[str, dict]:
        tools = await mcp.list_tools()
        return {tool.name: tool.output_schema for tool in tools}

    return asyncio.run(list_schemas())


def test_mcp_outputs_expose_stable_properties() -> None:
    schemas = _tool_schemas()

    assert schemas["registry_validate"]["properties"].keys() >= {"valid", "errors"}
    assert schemas["registry_resolve"]["properties"].keys() >= {
        "profile",
        "instructions",
        "skills",
    }
    assert schemas["skill_run"]["properties"].keys() >= {"skill"}
    assert schemas["orchestration_route"]["properties"].keys() >= {
        "target",
        "recipients",
        "executions",
        "errors",
        "succeeded",
        "failed",
    }
    assert schemas["hook_list"]["properties"].keys() >= {"events", "rootSessionsOnly"}
    assert schemas["hook_emit"]["properties"].keys() >= {
        "event",
        "sessionId",
        "handled",
        "results",
    }
    assert schemas["state_get"]["properties"].keys() >= {
        "namespace",
        "key",
        "value",
    }
