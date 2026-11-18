"""MCP transport for universal tool gateways; no dependency on any LLM host."""

import json

import anyio
from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

RESULT_SCHEMA = {
    "type": "object",
    "required": [
        "execution_id",
        "gateway_version",
        "tool",
        "status",
        "ok",
        "result",
        "error",
    ],
    "properties": {
        "execution_id": {"type": "string"},
        "gateway_version": {"type": "string"},
        "tool": {"type": "string"},
        "status": {"type": "string"},
        "ok": {"type": "boolean"},
        "result": {},
        "error": {"type": ["object", "null"]},
    },
}


class GatewayMCPServer(MCPServer):
    def __init__(self, gateway, name="Universal Tool Gateway"):
        super().__init__(name, version=gateway.version)
        self.gateway = gateway

    async def list_tools(self):
        return [
            Tool(
                name=spec.name,
                description=spec.description,
                inputSchema=spec.input_schema,
                outputSchema=RESULT_SCHEMA,
                annotations=ToolAnnotations(
                    read_only_hint=spec.read_only,
                    destructive_hint=not spec.read_only,
                    idempotent_hint=spec.replay_safe,
                    open_world_hint=not spec.replay_safe,
                ),
            )
            for spec in self.gateway.tools.values()
        ]

    async def call_tool(self, name, arguments, context=None):
        result = await anyio.to_thread.run_sync(
            lambda: self.gateway.execute(name, arguments)
        )
        return CallToolResult(
            content=[
                TextContent(type="text", text=json.dumps(result, ensure_ascii=False))
            ],
            structuredContent=result,
            isError=not result["ok"],
        )
