# Repository Agent Instructions

## Documentation synchronization

Every implementation change must update all directly affected documentation in the same
change. Documentation is part of the definition of done.

Before completing a change:

- update `README.md` when capabilities, setup, commands, endpoints, configuration, or
  repository structure change
- update architecture diagrams when components, data flow, transports, integrations,
  persistence, or trust boundaries change
- update configuration examples when entry points, environment variables, paths, or
  dependencies change
- remove stale claims about planned or implemented behavior
- validate documentation examples against the working implementation
- run the applicable diagram checks after modifying diagram HTML

Do not report an implementation task as complete while directly related documentation is
stale.
