# Security Policy

## Supported versions

This project is currently in alpha. Security fixes are applied to the latest code on the
`main` branch and the most recent release.

## Reporting a vulnerability

Do not open a public issue for a vulnerability.

Use GitHub's private vulnerability reporting feature on the repository's **Security**
tab. Include:

- the affected version or commit
- reproduction steps or a proof of concept
- the expected impact
- any suggested mitigation

You should receive an acknowledgement within seven days. A fix and disclosure timeline
will be coordinated based on severity and complexity.

## Security boundaries

The default stdio transport is local. The optional HTTP gateway binds to localhost and is
not hardened for untrusted networks. Do not expose it remotely without authentication,
authorization, TLS, origin validation, and appropriate network controls.

Skill runners are executable code. Review registry changes before installation and only
allow runners from trusted sources.
