# Universal tool execution and MCP transport

The reusable tool_gateway.py, tool_mcp.py and tool_client.py modules extend the existing control-plane registry/skills architecture with explicit contracts for arbitrary host-registered tools. Agent Playpen is the first integration; it is not a dependency of this package. The existing instructions/skills/hooks server is unchanged and remains its own entry point.

## Reusable host API

```python
from universal_agent_control_plane.tool_gateway import ToolGateway, ToolSpec
from universal_agent_control_plane.tool_mcp import GatewayMCPServer

gateway = ToolGateway(database='./.data/tools.sqlite3')
gateway.register(ToolSpec(
    name='double', description='Double an integer',
    input_schema={'type':'object','properties':{'value':{'type':'integer'}},'required':['value'],'additionalProperties':False},
    output_schema={'type':'integer'}, handler=lambda value: value*2,
    read_only=True, replay_safe=True, version='1',
))
assert gateway.execute('double', {'value':21})['result'] == 42
# To expose these individual contracts over local stdio MCP:
# GatewayMCPServer(gateway).run()
```

Use python -m pip install -e ".[dev]" from this repository, then python -m pytest. jsonschema validates Draft 2020-12 input and optional output contracts; external references are rejected. The official MCP Python SDK supplies discovery, calls, result schemas and stdio/HTTP client transport. The gateway itself is reusable in-process with no model or transport.

ToolSpec registration is trusted host code, not a model-supplied module path. Each tool has its own discoverable input schema, handler, version, deadline, concurrency and readiness function. Generic skill_run(payload) remains for skills; do not hide ordinary tool contracts behind an untyped universal payload. ToolGateway validates before execution and produces execution_id, gateway/tool versions, redacted arguments, status, result, error, duration and checksum. A host-supplied redactor is applied before events/persistence. Hosts must provide their credential-aware redactor; the standalone default is identity. No credentials, model APIs or paid tools are used by this package's gateway tests.

## Execution boundaries

64 KiB argument and 1 MiB output limits; maximum 16 active in-process handlers per process, one call per ToolSpec instance unless configured otherwise. Deadlines are configurable up to 300 seconds. Timed-out Python handlers may still run; the record reports that uncertainty and their capacity remains occupied until return. No automatic write retries, hidden fallback, process sandbox or guaranteed rollback is provided. The MCP transport's annotations communicate declared behavior, not authorization enforcement by themselves. Permissions belong to the host/tool implementation.

Records persist to an optional dedicated SQLite table using parameterized queries and WAL. Memory/history windows are bounded; disk retention is manual. Replay requires explicit replay_safe, unchanged contract version and non-redacted recorded arguments. It creates a new linked execution. Do not mark live network reads, mutable files or writes replay-safe merely because they usually succeed.

MCP structuredContent contains the common execution envelope, with a compatible JSON text content block and isError on failure. Its outputSchema describes the envelope; tool-specific output validation happens inside the gateway before reporting success. Local and MCP clients share the same execution implementation.

MCPConnection maintains an explicit persistent connection, discovers a paginated catalog on request and executes calls without relisting it. It accepts a trusted stdio command/args/environment or public HTTPS/loopback HTTP URL. Authentication/OAuth HTTP onboarding is not provided by this small adapter. Calling hosts must select allowed tools, namespace names and control credential forwarding. Cancelled queued requests are not executed later. Remote timeout does not prove remote side effects stopped. Connections should be closed by the owning host.

## Agent Playpen integration and evidence

Playpen routes selected tools through this package and offers a direct tool console, a stdio server, optional external MCP tools and provider normalization. Calculator, scientific calculator, date/time, search, fetch, extraction, and file tools all use the same execution layer. Playpen's own source applies credential redaction, file boundaries and an explicit external server allowlist. This repository does not import Playpen or ship its keys, runtime, results or Qalculate binary.

The motivating evidence included correct direct answers followed by tool-protocol errors, invalid/missing arguments, successful calculations followed by invalid final answers, unclear readiness/progress, quota skips and scorer-format limitations. A common interface makes these stages observable; it does not guarantee identical LLM decisions. Historical Playpen scores remain unchanged. Read the [Playpen issue register](https://github.com/Alan-VZ/Agent-Playpen/blob/main/docs/issues-and-resolutions.md), [integration guide](https://github.com/Alan-VZ/Agent-Playpen/blob/main/docs/universal-tools.md) and [study](https://github.com/Alan-VZ/Agent-Playpen/blob/main/docs/studies/2026-11-17-five-task-matched.md).

## Credits

Alan Van Zandt's Universal Agent Control Plane provides the shared registry/adapter/execution foundation. Credit to [Model Context Protocol and official Python SDK contributors](https://github.com/modelcontextprotocol/python-sdk) for the interoperability protocol/transport; [Python jsonschema contributors](https://github.com/python-jsonschema/jsonschema) for schema validation; Pydantic/FastAPI/Python contributors for the existing foundations.

Design/evaluation inspiration: [Pydantic AI validation/retries](https://pydantic.dev/docs/ai/tools-toolsets/tools-advanced/), [Anthropic tool-design guidance](https://www.anthropic.com/research/writing-tools-for-agents), [Berkeley BFCL](https://gorilla.cs.berkeley.edu/leaderboard.html), [Apple ToolSandbox](https://github.com/apple-aiml-research/ToolSandbox) and [Sierra tau-bench](https://github.com/sierra-research/tau-bench). These are inspirations, not new framework dependencies or reproduced benchmark claims. [PAL](https://proceedings.mlr.press/v202/gao23f.html) motivated executable computation in Playpen; [Qalculate contributors](https://github.com/Qalculate/libqalculate) supply its external high-precision engine under their own license. See Playpen's full creator/source ledger for distinctions.

Validation feedback identifies missing field names or expected types without echoing rejected argument values. Unexpected fields are rejected against the advertised properties; a malformed request never starts its handler.
