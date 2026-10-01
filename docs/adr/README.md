# Architecture Decision Records

| # | Decision | Status |
| --- | --- | --- |
| 0001 | [Rebuild as a layered engine instead of patching v2](0001-rebuild-as-layered-engine.md) | Accepted |
| 0002 | [Keep Python for the engine; manage it with uv; serve with FastAPI](0002-python-uv-fastapi.md) | Accepted |
| 0003 | [Own the BLE transport and protocol encoders; drop the idotmatrix dependency](0003-own-ble-transport.md) | Accepted |
| 0004 | [Latest-frame-wins device scheduler](0004-latest-frame-wins.md) | Accepted |
| 0005 | [Bake deterministic animations to GIFs the panel plays natively](0005-clips-baked-to-native-gif.md) | Accepted |
| 0006 | [Apps are plugins with pydantic settings; the UI is generated from the schema](0006-schema-driven-apps.md) | Accepted |
| 0007 | [Studio in React + TypeScript + Vite + Tailwind v4, frames over one WebSocket](0007-react-vite-tailwind-studio.md) | Accepted |
| 0008 | [MCP server is a thin client over the engine's HTTP API](0008-mcp-as-http-client.md) | Accepted |
| 0009 | [Pace packets and use the panel's acks for flow control](0009-paced-writes-and-ack-flow-control.md) | Accepted |
| 0010 | [Provider events and Autopilot are engine-level](0010-events-and-autopilot-in-engine.md) | Accepted |
| 0011 | [Host the whole engine on an Android phone as an app (Chaquopy + a Kotlin BLE bridge)](0011-android-host-app.md) | Proposed |

New decisions: copy the format, next number, status `Proposed` → `Accepted`. Never rewrite an accepted ADR; supersede it.
