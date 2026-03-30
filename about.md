# SPARK About

This document explains the application from the perspective of the two parts that matter most in day-to-day development:

- `server/`
- `electron/`

It intentionally does not document `voice_daemon/`, `llms/`, or other supporting folders in depth.

## What SPARK Is

SPARK is a desktop AI assistant with a Python backend and an Electron desktop client.

- The `server/` side is the intelligence and orchestration layer.
- The `electron/` side is the desktop shell, authentication surface, tray integration, socket bridge, and user interface.

At a high level:

1. Electron authenticates the user and stores tokens locally.
2. Electron connects to the server over REST and Socket.IO.
3. The server handles chat, tool planning, execution flow, and TTS/STT services.
4. Results are streamed back to Electron for UI updates and speech playback.

## Architecture At A Glance

```text
Electron Renderer
  -> calls preload API
Electron Main Process
  -> manages windows, tray, token storage, shared socket connection
  -> talks to
Server (FastAPI + Socket.IO)
  -> auth, chat, orchestration, tools, TTS/STT, persistence
  -> streams results back to
Electron Main -> Renderer
```

## Server

The server is a FastAPI application with a Socket.IO ASGI app mounted beside it. It is the core runtime for application logic.

### Primary Responsibilities

- boot the backend runtime and warm up registered services
- connect to MongoDB and create indexes
- expose HTTP endpoints for auth, chat, system status, TTS, STT, and kernel utilities
- accept authenticated Socket.IO connections from desktop clients
- turn user queries into immediate answers plus executable task plans
- run server-side tools directly and coordinate client-side work when needed
- stream progress, summaries, and TTS events back to the client

### Startup Model

On startup the server:

- runs the auto-initializer registry
- warms key caches, cache clients, TTS, kernel runtime, and the agent system
- optionally loads local ML runtime in `DESKTOP` mode
- connects MongoDB and mounts routes plus `/socket.io`

Important entry points:

- `server/main.py`
- `server/app/main.py`
- `server/app/startup_registrations.py`
- `server/app/auto_initializer.py`

### API Surface

The HTTP API is assembled from multiple routers, and the route prefixes are currently mixed rather than fully uniform. In practice the server exposes things like:

- `/health` and orchestration status endpoints
- `/chat`
- `/tts/stream` and `/tts/complete`
- `/api/stt`
- `/api/v1/auth/*`

Relevant files:

- `server/app/api/routes/__init__.py`
- `server/app/api/routes/system.py`
- `server/app/api/routes/chat.py`
- `server/app/api/routes/stt.py`
- `server/app/api/routes/tts.py`
- `server/app/api/routes/auth.py`

### Real-Time Layer

Socket.IO is the real-time backbone between the backend and the desktop app.

- clients authenticate with a JWT during socket connection
- the server tracks multiple active socket sessions per user
- the server emits query results, task batches, task progress, summaries, and TTS-related events

Relevant files:

- `server/app/socket/server.py`
- `server/app/socket/task_handler.py`
- `server/app/socket/utils.py`

### Query And Execution Pipeline

The server splits user handling into two layers:

- `PQH` handles the immediate conversational response
- `SQH` handles structured tool planning and execution

The flow looks like this:

1. A user query reaches the server.
2. `chat_service.py` builds the conversation context and asks the LLM for a fast response.
3. If tools are needed, `SQH` converts the plan into structured tasks.
4. The orchestrator stores task state, dependencies, and execution order per user.
5. The unified execution engine runs server tasks directly and coordinates client-targeted work based on environment.
6. The server emits progress updates and, when useful, a final spoken summary.

Relevant files:

- `server/app/services/chat/chat_service.py`
- `server/app/services/chat/sqh_service.py`
- `server/app/kernel/execution/orchestrator.py`
- `server/app/kernel/execution/execution_engine.py`
- `server/app/agent/execution_gateway.py`

### How Task Execution Works

Task execution is the bridge between "the model decided something should happen" and "the app safely carried it out."

The execution model is built around a structured task graph, not raw free-form commands. A task can carry:

- a `tool`
- an `execution_target` of `server` or `client`
- `depends_on` links to earlier tasks
- static `inputs`
- `input_bindings` that pull values from previous task outputs
- lifecycle messages
- control metadata such as approval and timeout

In practice, execution works like this:

1. `SQH` turns a tool-using request into structured `Task` objects.
2. The orchestrator registers those tasks into per-user execution state.
3. The orchestrator only releases tasks whose dependencies are already completed.
4. The binding resolver fills dynamic inputs from earlier task outputs using JSONPath-style bindings.
5. The execution engine routes each runnable task:
   - server tasks execute through loaded backend tool instances
   - client tasks execute through the desktop path, depending on environment
6. As tasks move forward, state is updated through statuses such as `pending`, `running`, `waiting`, `emitted`, `completed`, and `failed`.
7. Progress summaries are emitted back to the client during execution.
8. When the graph finishes, the server emits a final summary and, when useful, a spoken completion message.

Important execution-related files:

- `server/app/kernel/execution/execution_models.py`
- `server/app/kernel/execution/orchestrator.py`
- `server/app/kernel/execution/binding_resolver.py`
- `server/app/kernel/execution/execution_engine.py`
- `server/app/socket/task_handler.py`

### Safety Net Around Task Execution

The task system has multiple safety layers so failed or risky actions do not silently spiral into bad state.

#### 1. Structured Tasks Instead Of Raw Execution

The model does not directly "run code." It produces structured task definitions that must match the registered tool system.

- unknown tools are rejected during registration
- execution targets are explicit
- dependencies are explicit
- inputs and bindings are explicit

This sharply limits what the LLM can ask the runtime to do.

#### 2. Tool Registry And Schema Validation

Both server-side and client-side tools validate inputs against schemas before real execution.

- missing required parameters fail early
- wrong input types fail early
- output shape can also be checked

That means many bad plans are stopped before they touch the actual tool implementation.

Relevant files:

- `server/tools/tools/base.py`
- `electron/action_executor/tools/base.py`

#### 3. Dependency And Binding Validation

Tasks can depend on results from earlier tasks. Before a task runs:

- dependencies must already be completed
- bound source tasks must exist
- bound source tasks must have succeeded
- JSONPath bindings must resolve to real values

If a dependency is missing or failed, the task does not run as if everything were fine.

Relevant file:

- `server/app/kernel/execution/binding_resolver.py`

#### 4. Failure Cascading Prevents Hung Task Graphs

If one task fails, dependent tasks are marked failed too instead of sitting in `pending` forever.

This is a quiet but important safety net: the graph resolves to a terminal state instead of getting stuck waiting on work that can never succeed.

Relevant file:

- `server/app/kernel/execution/orchestrator.py`

#### 5. Approval Gates For Sensitive Actions

Tasks can require approval before execution. In those cases the engine:

- marks the task as `waiting`
- asks the connected client for approval
- continues only if approval is granted

If approval is denied or the approval flow is unavailable, the task fails safely instead of continuing.

Relevant files:

- `server/app/kernel/execution/execution_models.py`
- `server/app/kernel/execution/execution_engine.py`
- `server/app/socket/task_handler.py`

#### 6. Timeouts Limit Runaway Work

Tasks can carry `timeout_ms`, and server execution respects that timeout. If a task runs too long, it is failed and surfaced as a timeout rather than blocking the execution loop indefinitely.

Relevant file:

- `server/app/kernel/execution/execution_engine.py`

#### 7. User-Friendly Failure Normalization

Raw tool errors are not exposed to the user as-is. The backend normalizes many common failures into human-friendly explanations, including:

- missing inputs
- bad parameter formats
- failed dependencies
- unavailable tools
- timeouts
- rejected approvals

Those normalized messages are included in execution summaries so the UI can say something understandable instead of dumping technical traces.

Relevant file:

- `server/app/kernel/execution/failure_messages.py`

#### 8. Progress, Summary, And Output Shaping

The task system continuously reports what happened:

- `task:progress` and `task:summary` provide execution counts and failure details
- completed outputs stay in orchestrator state
- the output delivery service exposes only the fields the UI needs by default

This reduces UI guesswork and avoids pushing full raw tool payloads everywhere unless explicitly requested.

Relevant files:

- `server/app/kernel/execution/orchestrator.py`
- `server/app/services/chat/tool_output_delivery_service.py`
- `electron/src/types/socket.types.ts`

#### 9. Spoken Fallback Behavior

After execution, SPARK tries to give a clean spoken wrap-up instead of leaving the user with silent success or silent failure.

- useful completions can be summarized into a short spoken answer
- failures can be rewritten into non-technical speech
- the Electron response layer also suppresses overly technical failure text and falls back to generic speech when needed

Relevant files:

- `server/app/services/chat/task_summary_speech_service.py`
- `electron/src/renderer/hooks/useAiResponseHandler.ts`

#### 10. One Honest Note About The Current Design

The system is moving toward a cleaner unified execution path, but there is still an architectural seam in the desktop stack:

- the server has a unified execution engine with local `DESKTOP` execution support
- Electron still contains an `action_executor/` path and `executeTasks` IPC interface

So the safety net today is strong around validation, orchestration, and failure handling, but the exact client-execution path is still an area of active convergence.

### Persistence And Runtime Dependencies

The server is not just an API wrapper. It owns long-lived runtime concerns:

- MongoDB-backed user and application data
- cache layers and sync behavior
- AI provider configuration
- local model loading in desktop mode
- tool registry loading from `server/tools/`

Relevant files:

- `server/app/config.py`
- `server/app/db/mongo.py`
- `server/app/db/indexes.py`
- `server/app/plugins/tools/registry_loader.py`
- `server/app/plugins/tools/tool_instance_loader.py`

## Electron

The Electron app is the desktop operating surface for SPARK. It owns the user-facing windows, system integration, auth bootstrap, and the bridge between the backend and the React UI.

### Primary Responsibilities

- create and manage desktop windows
- keep a secure preload boundary between renderer and native capabilities
- store access and refresh tokens in the OS credential store
- connect to the server after authentication
- forward socket events and connection state into renderer code
- provide tray controls, device selection, and global shortcuts
- render the main app UI and the floating AI panel

### Window Model

The Electron app uses two window types:

- a frameless main window for welcome, auth, onboarding, and the full home UI
- a transparent always-on-top secondary window for the compact AI panel

On successful auth, the main process connects the shared socket and opens the AI panel window. The main window is hidden behind the scenes and can be reopened from the tray.

Relevant files:

- `electron/src/main/main.ts`
- `electron/src/main/windows/MainWindow.ts`
- `electron/src/main/windows/SecondaryWindow.ts`
- `electron/src/main/services/WindowManager.ts`

### Main Process Responsibilities

The Electron main process is the native control plane. It registers IPC handlers for:

- window actions
- token storage
- media and device queries
- socket bridge operations
- task execution hooks
- secondary window control

It also builds the system tray and registers a global mic shortcut.

Relevant files:

- `electron/src/main/ipc/index.ts`
- `electron/src/main/ipc/windowHandlers.ts`
- `electron/src/main/ipc/socketHandlers.ts`
- `electron/src/main/ipc/taskHandlers.ts`
- `electron/src/main/windows/TrayManager.ts`

### Preload And Security Boundary

The renderer never talks directly to Node or Electron internals. Instead it uses the preload bridge exposed on `window.electronApi`.

That bridge includes:

- token APIs
- media and permission APIs
- socket emit and socket event subscriptions
- tray event subscriptions
- window controls
- task execution IPC

Relevant file:

- `electron/src/main/preload.cts`

### Auth And Token Lifecycle

Electron stores tokens with `keytar`, then uses them from the renderer through the preload bridge.

The renderer boot flow is:

1. check for a valid stored access token
2. refresh if needed
3. fetch the current user profile
4. call `onAuthSuccess()` in the preload API if the session is valid
5. let the main process open the AI panel and connect the shared socket

Relevant files:

- `electron/src/main/services/TokenManager.ts`
- `electron/src/renderer/hooks/useAuthRouting.ts`
- `electron/src/renderer/utils/axiosConfig.ts`

### Socket Integration

Electron keeps one shared socket connection in the main process instead of opening separate renderer sockets.

That shared service:

- connects with the stored access token
- tracks connection state
- refreshes the token before reconnect attempts
- forwards all socket events to renderer windows through IPC
- routes TTS-style events to the preferred active window when possible
- forwards mic control events specially

Relevant files:

- `electron/src/main/services/SocketService.ts`
- `electron/src/renderer/context/socketContextProvider.tsx`

### Renderer Responsibilities

The renderer is a React + TypeScript app built with Vite. It owns the visible user experience.

Core responsibilities:

- routing between welcome, auth, onboarding, home, and AI panel views
- syncing device state into Redux
- responding to tray and shortcut events
- consuming forwarded socket events
- speaking backend answers through the local TTS playback context

Relevant files:

- `electron/src/renderer/App.tsx`
- `electron/src/renderer/components/layout/AppInitializer.tsx`
- `electron/src/renderer/hooks/useAiResponseHandler.ts`
- `electron/src/renderer/store/features/localState/localSlice.ts`

### UI Surfaces

There are two major renderer experiences:

- `Home`: the full desktop app surface
- `AiPanel`: the floating compact assistant window

Both surfaces can subscribe to AI responses through the shared socket context and response handler hooks.

Relevant files:

- `electron/src/renderer/pages/Home.tsx`
- `electron/src/renderer/pages/AiPanel/AiPanel.tsx`
- `electron/src/renderer/pages/Onboarding/index.tsx`

## How Server And Electron Fit Together

This is the practical integration path for the current codebase:

1. The server starts and exposes FastAPI routes plus Socket.IO.
2. Electron launches and checks whether the user already has a valid session.
3. If authenticated, Electron asks the main process to connect the shared socket.
4. Renderer code talks to the backend through:
   - REST for auth and profile flows
   - Socket.IO for query results, task progress, and streamed events
   - preload IPC for native desktop actions
5. The server remains the source of truth for orchestration and user-scoped task state.

## Important Implementation Note

There is an active architectural seam around client-side task execution:

- the server now has a unified execution engine that can execute client-targeted work locally in `DESKTOP` mode
- Electron also still exposes an `executeTasks` IPC path and includes `action_executor/` code for local automation

So when working in this area, treat task execution as an integration boundary that is still evolving rather than a fully settled single-path design.

## Suggested Reading Order For New Contributors

If you want to understand the app quickly, read files in this order:

1. `server/app/main.py`
2. `server/app/services/chat/chat_service.py`
3. `server/app/services/chat/sqh_service.py`
4. `server/app/kernel/execution/execution_engine.py`
5. `electron/src/main/main.ts`
6. `electron/src/main/services/SocketService.ts`
7. `electron/src/main/preload.cts`
8. `electron/src/renderer/components/layout/AppInitializer.tsx`
9. `electron/src/renderer/context/socketContextProvider.tsx`
10. `electron/src/renderer/hooks/useAiResponseHandler.ts`

## Minimal Local Dev Entry Points

For local development, the two core processes are:

```bash
# server
cd server
python main.py

# electron
cd electron
npm install
npm run dev
```

That is the shortest useful mental model of the application: the server is the orchestration brain, and Electron is the desktop runtime and presentation layer.
