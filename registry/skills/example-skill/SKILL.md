---
name: example-skill
description: Demonstrates a portable skill and its allow-listed MCP runner. Use when verifying that skill discovery and execution work.
---

# Example Skill

Call the `skill.run` MCP tool with `skill: "example-skill"` and
`payload: { "name": "<person to greet>" }`. The `name` key is optional; if omitted,
the runner uses a default greeting. Do not include other keys in the payload. The
allow-listed runner returns a greeting and never imports or executes code selected
by the caller.
