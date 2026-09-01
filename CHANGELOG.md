# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Public repository community health files and GitHub templates.
- GitHub Actions test matrix and Dependabot configuration.

### Fixed

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
