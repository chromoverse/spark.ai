# Client Tool Execution (Mobile/Desktop Remote)

This document describes how a remote client (mobile, web, desktop companion) executes tools emitted by the server.

## 1. Server-side flow

1. SQH generates tasks and registers them in orchestrator state.
2. `ExecutionEngine` picks executable tasks.
3. For `execution_target="client"` in production mode, engine emits through `SocketTaskHandler`.
4. Server sends one of:
   - `task:execute` for a single task
   - `task:execute_batch` for a dependency chain batch

Source references:
- [execution_engine.py](/d:/siddhant-files/projects/ai_assistant/ai_local/server/app/kernel/execution/execution_engine.py)
- [task_handler.py](/d:/siddhant-files/projects/ai_assistant/ai_local/server/app/socket/task_handler.py)

## 2. Socket events and payloads

### `task:execute`
```json
{
  "user_id": "user_123",
  "tasks": [
    {
      "task": {
        "task_id": "task_1",
        "tool": "file_create",
        "execution_target": "client",
        "depends_on": [],
        "inputs": { "path": "..." }
      },
      "status": "emitted"
    }
  ]
}
```

### `task:execute_batch`
```json
{
  "user_id": "user_123",
  "tasks": [ /* multiple TaskRecord items */ ]
}
```

Notes:
- `server_completed_dependencies` may be added per task when server-side deps are already done.
- Client should execute tasks in dependency-safe order if a batch is received.

## 3. Client responsibilities

1. Listen for `task:execute` and `task:execute_batch`.
2. Execute each tool locally (platform APIs, file system, app control, etc.).
3. Return result for each task:
   - `task:result` (single)
   - `task:batch_results` (many)

### `task:result` payload
```json
{
  "user_id": "user_123",
  "task_id": "task_1",
  "result": {
    "success": true,
    "data": {},
    "error": null
  }
}
```

### `task:batch_results` payload
```json
{
  "user_id": "user_123",
  "results": [
    { "task_id": "task_1", "result": { "success": true, "data": {}, "error": null } },
    { "task_id": "task_2", "result": { "success": false, "data": {}, "error": "..." } }
  ]
}
```

## 4. Server acknowledgment handling

- Server receives result events in `SocketTaskHandler`.
- Orchestrator updates each task as completed/failed.
- Dependent tasks are automatically unblocked or failed-cascaded.

## 5. Mobile implementation checklist

1. Authenticate socket session and map it to `user_id`.
2. Implement event listeners for `task:execute` and `task:execute_batch`.
3. Implement a local tool runner map: `tool_name -> handler`.
4. Return deterministic JSON outputs (`success`, `data`, `error`).
5. Retry failed network sends for `task:result`.
6. Keep client clock-independent; server owns lifecycle state.
