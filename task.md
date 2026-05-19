# Server Tool Execution Overhaul — Task Tracker

## Phase 1: Non-Blocking Tools
- [/] Add `_run_subprocess()` and `_async_sleep()` to `BaseTool`
- [ ] Migrate `system/shell_agent.py` — async subprocess
- [ ] Migrate `system/sound.py`
- [ ] Migrate `system/clipboard.py`
- [ ] Migrate `system/brightness.py`
- [ ] Migrate `system/battery.py`
- [ ] Migrate `system/network.py`
- [ ] Migrate `system/screenshot.py`
- [ ] Migrate `system/screen.py`
- [ ] Migrate `system/notification.py`
- [ ] Migrate `system/app.py`

## Phase 2: Artifact Context + Smart Directory Opening
- [ ] Create `artifact_context_service.py`
- [ ] Modify `sqh_prompt.py` — inject artifact context
- [ ] Modify `sqh_service.py` — pass user_id
- [ ] Improve `spark_data_open` registry entry

## Phase 3: Shell Agent V2
- [ ] Async subprocess engine with streaming
- [ ] Smarter LLM planning prompt (no limits, project init, error recovery)
- [ ] Per-step dynamic timeout from planner
- [ ] Network auto-detection
- [ ] Approval via notification (already wired)

## Phase 4: ToolContextService
- [ ] Create `tool_context_service.py`
- [ ] Wire into execution engine
