# ADR 0006: Apps are plugins with pydantic settings; the UI is generated from the schema

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

v2 hand-built HTML for each feature, so every new capability required frontend work and the UI drifted from the backend.

## Decision

Every app is a class with a `Settings` model. `/api/meta` publishes the JSON schema; the studio renders forms
from it (`SchemaForm.tsx`), the MCP server exposes it to agents, the tests enumerate every option. `Choice`,
`Color` and `format: media` extend the schema with UI hints. Apps can live in `plugins/` without touching the repo.

## Consequences

+ New capability = one Python file; the studio, MCP and tests pick it up.
− Very custom controls need a new schema `format` + a SchemaForm branch.
