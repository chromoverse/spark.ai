# test_real_world_scenarios.py


import asyncio
import logging
import json
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

from app.plugins.tools.registry_loader import load_tool_registry
from app.kernel.execution.orchestrator import init_orchestrator
from app.kernel.execution.execution_engine import init_execution_engine
from app.kernel.execution.server_executor import init_server_executor
from app.kernel.execution.task_emitter import get_task_emitter
from app.kernel.execution.execution_models import Task, LifecycleMessages
from app.plugins.tools.tool_instance_loader import load_all_tools


def print_section(title: str):
    """Pretty section divider"""
    logger.info("\n" + "="*80)
    logger.info(f"  {title}")
    logger.info("="*80 + "\n")


async def scenario_1_server_chain():
    """
    Scenario 1: S→S (Server Chain)
    
    search_company → fetch_details
    
    Tests:
    - Server task dependency
    - Input binding from server to server
    - Sequential server execution
    """
    print_section("SCENARIO 1: Server Chain (S→S)")
    
    orchestrator = init_orchestrator()
    server_executor = init_server_executor()
    execution_engine = init_execution_engine()
    execution_engine.set_server_executor(server_executor)
    # ✅ Add mock client emitter
    mock_emitter = get_task_emitter()
    execution_engine.set_client_emitter(mock_emitter)
    
    user_id = "siddthecoder"
    
    tasks = [
        Task(
            task_id="search_company",
            tool="web_research",
            execution_target="server",
            depends_on=[],
            inputs={"query": "what did balen shah said in speech at janakpur?"},
            lifecycle_messages=LifecycleMessages(
                on_start="🔍 Searching for company info...",
                on_success="✅ Found company information",
                on_failure="❌ Search failed"
            )
        ),
        # Task(
        #     task_id="fetch_details",
        #     tool="web_scrape",
        #     execution_target="server",
        #     depends_on=["search_company"],
        #     inputs={"query": "Anthropic Claude API pricing"},
        #     lifecycle_messages=LifecycleMessages(
        #         on_start="📡 Fetching additional details...",
        #         on_success="✅ Details retrieved",
        #         on_failure="❌ Fetch failed"
        #     )
        # ),
    ]
    
    await orchestrator.register_tasks(user_id, tasks)
    engine_task = await execution_engine.start_execution(user_id)
    await engine_task
    
    summary = await orchestrator.get_execution_summary(user_id)
    logger.info(f"\n📊 Summary: {summary}")
    
    return summary


async def scenario_2_parallel_servers():
    """
    Scenario 2: S1, S2 (Independent Parallel Server Tasks)
    
    search_weather + search_stocks (parallel)
    
    Tests:
    - Parallel server execution
    - No dependencies
    - Concurrent tool execution
    """
    print_section("SCENARIO 2: Parallel Independent Servers (S1, S2)")
    
    orchestrator = init_orchestrator()
    server_executor = init_server_executor()
    execution_engine = init_execution_engine()
    execution_engine.set_server_executor(server_executor)
    
    user_id = "scenario_2"
    
    tasks = [
        Task(
            task_id="search_weather",
            tool="web_search",
            execution_target="server",
            depends_on=[],
            inputs={"query": "Tokyo weather today"},
            lifecycle_messages=LifecycleMessages(
                on_start="🌤️  Checking weather...",
                on_success="✅ Weather data retrieved"
            )
        ),
        Task(
            task_id="search_stocks",
            tool="web_search",
            execution_target="server",
            depends_on=[],
            inputs={"query": "NASDAQ today"},
            lifecycle_messages=LifecycleMessages(
                on_start="📈 Fetching stock data...",
                on_success="✅ Stock data retrieved"
            )
        ),
        Task(
            task_id="search_crypto",
            tool="web_search",
            execution_target="server",
            depends_on=[],
            inputs={"query": "Bitcoin price"},
            lifecycle_messages=LifecycleMessages(
                on_start="₿ Checking crypto prices...",
                on_success="✅ Crypto data retrieved"
            )
        ),
    ]
    
    await orchestrator.register_tasks(user_id, tasks)
    
    start_time = datetime.now()
    engine_task = await execution_engine.start_execution(user_id)
    await engine_task
    duration = (datetime.now() - start_time).total_seconds()
    
    summary = await orchestrator.get_execution_summary(user_id)
    logger.info(f"\n📊 Summary: {summary}")
    logger.info(f"⏱️  Total execution time: {duration:.2f}s (should be ~same as single task due to parallelism)")
    
    return summary

async def scenario_3_server_to_client_chain():
    """
    Scenario 3: S→C→C (Server triggers Client Chain)
    
    fetch_data → open_notepad
    
    Tests:
    - Server to client handoff
    - Client task execution after server completion
    - Input binding across execution targets
    """
    print_section("SCENARIO 3: Server to Client Chain (S→C)")
    
    orchestrator = init_orchestrator()
    server_executor = init_server_executor()
    execution_engine = init_execution_engine()
    execution_engine.set_server_executor(server_executor)
    
    # ✅ Add mock client emitter
    mock_emitter = get_task_emitter()
    execution_engine.set_client_emitter(mock_emitter)
    
    user_id = "scenario_3"
    
    tasks = [
        Task(
            task_id="fetch_data",
            tool="web_search",
            execution_target="server",
            depends_on=[],
            inputs={"query": "latest AI research papers"},
            lifecycle_messages=LifecycleMessages(
                on_start="📥 Fetc`hing research data from web...",
                on_success="✅ Data fetched successfully"
            )
        ),
        Task(
            task_id="open_notepad",
            tool="open_app",
            execution_target="client",
            depends_on=[],
            inputs={"target": "notepad"},
            input_bindings={},
            lifecycle_messages=LifecycleMessages(
                on_start="📁 Opening Notepad on client...",
                on_success="✅ Notepad opened successfully"
            )
        ),
        Task(
            task_id="open_vscode",
            tool="open_app",
            execution_target="client",
            depends_on=[],
            inputs={"target": "vscode"},
            input_bindings={},
            lifecycle_messages=LifecycleMessages(
                on_start="📁 Opening VSCode on client...",
                on_success="✅ VSCode opened successfully"
            )
        ),
        Task(
            task_id="open_zen",
            tool="open_app",
            execution_target="client",
            depends_on=[],
            inputs={"target": "Zen"},
            input_bindings={},
            lifecycle_messages=LifecycleMessages(
                on_start="📁 Opening Notepad on client...",
                on_success="✅ Notepad opened successfully"
            )
        )
    ]
    
    await orchestrator.register_tasks(user_id, tasks)
    engine_task = await execution_engine.start_execution(user_id)
    await engine_task
    
    summary = await orchestrator.get_execution_summary(user_id)
    logger.info(f"\n📊 Summary: {summary}")
    
    # Verify server→client handoff
    state = orchestrator.get_state(user_id)
    if state:
        fetch_task = state.get_task("fetch_data")
        notepad_task = state.get_task("open_notepad")
        
        if fetch_task and notepad_task:
            logger.info(f"\n🔗 Server→Client handoff verification:")
            logger.info(f"   fetch_data completed at: {fetch_task.completed_at}")
            logger.info(f"   open_notepad emitted at: {notepad_task.emitted_at}")
            logger.info(f"   ✅ Client task emitted after server completion!")
        else:
            logger.warning(f"⚠️ Tasks not found - fetch_task: {fetch_task}, notepad_task: {notepad_task}")
    
    return summary


async def scenario_4_pure_client_chain():
    """
    Scenario 4: C→C→C (Pure Client Chain)
    
    create_project → create_files → update_config
    
    Tests:
    - Client-only workflow
    - Multi-step client chain
    - Batch emission optimization
    - Local dependency handling
    """
    print_section("SCENARIO 4: Pure Client Chain (C→C→C)")
    
    orchestrator = init_orchestrator()
    execution_engine = init_execution_engine()
    # ✅ Add mock client emitter  
    mock_emitter = get_task_emitter()
    execution_engine.set_client_emitter(mock_emitter)
    # ✅ Add mock client emitter
    mock_emitter = get_task_emitter()
    execution_engine.set_client_emitter(mock_emitter)
    
    user_id = "scenario_4"
    
    tasks = [
        Task(
            task_id="create_project",
            tool="file_open",
            execution_target="client",
            depends_on=[],
            inputs={"path": "~/my_project"},
            lifecycle_messages=LifecycleMessages(
                on_start="📁 Creating project folder...",
                on_success="✅ Project folder created"
            )
        ),
        Task(
            task_id="create_files",
            tool="file_create",
            execution_target="client",
            depends_on=["create_project"],
            inputs={"path": "~/my_project/main.py", "content": "# Project code"},
            lifecycle_messages=LifecycleMessages(
                on_start="📄 Creating project files...",
                on_success="✅ Files created"
            )
        ),
        Task(
            task_id="update_config",
            tool="file_create",
            execution_target="client",
            depends_on=["create_files"],
            inputs={"path": "~/my_project/config.json", "content": '{"version": "1.0"}'},
            lifecycle_messages=LifecycleMessages(
                on_start="⚙️  Updating configuration...",
                on_success="✅ Config updated"
            )
        ),
    ]
    
    await orchestrator.register_tasks(user_id, tasks)
    engine_task = await execution_engine.start_execution(user_id)
    await engine_task
    
    summary = await orchestrator.get_execution_summary(user_id)
    logger.info(f"\n📊 Summary: {summary}")
    
    logger.info("\n🚀 This entire chain should be emitted as ONE batch to client!")
    
    return summary


async def scenario_5_parallel_clients():
    """
    Scenario 5: C1, C2 (Independent Parallel Client Tasks)
    
    create_notes + create_images (parallel)
    
    Tests:
    - Parallel client execution
    - Independent client tasks
    - No cross-dependencies
    """
    print_section("SCENARIO 5: Parallel Independent Clients (C1, C2)")
    
    orchestrator = init_orchestrator()
    execution_engine = init_execution_engine()
    
    user_id = "scenario_5"
    
    tasks = [
        Task(
            task_id="create_notes",
            tool="file_create",
            execution_target="client",
            depends_on=[],
            inputs={"path": "~/notes.txt", "content": "Meeting notes"},
            lifecycle_messages=LifecycleMessages(
                on_start="📝 Creating notes file...",
                on_success="✅ Notes created"
            )
        ),
        Task(
            task_id="create_images",
            tool="folder_create",
            execution_target="client",
            depends_on=[],
            inputs={"path": "~/images"},
            lifecycle_messages=LifecycleMessages(
                on_start="🖼️  Creating images folder...",
                on_success="✅ Images folder created"
            )
        ),
        Task(
            task_id="create_backup",
            tool="folder_create",
            execution_target="client",
            depends_on=[],
            inputs={"path": "~/backup"},
            lifecycle_messages=LifecycleMessages(
                on_start="💾 Creating backup folder...",
                on_success="✅ Backup folder created"
            )
        ),
    ]
    
    await orchestrator.register_tasks(user_id, tasks)
    engine_task = await execution_engine.start_execution(user_id)
    await engine_task
    
    summary = await orchestrator.get_execution_summary(user_id)
    logger.info(f"\n📊 Summary: {summary}")
    logger.info(f"\n⚡ These tasks should be emitted separately for parallel client execution!")
    
    return summary


async def scenario_6_complex_mixed():
    """
    Scenario 6: Complex Mixed Workflow
    
    Graph:
    ```
    search1 (S) ─┐
                 ├─> analyze (S) ─> create_report_folder (C) ─> write_report (C)
    search2 (S) ─┘                          │
                                            ├─> write_summary (C)
                                            │
    fetch_images (S) ────────────────────> save_images (C)
    ```
    
    Tests:
    - Complex dependency graph
    - Mixed server/client
    - Multiple parallel branches
    - Input binding across targets
    - Chain detection in complex graph
    """
    print_section("SCENARIO 6: Complex Mixed Workflow")
    
    orchestrator = init_orchestrator()
    server_executor = init_server_executor()
    execution_engine = init_execution_engine()
    execution_engine.set_server_executor(server_executor)
    
    user_id = "scenario_6"
    
    tasks = [
        # Parallel server searches
        Task(
            task_id="search_market_data",
            tool="web_search",
            execution_target="server",
            depends_on=[],
            inputs={"query": "stock market trends 2024"},
            lifecycle_messages=LifecycleMessages(
                on_start="📊 Searching market data...",
                on_success="✅ Market data found"
            )
        ),
        Task(
            task_id="search_competitor_data",
            tool="web_search",
            execution_target="server",
            depends_on=[],
            inputs={"query": "competitor analysis tech sector"},
            lifecycle_messages=LifecycleMessages(
                on_start="🔍 Searching competitor data...",
                on_success="✅ Competitor data found"
            )
        ),
        
        # Server analysis (depends on both searches)
        Task(
            task_id="analyze_combined",
            tool="web_search",
            execution_target="server",
            depends_on=["search_market_data", "search_competitor_data"],
            inputs={"query": "market analysis summary"},
            lifecycle_messages=LifecycleMessages(
                on_start="🧠 Analyzing combined data...",
                on_success="✅ Analysis complete"
            )
        ),
        
        # Client chain: create folder → write files
        Task(
            task_id="create_report_folder",
            tool="folder_create",
            execution_target="client",
            depends_on=["analyze_combined"],
            inputs={"path": "~/reports"},
            lifecycle_messages=LifecycleMessages(
                on_start="📁 Creating report folder...",
                on_success="✅ Folder created"
            )
        ),
        Task(
            task_id="write_report",
            tool="file_create",
            execution_target="client",
            depends_on=["create_report_folder"],
            inputs={"path": "~/reports/analysis.txt"},
            input_bindings={
                "content": "$.analyze_combined.data.summary"
            },
            lifecycle_messages=LifecycleMessages(
                on_start="📝 Writing analysis report...",
                on_success="✅ Report written"
            )
        ),
        Task(
            task_id="write_summary",
            tool="file_create",
            execution_target="client",
            depends_on=["create_report_folder"],
            inputs={"path": "~/reports/summary.txt", "content": "Executive summary"},
            lifecycle_messages=LifecycleMessages(
                on_start="📄 Writing summary...",
                on_success="✅ Summary written"
            )
        ),
        
        # Parallel independent branch
        Task(
            task_id="fetch_images",
            tool="web_search",
            execution_target="server",
            depends_on=[],
            inputs={"query": "market charts visualization"},
            lifecycle_messages=LifecycleMessages(
                on_start="🖼️  Fetching visualization images...",
                on_success="✅ Images fetched"
            )
        ),
        Task(
            task_id="save_images",
            tool="folder_create",
            execution_target="client",
            depends_on=["fetch_images"],
            inputs={"path": "~/reports/images"},
            lifecycle_messages=LifecycleMessages(
                on_start="💾 Saving images...",
                on_success="✅ Images saved"
            )
        ),
    ]
    
    await orchestrator.register_tasks(user_id, tasks)
    
    start_time = datetime.now()
    engine_task = await execution_engine.start_execution(user_id)
    await engine_task
    duration = (datetime.now() - start_time).total_seconds()
    
    summary = await orchestrator.get_execution_summary(user_id)
    logger.info(f"\n📊 Summary: {summary}")
    logger.info(f"⏱️  Total execution time: {duration:.2f}s")
    
    # Verify execution order
    state = orchestrator.get_state(user_id)
    if state:
        logger.info("\n📋 Execution Timeline:")
        for task_id in ["search_market_data", "search_competitor_data", "analyze_combined",
                        "create_report_folder", "write_report", "write_summary",
                        "fetch_images", "save_images"]:
            task = state.get_task(task_id)
            if task and task.started_at:
                logger.info(f"   {task_id}: started at {task.started_at.strftime('%H:%M:%S.%f')[:-3]}")
    
    return summary


async def run_all_scenarios():
    """Run all test scenarios"""
    print_section("🚀 REAL-WORLD EXECUTION SCENARIOS TEST SUITE")
    
    results = {}

    
    # Run each scenario
    scenarios = [
        ("Scenario 1: S→S", scenario_1_server_chain),
        # ("Scenario 2: S1, S2", scenario_2_parallel_servers),
        # ("Scenario 3: S→C→C", scenario_3_server_to_client_chain),
        # ("Scenario 4: C→C→C", scenario_4_pure_client_chain),
        # ("Scenario 5: C1, C2", scenario_5_parallel_clients),
        # ("Scenario 6: Complex", scenario_6_complex_mixed),
    ]
    
    for name, scenario_func in scenarios:
        try:
            logger.info(f"\n▶️  Running {name}...")
            result = await scenario_func()
            results[name] = {"status": "✅ PASS", "summary": result}
            logger.info(f"✅ {name} completed successfully\n")
            await asyncio.sleep(1)  # Brief pause between scenarios
        except Exception as e:
            results[name] = {"status": "❌ FAIL", "error": str(e)}
            logger.error(f"❌ {name} failed: {e}\n")
    
    # Final report
    print_section("📊 FINAL TEST REPORT")
    
    total = len(scenarios)
    passed = sum(1 for r in results.values() if "PASS" in r["status"])
    failed = total - passed
    
    logger.info(f"Total Scenarios: {total}")
    logger.info(f"✅ Passed: {passed}")
    logger.info(f"❌ Failed: {failed}")
    logger.info(f"Success Rate: {(passed/total)*100:.1f}%\n")
    
    # logger.info("Detailed Results:")
    for name, result in results.items():
        logger.info(f"  {result['status']} {name}")
        if "summary" in result:
            s = result["summary"]
            logger.info(f"      Tasks: {s.get('total', 0)}, "
                       f"Completed: {s.get('completed', 0)}, "
                       f"Failed: {s.get('failed', 0)}")
    
    print_section("🏁 TEST SUITE COMPLETE")


if __name__ == "__main__":
    asyncio.run(run_all_scenarios())

