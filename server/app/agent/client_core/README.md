# Client Core (Standalone & Server Mode)

This directory contains the client-side execution engine for the AI Assistant.

## Modes

### 1. Server Integration (Default)
When running as part of the backend server (`Desktop` environment), `client_core` uses shared tools and registry located in `app/agent/shared/`.

- Tools: `app/agent/shared/tools/`
- Registry: `app/agent/shared/registry/`

### 2. Standalone Mode (Legacy)
To run `client_core` independently (e.g., packaged in an Electron app), you must restore the local tools and registry from the `legacy/` backup:

1. Copy content of `legacy/tools` to `client_core/tools`.
2. Copy content of `legacy/registry` to `client_core/registry`.
3. Copy content of `legacy/utils` to `client_core/utils`.
4. Ensure your python environment can resolve dependencies.

The code attempts to import from `app.agent.shared` first. If missing, it falls back to local imports (if files exist).
