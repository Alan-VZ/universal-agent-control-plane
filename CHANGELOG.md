# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Universal lifecycle hooks: one canonical event set (`session_start`, `session_end`,
  `user_prompt`, tool-use, sub-agent, and notification events) normalized across the
  GitHub Copilot and Claude Code hook dialects.
- Hook delivery on three surfaces: the `uacp hook <event>` CLI command, `GET /hooks`
  and `POST /hooks/{event}` REST routes, and the `hook_list`, `hook_emit`, and
  `journal_recent` MCP tools.
- Session journal with anti-recursion (sub-agents never summarize themselves) and
  anti-bloat rules (duplicate events suppressed, short summaries rejected).
- Managed hook configuration written for both hosts by `uacp install-global`, removed
  again by `uacp uninstall-global` without touching user-authored hooks.
- Public repository community health files and GitHub templates.
- GitHub Actions test matrix and Dependabot configuration.
- GitHub-renderable architecture diagram embedded in the README.

### Security

- Skill and hook handler executions are now audited with a SHA-256 hash of the runner
  source that actually ran, closing a time-of-check/time-of-use gap where hot-reloading
  could execute code other than the module validated at allow-list time.
- Skill execution is now recorded in the audit table at all; previously only state
  writes and hook events were audited.

### Fixed

- `orchestrate` now executes the target skill independently for each recipient (three
  separate runs for `broadcast`) instead of running it once and relabeling a single
  result for every recipient. The response reports `executions` keyed by recipient plus
  `succeeded`/`failed` lists, and one recipient's failure no longer prevents the others
  from executing.
- Corrected invalid JSON in the README client configuration example, where the `env`
  object was closed with `]`.
- Aligned README prose with the shipped `skill_run` tool name.
- Replaced the aspirational security baseline list with a status table separating
  implemented controls from planned ones.
- Scoped the multi-agent orchestration non-goal so it no longer contradicts the shipped
  single-step `orchestrate` routing primitive.
- Listed the hook and journal tools in the client configuration tool summary.
- Architecture diagram now shows the installer-to-registry link, the localhost trust
  boundary around the REST gateway, project override precedence, and a legend entry for
  every line style in use.
- Restored Python 3.10 compatibility for structured log timestamps.
- Made global installer tests use the active interpreter on clean CI runners.

## [0.1.0] - 2026-09-01

### Added

- Canonical registry for shared instructions, Agent Skills, and prompt templates.
- Native MCP server over stdio and Streamable HTTP.
- FastAPI REST compatibility gateway and OpenAPI documentation.
- Allow-listed skill execution with source modification hot-reloading.
- Namespaced SQLite state and structured rotating logs.
- Global installer for VS Code, Copilot Agent Host, Claude Code, and Agent Skills scopes.
- Dry-run, sync, doctor, conflict detection, and managed-only uninstall commands.
- Architecture documentation and automated tests.

[Unreleased]: https://github.com/Alan-VZ/universal-agent-control-plane/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Alan-VZ/universal-agent-control-plane/releases/tag/v0.1.0
