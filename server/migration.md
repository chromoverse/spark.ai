# Tool System Migration Plan

## Current State (messy but working)

```
server/tools/
├── registry/
│   ├── tool_registry.json    ← source of truth (76 tools, full schemas)
│   └── tool_index.json       ← generated summary (name + description + triggers)
├── manifest.json             ← another generated summary
├── tools/                    ← actual tool implementations
│   ├── ai/
│   ├── file_system/
│   ├── system/
│   ├── communication/
│   └── ...
└── base.py                   ← BaseTool class

server/plugins/               ← separate plugin system (skills, installed plugins)
├── manager.py
├── models.py
├── skills/
└── installed/

server/app/plugins/           ← yet another plugin reference inside app
```

**Problems:**
- 3 JSON files that duplicate tool info
- Tools and plugins are separate systems with different loading paths
- Adding a tool requires editing tool_registry.json + creating the .py file + sometimes manifest.json
- Categories are hardcoded in a separate file
- No auto-discovery

---

## Target State

```
server/tools/
├── system_control/
│   ├── app_open/
│   │   ├── manifest.yaml
│   │   └── handler.py
│   ├── brightness_increase/
│   │   ├── manifest.yaml
│   │   └── handler.py
│   └── ...
├── file_management/
│   ├── folder_organize/
│   │   ├── manifest.yaml
│   │   └── handler.py
│   └── ...
├── communication/
├── media/
├── web_knowledge/
├── ai_content/
├── automation/
├── spark_internal/
├── clipboard_notify/
└── _base.py                  ← BaseTool class
```

**Each tool = one folder:**
```
folder_organize/
├── manifest.yaml       ← single source of truth
└── handler.py          ← the tool class
```

**manifest.yaml:**
```yaml
name: folder_organize
category: file_management
description: "Organize folder structure using LLM categorization"
version: "1.0.0"
execution_target: server

inputs:
  path:
    type: string
    required: true
    description: "Folder path to organize"

outputs:
  files_affected:
    type: integer
  action_performed:
    type: string
  restore_script:
    type: string

example_triggers:
  - "organize my desktop"
  - "clean up my downloads folder"

permissions:
  - filesystem.read
  - filesystem.write
  - shell.execute
```

---

## Migration Steps (in order)

### Phase 1: Auto-discovery loader (no file moves)
- [ ] Build a `ToolScanner` that reads manifest.yaml from tool folders
- [ ] Generate tool_registry.json and tool_index.json automatically at startup
- [ ] Remove manual JSON editing from the "add a tool" workflow
- [ ] Keep old JSON files as cache (regenerated on change)

### Phase 2: Manifest per tool
- [ ] Create manifest.yaml for each of the 76 tools (script can generate from current registry)
- [ ] Move category, description, inputs, outputs, example_triggers INTO manifest.yaml
- [ ] Remove tool_registry.json as source of truth (now auto-generated)
- [ ] Remove manifest.json (redundant)

### Phase 3: Folder restructure
- [ ] Move tools into category-based folders (system_control/, file_management/, etc.)
- [ ] Update import paths (BaseTool import changes)
- [ ] Test all 76 tools still execute correctly

### Phase 4: Merge plugins into tools
- [ ] Skills become tools with `type: skill` in manifest
- [ ] Installed plugins become tools with `type: plugin` in manifest
- [ ] Kill server/plugins/ and server/app/plugins/ as separate systems
- [ ] One loader, one registry, one execution path

### Phase 5: Hot-reload
- [ ] Watch tool folders for changes (watchdog)
- [ ] New tool folder dropped → auto-registered without restart
- [ ] Tool folder deleted → auto-deregistered
- [ ] manifest.yaml changed → tool reloaded

---

## Rules for the new system

1. **One tool = one folder.** No exceptions.
2. **manifest.yaml is the single source of truth.** No other config file needed.
3. **Category lives in the manifest.** Auto-discovered, never hardcoded elsewhere.
4. **No JSON editing to add a tool.** Drop a folder, server picks it up.
5. **BaseTool stays.** All tools extend it. The interface doesn't change.
6. **Execution engine doesn't change.** It receives tool name + inputs, executes. The discovery layer is what changes.

---

## Estimated effort

| Phase | Time | Risk |
|-------|------|------|
| Phase 1 | 2-3 hours | Low (additive, no breaking changes) |
| Phase 2 | 3-4 hours | Low (generate manifests from existing data) |
| Phase 3 | 2-3 hours | Medium (import path changes) |
| Phase 4 | 4-6 hours | Medium (merging two systems) |
| Phase 5 | 2-3 hours | Low (additive) |

Total: ~2 days of focused work. Do it in a feature branch.
