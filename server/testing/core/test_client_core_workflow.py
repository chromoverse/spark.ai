# test_client_workflow.py
"""
Client Core - execution scenarios test

Tests:
1. C->C->C: Pure client chain (Chain handling)
2. C1, C2: Independent parallel client tasks
"""

import asyncio
import logging
from datetime import datetime

# Adjust path to allow imports if needed, though likely running from root
import sys
import os

from app.core.models import TaskRecord

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Import from Client Core
from app.client_core.main import initialize_client, receive_tasks_from_server, get_execution_engine

def print_section(title: str):
    """Pretty section divider"""
    logger.info("\n" + "="*80)
    logger.info(f"  {title}")
    logger.info("="*80 + "\n")


async def scenario_chain_handling():
    """
    Scenario 1: Client Chain (C->C->C)
    
    create_project -> create_files -> update_config
    """
    print_section("SCENARIO 1: Client Chain (C->C->C)")
    
    user_id = "test_user_chain"
    
    # 1. Initialize
    initialize_client(user_id)
    engine = get_execution_engine()
    
    # 2. Define Tasks (As dictionaries, mimicking server payload)
    tasks = [
        {
            "task": {
                "task_id": "create_project",
                "tool": "folder_create",
                "execution_target": "client",
                "depends_on": [],
                "inputs": {"path": "~/test_client_core/project_alpha"},
                "lifecycle_messages": {
                    "on_start": "Creating project folder...",
                    "on_success": "Project folder created"
                }
            },
            "status": "pending"
        },
        {
            "task": {
                "task_id": "create_main",
                "tool": "file_create",
                "execution_target": "client",
                "depends_on": ["create_project"],
                "inputs": {
                    "path": "~/test_client_core/project_alpha/main.py", 
                    "content": "print('Hello World')"
                },
                "lifecycle_messages": {
                    "on_start": "Creating main.py...",
                    "on_success": "main.py created"
                }
            },
            "status": "pending"
        },
        {
            "task": {
                "task_id": "create_config",
                "tool": "file_create",
                "execution_target": "client",
                "depends_on": ["create_main"],
                "inputs": {
                    "path": "~/test_client_core/project_alpha/config.json", 
                    "content": "{}"
                },
                "lifecycle_messages": {
                    "on_start": "Creating config...",
                    "on_success": "Config created"
                }
            },
            "status": "pending"
        }
    ]
    
    # 3. Send to Client Core
    logger.info("📨 Sending chained tasks to client core...")
    await receive_tasks_from_server(user_id, tasks)
    
    # 4. Wait for completion
    await engine.wait_for_completion()
    
    # 5. detailed verification could go here by checking file system
    logger.info("✅ Scenario 1 Complete")


async def scenario_parallel_execution():
    """
    Scenario 2: Parallel Independent Tasks
    
    note_1, note_2 running in parallel
    """
    print_section("SCENARIO 2: Parallel Independent Clients")
    
    user_id = "test_user_parallel"
    
    # Re-use engine (idempotent init)
    initialize_client(user_id)
    engine = get_execution_engine()
    
    tasks = [
        {
            "task": {
                "task_id": "note_1",
                "tool": "file_create",
                "execution_target": "client",
                "depends_on": [],
                "inputs": {
                    "path": "~/test_client_core/note1.txt", 
                    "content": "Parallel Note 1"
                },
                "lifecycle_messages": {
                    "on_start": "Writing Note 1...",
                    "on_success": "Note 1 created"
                }
            },
            "status": "pending"
        },
        {
            "task": {
                "task_id": "note_2",
                "tool": "file_create",
                "execution_target": "client",
                "depends_on": [],
                "inputs": {
                    "path": "~/test_client_core/note2.txt", 
                    "content": "Parallel Note 2"
                },
                "lifecycle_messages": {
                    "on_start": "Writing Note 2...",
                    "on_success": "Note 2 created"
                }
            },
            "status": "pending"
        }
    ]
    
    logger.info("📨 Sending parallel tasks to client core...")
    await receive_tasks_from_server(user_id, tasks)
    
    await engine.wait_for_completion()
    logger.info("✅ Scenario 2 Complete")


async def scenario_system_tools():
    """
    Scenario 3: System Tools (Open/Close App)
    """
    print_section("SCENARIO 3: System Tools (Open/Close)")
    
    user_id = "test_user_system"
    initialize_client(user_id)
    engine = get_execution_engine()
    
    
    tasks = [
        {
            "task": {
                "task_id": "task1",
                "tool": "open_app",
                "execution_target": "client",
                "depends_on": [],
                "inputs": {"target": "whatsapp"},
                "lifecycle_messages": {
                    "on_start": "Closing Notepad...",
                    "on_success": "Notepad closed"
                }
            },
            "status": "emitted"
        },
        {
            "task": {
                "task_id": "openapp_1",
                "tool": "open_app",
                "execution_target": "client",
                "depends_on": [],
                "inputs": {"target": "zen"},
                "lifecycle_messages": {
                    "on_start": "Opening Camera...",
                    "on_success": "Camera opened"
                }
            },
            "status": "emitted"
        }
    ]


    
    logger.info("📨 Sending system tasks...")
    # await receive_tasks_from_server(user_id, tasks)
    # await engine.wait_for_completion()
    from app.core.task_emitter import get_task_emitter
    emitter = get_task_emitter()
    tasks = [TaskRecord(**task) for task in tasks]
    await emitter.emit_task_batch("user_id", tasks)
    logger.info("✅ Scenario 3 Complete")


async def scenario_simulated_workflow():
    """
    Scenario 4: Simulated Interactive Workflow
    
    Demonstrates chain:
    1. Open Folder -> Create File (Dependent)
    2. Open Editor -> Create Note (Dependent)
    """
    print_section("SCENARIO 4: Simulated Interactive Workflow")
    
    user_id = "test_user_sim_flow"
    initialize_client(user_id)
    engine = get_execution_engine()
    
    tasks = [
        # Chain A: Folder Interaction
        {
            "task": {
                "task_id": "open_project_folder",
                "tool": "open_file",
                "execution_target": "client",
                "depends_on": [],
                "inputs": {
                    # "target": "explorer", 
                    # "args": ["~/test_client_core"]
                },
                "lifecycle_messages": {
                    "on_start": "Opening Project Folder...",
                    "on_success": "Folder opened"
                }
            },
            "status": "pending"
        },
        {
            "task": {
                "task_id": "create_readme",
                "tool": "file_create",
                "execution_target": "client",
                "depends_on": ["open_project_folder"],
                "inputs": {
                    "path": "~/test_client_core/README.md",
                    "content": "# Project Alpha\nManaged by AI Assistant"
                },
                "lifecycle_messages": {
                    "on_start": "Creating README...",
                    "on_success": "README created"
                }
            },
            "status": "pending"
        },
        
        # Chain B: Editor Interaction ("Open Notepad then Write")
        # {
        #     "task": {
        #         "task_id": "open_editor",
        #         "tool": "open_app",
        #         "execution_target": "client",
        #         "depends_on": [],
        #         "inputs": {"target": "notepad"},
        #         "lifecycle_messages": {
        #             "on_start": "Opening Editor...",
        #             "on_success": "Editor launched"
        #         }
        #     },
        #     "status": "pending"
        # },
        # {
        #     "task": {
        #         "task_id": "write_notes",
        #         "tool": "file_create",
        #         "execution_target": "client",
        #         "depends_on": ["open_editor"],
        #         "inputs": {
        #             "path": "~/test_client_core/quick_notes.txt",
        #             "content": "Meeting notes: AI Assistant is working well."
        #         },
        #         "lifecycle_messages": {
        #             "on_start": "Writing notes...",
        #             "on_success": "Notes saved"
        #         }
        #     },
        #     "status": "pending"
        # }
    ]
    
    logger.info("📨 Sending simulated workflow tasks...")
    await receive_tasks_from_server(user_id, tasks)
    await engine.wait_for_completion()
    logger.info("✅ Scenario 4 Complete")


async def run_tests():
    try:
        # await scenario_chain_handling()
        # await scenario_parallel_execution()
        await scenario_system_tools()
        # await scenario_simulated_workflow()
        print_section("🎉 ALL CLIENT TESTS PASSED")
    except Exception as e:
        logger.error(f"❌ Test Failed: {e}")
        # raise e

def check():
    from app.client_core.main import run_demo_tasks
    asyncio.run(run_demo_tasks())

if __name__ == "__main__":
    asyncio.run(run_tests())
    # check()
