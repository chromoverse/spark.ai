# Kernel Package Layout

The `kernel` package is split by responsibility:

- `contracts/`
  - Shared kernel event contracts (`KernelEvent`).
- `eventing/`
  - Event bus and publish/subscribe wiring.
- `execution/`
  - Task orchestration and execution runtime:
    - execution models
    - orchestrator
    - execution engine
    - client/server executors
    - task emitter
- `persistence/`
  - Event persistence routing, stats storage, and query services.
- `observability/`
  - Structured log indexing and logging setup.
- `runtime/`
  - Kernel runtime bootstrap/shutdown wiring.

Top-level `kernel/__init__.py` re-exports the public kernel API.
