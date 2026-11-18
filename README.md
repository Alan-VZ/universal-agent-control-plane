# Universal Agent Instructions and Skills

<p align="center">
  <a href="https://github.com/Alan-VZ/universal-agent-control-plane/actions/workflows/ci.yml"><img src="https://github.com/Alan-VZ/universal-agent-control-plane/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-3776AB.svg" alt="Python 3.10+" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT" /></a>
</p>

An open-source control plane for sharing instructions, Agent Skills, prompts, tools, and optional state across AI agents in VS Code and other MCP-compatible hosts.

The project has one core goal:

**Author reusable agent guidance once, validate it once, and deliver it through each
host's supported mechanism without pretending every host has identical semantics.**

> [!IMPORTANT]
> This project is an alpha-stage local developer tool. Review generated user-level
> configuration before using it on a production workstation, and do not expose the HTTP
> gateway beyond localhost without adding authentication and transport security.

## Architecture map

<p align="center">
  <a href="docs/universal-agent-control-plane.html">
    <img src="docs/universal-agent-control-plane.svg" alt="Universal Agent Control Plane architecture showing the canonical registry, MCP runtime services, global installer, hook dispatcher, and agent hosts" width="1200" />
  </a>
</p>

The diagram is embedded as SVG so GitHub can display it directly. Open the
[self-contained interactive architecture map](docs/universal-agent-control-plane.html)
for the full browser view.

The design uses two complementary delivery paths:

1. **Native user-scope installation** creates host-compatible instruction projections and live links to canonical skills.
2. **MCP delivery** exposes tools, prompts, resources, and optional shared state through the Model Context Protocol.

MCP is the integration protocol, not an instruction override mechanism. Each agent host still decides which resources, prompts, and tools it discovers, loads, or invokes.

## Current platform reality

The original concept is valid, but several assumptions have changed:

- GitHub Copilot in VS Code supports MCP servers natively. A custom REST wrapper is not required for current MCP-capable versions of VS Code.
- VS Code supports portable Agent Skills stored in `.github/skills/`, `.claude/skills/`, or `.agents/skills/`, as well as user-level equivalents.
- VS Code recognizes multiple instruction formats, including `.github/copilot-instructions.md`, `AGENTS.md`, `CLAUDE.md`, `.github/instructions/*.instructions.md`, and `.claude/rules/`.
- Claude Code supports MCP, `CLAUDE.md`, `.claude/rules/`, and filesystem-based Agent Skills.
- OpenAI Codex CLI supports MCP servers via `~/.codex/config.toml`, an always-on
  `~/.codex/AGENTS.md` instructions file, and filesystem-based Agent Skills under
  `~/.codex/skills/`.
- **GitHub Copilot, Claude Code, and Codex CLI all ship native lifecycle hooks.** Copilot reads hook files from `.github/hooks/`, `~/.copilot/hooks/`, and its settings; Claude Code reads them from `~/.claude/settings.json` and `.claude/settings.json`; Codex reads them from `~/.codex/hooks.json`. Hooks therefore do not need to be simulated — this server acts as the shared hook backend all three hosts call.
- Skills and instructions are portable only where their host semantics overlap. A resolver and adapter layer is still useful for validation, precedence, compatibility checks, and installation.

This repository therefore aims for **shared source, explicit adapters, and honest capability negotiation** rather than claiming that all agents behave identically.

## Repository map

```text
universal-agent-control-plane/
├── README.md
├── LICENSE
├── CHANGELOG.md
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── SECURITY.md
├── pyproject.toml
├── AGENTS.md
├── server.py
├── .vscode/
│   └── mcp.json
├── .github/
│   ├── ISSUE_TEMPLATE/
│   ├── workflows/
│   │   └── ci.yml
│   ├── dependabot.yml
│   └── pull_request_template.md
├── docs/
│   ├── external-mcp-servers.md
│   ├── universal-agent-control-plane.html
│   └── universal-agent-control-plane.svg
├── registry/
│   ├── manifest.yaml
│   ├── instructions/
│   │   └── global.md
│   ├── skills/
│   │   └── example-skill/
│   │       └── SKILL.md
│   └── prompts/
│       └── code-review.md
├── src/
│   └── universal_agent_control_plane/
│       ├── api.py
│       ├── cli.py
│       ├── execution.py
│       ├── global_install.py
│       ├── hooks.py
│       ├── logging_config.py
│       ├── orchestration.py
│       ├── server.py
│       ├── registry.py
│       ├── storage.py
│       └── runners/
│           ├── greeting.py
│           └── session_journal.py
└── tests/
    ├── test_api.py
    ├── test_execution.py
    ├── test_global_install.py
    ├── test_hook_install.py
    ├── test_hooks.py
    ├── test_orchestration.py
    ├── test_registry.py
    └── test_storage.py
```

The repository now includes a working Python MCP server, canonical registry, example
skill and prompt, SQLite-backed shared state, VS Code configuration, and focused tests.

## Component responsibilities

| Component | Responsibility |
| --- | --- |
| Canonical registry | Versioned source for instructions, skills, prompt templates, manifests, and compatibility metadata |
| Registry resolver | Validates schemas, resolves scope and precedence, and produces a deterministic effective configuration |
| MCP gateway | Exposes standard MCP tools, prompts, and resources over `stdio` and Streamable HTTP |
| Global installer | Merges user MCP configuration, adds managed instruction projections, writes managed hook configuration, and creates live links to canonical skills |
| Hook dispatcher | Normalizes host lifecycle events onto canonical names, enforces anti-recursion and anti-bloat rules, and journals session history |
| Policy and state | Applies authorization and capability rules; stores optional namespaced state and append-only audit events |
| Agent hosts | Consume MCP capabilities and/or native files according to host behavior and user approval |

## Implemented MCP surface

Prefer standard MCP primitives instead of inventing REST-like endpoint names.

### Resources

```text
instructions://catalog
instructions://effective/{profile}
skills://catalog
skills://{name}/manifest
registry://manifest
```

Resources are the natural fit for discoverable, read-only context such as effective instructions and skill metadata.

### Prompts

```text
review_code
```

Prompts provide user-selectable templates. They should not be treated as silently injected system instructions.

### Tools

```text
registry_search
registry_validate
registry_resolve
skill_run
orchestration_route
state_get
state_put
hook_list
hook_emit
journal_recent
```

Tool schemas must be explicit and validated. Every parameter carries an MCP
`description`, and every tool declares `readOnlyHint`/`destructiveHint`/
`idempotentHint`/`openWorldHint` annotations so a client can tell reads from
writes without parsing prose. `skill_run` dispatches only to allow-listed
implementations declared in the registry; it never imports an arbitrary
module name supplied by a client. `orchestration_route` (formerly
`orchestrate`) runs the skill independently once per recipient (three times
for `broadcast`) and returns `executions` keyed by recipient plus
`succeeded`/`failed` recipient lists — one recipient's failure does not
prevent the others from executing. Use `skill_run` when a specific agent
target does not matter; use `orchestration_route` when it does, or to
broadcast to every known agent.

## Configuration model

The registry manifest should describe both content and compatibility:

```yaml
schemaVersion: 1
profiles:
  default:
    instructions:
      - instructions/global.md
    skills:
      - example-skill

targets:
  vscode:
    instructions: true
    agentSkills: true
    mcp:
      tools: true
      prompts: true
      resources: true
  claude-code:
    instructions: true
    agentSkills: true
    mcp:
      tools: true
      prompts: true
      resources: true
```

The resolver should fail clearly when a target cannot represent a requested feature. Silent conversion would make behavior unpredictable.

## Design principles

1. **Canonical source, generated projections**
   Edit registry content, not generated host files.

2. **Standards before adapters**
   Use MCP and the Agent Skills standard directly where supported. Add adapters only for real semantic gaps.

3. **Deterministic resolution**
   Scope, precedence, inheritance, and conflicts must produce repeatable output with an explainable resolution trace.

4. **Least privilege**
   Separate read-only resources from mutating tools. Require explicit grants for filesystem, process, network, secret, and state access.

5. **Human approval**
   Hosts should preserve confirmation for consequential tool calls. The server must not disguise side effects.

6. **Untrusted content boundaries**
   Registry documents, tool results, remote resources, and skill packages are data—not authority. Validate paths, schemas, signatures, and origins.

7. **Portable core, host-specific edges**
   Keep shared skills portable, while allowing clearly labeled host extensions when a capability is not universal.

## Security baseline

Status reflects what is in the code today, not what is planned.

| Control | Status | Evidence |
| --- | --- | --- |
| localhost-only binding for Streamable HTTP | Implemented | `api.py` binds `127.0.0.1` and rejects non-loopback hosts |
| Path traversal prevention and a configured registry root | Implemented | `Registry._safe_path` rejects paths escaping the root |
| Allow-listed skill runners | Implemented | runners resolve only through `manifest.yaml` |
| No dynamic import or shell execution from untrusted skill names | Implemented | client-supplied names are never imported directly |
| Input and output schema validation | Implemented | Pydantic models on REST and concrete MCP output envelopes, with explicitly open-ended skill payload fields |
| Namespaced, concurrency-safe state storage | Implemented | SQLite with WAL and namespaced keys |
| Append-only audit records for mutations and skill execution | Implemented | `state.put`, `hook.event`, and `skill.run` rows |
| Runner source hashing recorded with each execution | Implemented | closes the hot-reload time-of-check/time-of-use gap |
| Resource size limits | Implemented | 64 KiB caps on payloads, summaries, and state values |
| `Origin` validation and authentication for HTTP connections | Planned | no auth layer exists; localhost binding is the only control |
| Environment or secret-store credentials | Planned | no credentials are consumed yet |
| Per-client authorization and least-privilege scopes | Planned | all clients share one permission level |
| Execution time and concurrency limits | Planned | runners are not yet time-bounded |

A shared `memory.json` file is not sufficient for concurrent clients, access control, or crash-safe writes. SQLite is a reasonable local MVP; a pluggable store can follow.

## Implementation status

### Phase 1 — Registry and validation (implemented)

- Define the manifest and content schemas.
- Load and validate instructions, prompts, and `SKILL.md` packages.
- Resolve one profile deterministically.
- Add unit tests for invalid paths, duplicate IDs, conflicts, and precedence.

### Phase 2 — Native distribution (implemented)

- Install user skills into supported directories as live links.
- Generate a VS Code instruction projection and a managed Claude import.
- Merge global MCP configuration without replacing unrelated servers.
- Support dry-run, status/doctor, conflict detection, idempotent sync, and managed-only uninstall.

### Phase 3 — MCP server (implemented)

- Implement `stdio` transport first.
- Expose registry resources, prompt templates, and read-only validation tools.
- Add localhost Streamable HTTP; authentication remains required before remote exposure.

### Phase 4 — Execution and state (implemented locally)

- Add permission-declared, allow-listed skill execution.
- Add namespaced SQLite state and audit events.
- Add contract tests against installed VS Code and Claude Code clients.

### Phase 5 — Packaging (in progress)

- Publish a Python package and a reproducible launcher.
- Install VS Code and Agent Host user configuration through the CLI.
- Document migration from existing `.github`, `.claude`, and `.agents` customizations.

## Non-goals

- Injecting hidden system prompts into an agent host
- Overriding a host's safety policy or tool approval UI
- Guaranteeing identical model behavior across vendors
- Treating executable skills as trusted merely because they are in the registry
- Replacing native instruction and Agent Skills support when it already works
- Building cross-host multi-agent orchestration — autonomous agent-to-agent
  delegation, negotiation, or scheduling — before registry, transport, and
  security contracts are stable. The shipped `orchestration_route` tool
  executes one skill independently for each target recipient (or all
  recipients on `broadcast`) and reports a per-recipient result; it does not
  spawn agents, let recipients negotiate, or coordinate cross-host state.

## Workspace MCP configuration

The included `.vscode/mcp.json` starts the local UACP server and configures five
official third-party MCP integrations:

| Server | Transport | Authentication | Primary use |
| --- | --- | --- | --- |
| Universal Agent Control Plane | Local stdio | None | Shared registry, skills, prompts, hooks, and state |
| Perplexity | Hosted HTTP | Perplexity API key, stored by VS Code | Search, research, and reasoning |
| Playwright | Local stdio via `npx` | None | Accessibility-tree browser automation |
| Firecrawl | Local stdio via `npx` | Firecrawl API key, stored by VS Code | Search, scrape, crawl, and structured web extraction |
| Higgsfield | Hosted HTTP | Browser-based OAuth | Image, video, character, and audio generation |
| Chrome DevTools | Local stdio via `npx` | None | Browser debugging, network inspection, and performance analysis |

See the [external MCP server setup and operations guide](docs/external-mcp-servers.md)
for prerequisites, credential setup, first-run behavior, verification prompts, security
and billing considerations, troubleshooting, and optional configurations.

Install this project first so the local UACP entry can start:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

The root launcher keeps local use simple:

```powershell
# Native stdio MCP
.\.venv\Scripts\python.exe .\server.py

# Streamable HTTP MCP plus REST compatibility routes
.\.venv\Scripts\python.exe .\server.py --http
```

Then open **MCP: List Servers** in VS Code and start
`universal-agent-control-plane`. The equivalent UACP-only configuration is:

```json
{
  "servers": {
    "universal-agent-control-plane": {
      "type": "stdio",
      "command": "${workspaceFolder}\\.venv\\Scripts\\python.exe",
      "args": [
        "-m",
        "universal_agent_control_plane.server"
      ],
      "env": {
        "PYTHONPATH": "${workspaceFolder}\\src",
        "UACP_REGISTRY_ROOT": "${workspaceFolder}\\registry",
        "UACP_DATA_DIR": "${workspaceFolder}\\.data"
      }
    }
  }
}
```

For the complete checked-in configuration, including secure VS Code input variables for
Perplexity and Firecrawl, inspect [`.vscode/mcp.json`](.vscode/mcp.json). API keys are
prompted for by VS Code and stored in its secret storage; they are not committed to this
repository. Higgsfield opens its OAuth authorization flow when first connected.

The server uses `stdio` by default and exposes:

- resources: `registry://manifest`, `instructions://effective/{profile}`,
  `skills://catalog`, and `skills://{name}/manifest`
- prompt: `review_code`
- tools: `registry_validate`, `registry_resolve`, `registry_search`, `skill_run`,
  `orchestration_route`, `state_get`, `state_put`, `hook_list`, `hook_emit`, and
  `journal_recent`

### HTTP MCP and REST compatibility gateway

Run the optional localhost gateway:

```powershell
.\.venv\Scripts\python.exe -m universal_agent_control_plane.api
```

This exposes the native Streamable HTTP MCP endpoint at
`http://127.0.0.1:8000/mcp` and interactive REST documentation at
`http://127.0.0.1:8000/docs`.

REST compatibility routes are:

- `GET /health`
- `GET /instructions?profile=default`
- `GET /skills`
- `POST /execute`
- `POST /copilot/skill`
- `GET /memory?namespace=...&key=...`
- `POST /memory`
- `POST /orchestrate`
- `GET /hooks`
- `POST /hooks/{event}`

Current VS Code and Claude clients should use the native MCP endpoint. The REST routes
exist for older clients, scripts, and extension commands; they do not imitate MCP tool
discovery.

Skill runner modules are explicitly allow-listed in `registry/manifest.yaml`. Their
source modification time is checked on each call and changed modules are reloaded
without restarting the server. Because the reloaded module may differ from the one
validated at allow-list time, every execution records a SHA-256 hash of the runner
source in the audit table, so an audit record identifies the code that actually ran
rather than only the skill name. Both server modes write structured JSON logs to stderr
and `.data/server.log`.

Secrets must use environment files, input variables, or the platform secret store rather
than literal values in this file.

## Universal hooks

Hooks let one lifecycle rule run identically on every supported agent. Copilot, Claude
Code, and Codex CLI each have their own native hook system, their own event names, and
their own payload shapes. This server normalizes all of them onto one canonical event
set, so you write the behavior once.

### Canonical events

```text
session_start   session_end     user_prompt
pre_tool_use    post_tool_use   subagent_start
subagent_stop   agent_stop      notification
```

Host spellings are accepted in any dialect and mapped onto these names:
`sessionEnd`, `SessionEnd`, and `session_end` all resolve to `session_end`.
Three payload shapes are understood — Copilot camelCase (Unix millisecond
timestamps), the VS Code snake_case form, and Claude PascalCase.

### Three ways to deliver a hook

| Surface | Use when |
| --- | --- |
| `uacp hook <event>` (stdin JSON) | Default. Needs no running server, so it stays inside Claude's short `SessionEnd` budget. |
| `POST /hooks/{event}` | The gateway is already running and you want an HTTP hook. |
| `hook_emit` MCP tool | An agent should raise a lifecycle event itself. |

`GET /hooks` and the `hook_list` tool report the configured events and handlers.

### Behavior rules

Two rules keep the session journal trustworthy:

- **Anti-recursion.** Events listed under `hooks.rootSessionsOnly` in
  `registry/manifest.yaml` are skipped when the payload carries `agent_id` or
  `agent_type`. Sub-agents therefore never summarize themselves.
- **Anti-bloat.** A repeated `(event, sessionId)` pair is a no-op, summaries shorter
  than 200 characters are rejected, and a session is journaled once.

The session-end handler stores a **caller-supplied** summary. It never invokes a model,
so ending a session cannot trigger another billable agent run.

A failing hook is always reported as data. Handler errors never abort the host session,
and the CLI exits `0` even on failure. Logs go to stderr so stdout carries exactly one
JSON object for the host to parse.

### Configuration

`uacp install-global` writes managed hook configuration for all three hosts:
`~/.copilot/hooks/universal-agent-control-plane.json`, a managed group inside
`~/.claude/settings.json`, and a managed group inside `~/.codex/hooks.json`. Install is
idempotent and preserves hooks you wrote yourself; `uacp uninstall-global` removes only
the managed entries.

The Claude `SessionEnd` handler is registered with `"async": true` because
`SessionEnd` hooks share a 1.5 second budget by default. Codex's `SessionEnd` handler is
registered with `"async": true` and an explicit `"timeout": 3` because Codex caps
`SessionEnd`/`Interrupt` handlers at 3 seconds by default (vs. 600 seconds elsewhere).
Unlike Claude and Copilot, Codex hook handlers take a single shell-quoted `command`
string rather than a `command`/`args` pair, so the installer quotes the Python
invocation per-platform (`subprocess.list2cmdline` on Windows, `shlex.join` elsewhere).

HTTP hooks pointed at `http://localhost` require `COPILOT_HOOK_ALLOW_LOCALHOST=1` on
Copilot, which is why the CLI surface is the default.

## Install once for every project

The global installer makes the canonical registry available to supported agents in every
workspace while leaving repository-level instructions available for project-specific
rules.

```powershell
# Preview destinations and conflicts; this performs no writes.
.\.venv\Scripts\uacp.exe install-global --dry-run

# Install global instructions, live skill links, and MCP configuration.
.\.venv\Scripts\uacp.exe install-global

# Reconcile managed links/configuration after adding or removing registry skills.
.\.venv\Scripts\uacp.exe sync-global

# Inspect the current installation.
.\.venv\Scripts\uacp.exe doctor

# Remove only UACP-managed files, links, blocks, and MCP entries.
.\.venv\Scripts\uacp.exe uninstall-global
```

The installer owns only these projections:

| Consumer | Managed user-scope projection |
| --- | --- |
| VS Code/Copilot instructions | `~/.copilot/instructions/uacp-global.instructions.md` |
| Claude instructions | Marked import block in `~/.claude/CLAUDE.md` |
| Codex instructions | Marked link block in `~/.codex/AGENTS.md` |
| VS Code MCP | Merged server entry in `%APPDATA%\Code\User\mcp.json` |
| Copilot Agent Host MCP | Merged server entry in `~/.copilot/mcp-config.json` |
| Codex MCP | Merged `[mcp_servers.universal-agent-control-plane]` table in `~/.codex/config.toml` |
| Portable skills | Live links under `~/.copilot/skills`, `~/.claude/skills`, `~/.agents/skills`, and `~/.codex/skills` |

On Windows, the live skill links use directory symbolic links when available and directory
junctions otherwise. They point to `registry/skills`, so editing a canonical `SKILL.md`
takes effect without copying it into every host directory.

Claude Code reads the canonical instruction file through its managed
`@uacp-registry/instructions/global.md` import. VS Code/Copilot and Codex each read a
small global instruction projection whose Markdown link targets the same canonical file
(Codex has no `@import` syntax, so its `AGENTS.md` block uses a plain relative link like
Copilot's). The installer never overwrites an existing skill directory that it does not
own and never replaces unrelated MCP servers or `config.toml` tables.

If the Claude CLI is installed, `install-global` registers the stdio server at user scope.
If it is absent, the install still configures Claude instructions and skills and returns
the exact `claude mcp add-json ... --scope user` command to run later.

### Precedence and project overrides

Global configuration supplies defaults; it does not remove native project customization.
Keep repository-specific behavior in the host-supported project files, such as:

- `.github/copilot-instructions.md`
- `.github/instructions/*.instructions.md`
- `AGENTS.md`
- `CLAUDE.md` and `.claude/rules/`
- project-local `.github/skills`, `.claude/skills`, or `.agents/skills`

Project files should contain only rules specific to that repository. Avoid copying the
global instruction set into each project.

## Contributing and support

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md), follow the
[Code of Conduct](CODE_OF_CONDUCT.md), and review the [Security Policy](SECURITY.md)
before reporting a vulnerability.

- Use [GitHub Issues](https://github.com/Alan-VZ/universal-agent-control-plane/issues)
  for reproducible bugs and focused feature requests.
- Use pull requests for reviewed changes; the CI workflow runs the supported Python
  3.10-3.13 test matrix on both Ubuntu and Windows automatically.
- See [CHANGELOG.md](CHANGELOG.md) for release history.

## Definition of done for the first release

- One canonical registry can be consumed by current VS Code/Copilot, Claude Code, and
  Codex CLI.
- Effective instructions and skills can be explained before installation.
- Standard MCP discovery works for tools, prompts, and resources.
- Installation is idempotent and supports dry-run, status, sync, and managed-only rollback.
- Mutating actions are authenticated, authorized, validated, and audited.
- Contract and security tests cover both supported clients.

## References

- [VS Code: custom instructions](https://code.visualstudio.com/docs/agent-customization/custom-instructions)
- [VS Code: Agent Skills](https://code.visualstudio.com/docs/agent-customization/agent-skills)
- [VS Code: MCP servers](https://code.visualstudio.com/docs/agent-customization/mcp-servers)
- [Perplexity MCP server](https://github.com/perplexityai/modelcontextprotocol)
- [Playwright MCP server](https://github.com/microsoft/playwright-mcp)
- [Firecrawl MCP server](https://github.com/firecrawl/firecrawl-mcp-server)
- [Higgsfield MCP documentation](https://higgsfield.ai/creator-hub/help-center/integrations/what-is-higgsfield-mcp)
- [Chrome DevTools MCP server](https://github.com/ChromeDevTools/chrome-devtools-mcp)
- [Claude Code: MCP](https://code.claude.com/docs/en/mcp)
- [Claude Code: persistent instructions](https://code.claude.com/docs/en/memory)
- [Anthropic: Agent Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
- [MCP specification: tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- [MCP specification: resources](https://modelcontextprotocol.io/specification/2025-06-18/server/resources)
- [MCP specification: prompts](https://modelcontextprotocol.io/specification/2025-06-18/server/prompts)
- [MCP specification: transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [MCP security best practices](https://modelcontextprotocol.io/specification/latest/basic/security_best_practices)

## Summary

Universal Agent Control Plane is one canonical registry for the guidance your agents
share. It combines the pieces a multi-host agent setup normally duplicates by hand:

- canonical instructions, Agent Skills, and prompt templates
- deterministic resolution with documented precedence
- native MCP delivery over stdio and Streamable HTTP
- a REST compatibility gateway for clients that cannot speak MCP
- a global installer that projects one source of truth into every host scope
- universal lifecycle hooks normalized across host dialects
- namespaced state with append-only, source-hashed audit records

You author guidance once and validate it once, and each host receives it through the
mechanism that host actually supports — without pretending every host has identical
semantics.

## License

This project is licensed under the **MIT License**. See the [LICENSE](LICENSE) file for details.

Copyright © 2026 Alan Van Zandt

You are free to use, modify, and distribute this software in accordance with the terms of the MIT License.


## Universal tool execution (November 17)

The reusable ToolGateway now provides typed per-tool contracts, validation-before-execution, readiness, execution records/status, bounded output, concurrency/deadline handling and restricted replay. GatewayMCPServer exposes those same contracts as individual MCP tools. MCPConnection supports persistent explicit connections to external stdio/public HTTP servers. The existing guidance/skills/hooks server is unchanged; host applications register their tools through the new library API.

[Agent Playpen](https://github.com/Alan-VZ/Agent-Playpen) integrates the gateway across its selected tools and adds the model adapters/UI. See [API examples, limits, integration evidence and credits](docs/tool-gateway.md). A common interface does not guarantee identical model decisions, reliable final prose, killable Python threads or unchanged live web data. The new execution limits apply to ToolGateway handlers; the older SkillExecutor's synchronous execution limitations remain as documented above.
