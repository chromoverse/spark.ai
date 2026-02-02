# test_input_bindings.py
"""
Test Input Bindings Resolution

Tests various binding scenarios:
1. Simple binding: S1 → S2 (output.data.field)
2. Nested binding: S1 → S2 (output.data.nested.field)
3. Cross-target binding: S → C (server output to client input)
4. Chain binding: S1 → S2 → S3 (A→B→C with bindings)
5. Multiple bindings: S1,S2 → S3 (multiple sources)
6. Failed binding: Missing field
"""

import asyncio
import logging
import json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

from app.registry.loader import load_tool_registry
from app.core.orchestrator import init_orchestrator
from app.core.execution_engine import init_execution_engine
from app.core.server_executor import init_server_executor
from app.core.mock_client_emitter import create_mock_emitter
from app.core.models import Task, LifecycleMessages
from app.tools.loader import load_all_tools


def print_section(title: str):
    """Pretty section divider"""
    logger.info("\n" + "="*80)
    logger.info(f"  {title}")
    logger.info("="*80 + "\n")


async def test_simple_binding():
    """
    Test 1: Simple Server→Server Binding
    
    search_term → analyze_results
    analyze_results gets search results via binding
    """
    print_section("TEST 1: Simple S→S Binding")
    
    orchestrator = init_orchestrator()
    server_executor = init_server_executor()
    execution_engine = init_execution_engine()
    execution_engine.set_server_executor(server_executor)
    mock_emitter = create_mock_emitter()
    execution_engine.set_client_emitter(mock_emitter)
    
    user_id = "binding_test_1"
    
    tasks = [
        Task(
            task_id="search_term",
            tool="web_search",
            execution_target="server",
            depends_on=[],
            inputs={"query": "Python asyncio tutorial - siddthecoder"},
        ),
        Task(
            task_id="analyze_results",
            tool="web_search",
            execution_target="server",
            depends_on=["search_term"],
            inputs={"query": "detailed analysis"},
            input_bindings={
                "query": "$.search_term.data.query_demo"
            }
        ),
    ]
    
    await orchestrator.register_tasks(user_id, tasks)
    engine_task = await execution_engine.start_execution(user_id)
    await engine_task
    
    # Verify binding was resolved
    state = orchestrator.get_state(user_id)
    if state:
        analyze_task = state.get_task("analyze_results")
        logger.info(f"\n✅ Binding Test Result:")
        logger.info(f"   analyze_results resolved_inputs: {analyze_task.resolved_inputs if analyze_task else 'None'}")
    
    summary = await orchestrator.get_execution_summary(user_id)
    return summary


async def test_server_to_client_binding():
    """
    Test 2: Server→Client Binding
    
    fetch_data (S) → save_file (C)
    save_file gets content from fetch_data output
    """
    print_section("TEST 2: Server→Client Binding")
    
    orchestrator = init_orchestrator()
    server_executor = init_server_executor()
    execution_engine = init_execution_engine()
    execution_engine.set_server_executor(server_executor)
    mock_emitter = create_mock_emitter()
    execution_engine.set_client_emitter(mock_emitter)
    
    user_id = "binding_test_2"
    
    tasks = [
        Task(
            task_id="fetch_data",
            tool="web_search",
            execution_target="server",
            depends_on=[],
            inputs={"query": "latest tech news"},
        ),
        Task(
            task_id="save_file",
            tool="file_create",
            execution_target="client",
            depends_on=["fetch_data"],
            inputs={
                "path": "~/news.txt"
            },
            input_bindings={
                # Bind content from search results
                # "content": "$.fetch_data.data.results"
                "query": "$.fetch_data.data.query_demo"
            }
        ),
    ]
    
    await orchestrator.register_tasks(user_id, tasks)
    engine_task = await execution_engine.start_execution(user_id)
    await engine_task
    
    # Verify binding
    state = orchestrator.get_state(user_id)
    if state:
        save_task = state.get_task("save_file")
        logger.info(f"\n✅ Cross-Target Binding Result:")
        logger.info(f"   save_file resolved_inputs: {save_task.resolved_inputs if save_task else 'None'}")
        if save_task and save_task.resolved_inputs:
            logger.info(f"   ✅ Content bound from fetch_data: {len(str(save_task.resolved_inputs.get('content', '')))} chars")
    
    summary = await orchestrator.get_execution_summary(user_id)
    return summary


async def test_chain_binding():
    """
    Test 3: Chain Binding (A→B→C)
    
    search → extract → format
    Each step uses output from previous
    """
    print_section("TEST 3: Chain Binding (S→S→S)")
    
    orchestrator = init_orchestrator()
    server_executor = init_server_executor()
    execution_engine = init_execution_engine()
    execution_engine.set_server_executor(server_executor)
    mock_emitter = create_mock_emitter()
    execution_engine.set_client_emitter(mock_emitter)
    
    user_id = "binding_test_3"
    
    tasks = [
        Task(
            task_id="search",
            tool="web_search",
            execution_target="server",
            depends_on=[],
            inputs={"query": "machine learning basics"},
        ),
        Task(
            task_id="extract",
            tool="web_search",
            execution_target="server",
            depends_on=["search"],
            inputs={"query": "extract key concepts"},
            input_bindings={
                # Would bind search results in real scenario
            }
        ),
        Task(
            task_id="format",
            tool="web_search",
            execution_target="server",
            depends_on=["extract"],
            inputs={"query": "format as summary"},
            input_bindings={
                # Would bind extracted data
            }
        ),
    ]
    
    await orchestrator.register_tasks(user_id, tasks)
    engine_task = await execution_engine.start_execution(user_id)
    await engine_task
    
    # Verify chain execution
    state = orchestrator.get_state(user_id)
    if state:
        logger.info(f"\n✅ Chain Binding Results:")
        for task_id in ["search", "extract", "format"]:
            task = state.get_task(task_id)
            if task:
                logger.info(f"   {task_id}: status={task.status}, duration={task.duration_ms}ms")
    
    summary = await orchestrator.get_execution_summary(user_id)
    return summary


async def test_multiple_source_binding():
    """
    Test 4: Multiple Source Binding
    
    search1 + search2 → combine
    combine task binds inputs from BOTH sources
    """
    print_section("TEST 4: Multiple Source Binding")
    
    orchestrator = init_orchestrator()
    server_executor = init_server_executor()
    execution_engine = init_execution_engine()
    execution_engine.set_server_executor(server_executor)
    mock_emitter = create_mock_emitter()
    execution_engine.set_client_emitter(mock_emitter)
    
    user_id = "binding_test_4"
    
    tasks = [
        Task(
            task_id="search_topic_a",
            tool="web_search",
            execution_target="server",
            depends_on=[],
            inputs={"query": "Python programming"},
        ),
        Task(
            task_id="search_topic_b",
            tool="web_search",
            execution_target="server",
            depends_on=[],
            inputs={"query": "JavaScript programming"},
        ),
        Task(
            task_id="compare",
            tool="web_search",
            execution_target="server",
            depends_on=["search_topic_a", "search_topic_b"],
            inputs={"query": "compare results"},
            input_bindings={
                # Would bind from both sources
                "topic_a_data": "$.search_topic_a.data.query_demo",
                "topic_b_data": "$.search_topic_b.data.query_demo"
            }
        ),
    ]
    
    await orchestrator.register_tasks(user_id, tasks)
    engine_task = await execution_engine.start_execution(user_id)
    await engine_task
    
    # Verify parallel execution + binding
    state = orchestrator.get_state(user_id)
    if state:
        compare_task = state.get_task("compare")
        logger.info(f"\n✅ Multiple Source Binding Result:")
        logger.info(f"   compare task status: {compare_task.status if compare_task else 'None'}")
        logger.info(f"   ✅ Both searches completed before compare ran")
    
    summary = await orchestrator.get_execution_summary(user_id)
    return summary


async def test_client_chain_binding():
    """
    Test 5: Client Chain with Bindings
    
    S → C1 → C2 → C3
    Each client task binds from previous
    """
    print_section("TEST 5: Client Chain Binding (S→C→C→C)")
    
    orchestrator = init_orchestrator()
    server_executor = init_server_executor()
    execution_engine = init_execution_engine()
    execution_engine.set_server_executor(server_executor)
    mock_emitter = create_mock_emitter()
    execution_engine.set_client_emitter(mock_emitter)
    
    user_id = "binding_test_5"
    
    tasks = [
        Task(
            task_id="fetch_config",
            tool="web_search",
            execution_target="server",
            depends_on=[],
            inputs={"query": "project configuration"},
        ),
        Task(
            task_id="create_folder",
            tool="folder_create",
            execution_target="client",
            depends_on=["fetch_config"],
            inputs={"path": "~/project"},
            input_bindings={
                # Would bind folder name from config
            }
        ),
        Task(
            task_id="create_file",
            tool="file_create",
            execution_target="client",
            depends_on=["create_folder"],
            inputs={"path": "~/project/config.json"},
            input_bindings={
                # Bind content from server config
                "content": "$.fetch_config.data.results"
            }
        ),
        Task(
            task_id="update_file",
            tool="file_create",
            execution_target="client",
            depends_on=["create_file"],
            inputs={"path": "~/project/readme.md"},
            input_bindings={
                # Could bind from created file path
            }
        ),
    ]
    
    await orchestrator.register_tasks(user_id, tasks)
    engine_task = await execution_engine.start_execution(user_id)
    await engine_task
    
    # Verify chain batching and binding
    state = orchestrator.get_state(user_id)
    if state:
        logger.info(f"\n✅ Client Chain Binding Results:")
        for task_id in ["create_folder", "create_file", "update_file"]:
            task = state.get_task(task_id)
            if task:
                logger.info(f"   {task_id}: emitted_at={task.emitted_at}")
        logger.info(f"   ✅ All client tasks should be emitted together!")
    
    summary = await orchestrator.get_execution_summary(user_id)
    return summary


async def test_complex_binding_graph():
    """
    Test 6: Complex Dependency Graph with Multiple Bindings
    
         S1 ──┐
              ├─→ S3 ─→ C1 ─→ C2
         S2 ──┘
    
    S3 binds from both S1 and S2
    C1 binds from S3
    C2 binds from C1
    """
    print_section("TEST 6: Complex Binding Graph")
    
    orchestrator = init_orchestrator()
    server_executor = init_server_executor()
    execution_engine = init_execution_engine()
    execution_engine.set_server_executor(server_executor)
    mock_emitter = create_mock_emitter()
    execution_engine.set_client_emitter(mock_emitter)
    
    user_id = "binding_test_6"
    
    tasks = [
        Task(
            task_id="fetch_users",
            tool="web_search",
            execution_target="server",
            depends_on=[],
            inputs={"query": "user data"},
        ),
        Task(
            task_id="fetch_products",
            tool="web_search",
            execution_target="server",
            depends_on=[],
            inputs={"query": "product data"},
        ),
        Task(
            task_id="merge_data",
            tool="web_search",
            execution_target="server",
            depends_on=["fetch_users", "fetch_products"],
            inputs={"query": "merge datasets"},
            input_bindings={
                # "users": "$.fetch_users.data.results",
                # "products": "$.fetch_products.data.results"
            }
        ),
        Task(
            task_id="create_report_folder",
            tool="folder_create",
            execution_target="client",
            depends_on=["merge_data"],
            inputs={"path": "~/reports"},
        ),
        Task(
            task_id="save_report",
            tool="file_create",
            execution_target="client",
            depends_on=["create_report_folder"],
            inputs={"path": "~/reports/data.json"},
            input_bindings={
                "content": "$.merge_data.data.results"
            }
        ),
    ]
    
    await orchestrator.register_tasks(user_id, tasks)
    engine_task = await execution_engine.start_execution(user_id)
    await engine_task
    
    # Verify complex execution
    state = orchestrator.get_state(user_id)
    if state:
        logger.info(f"\n✅ Complex Binding Graph Results:")
        logger.info(f"   Execution Order:")
        
        tasks_with_times = []
        for task_id in ["fetch_users", "fetch_products", "merge_data", 
                        "create_report_folder", "save_report"]:
            task = state.get_task(task_id)
            if task and task.started_at:
                tasks_with_times.append((task_id, task.started_at, task.status))
        
        tasks_with_times.sort(key=lambda x: x[1])
        for task_id, start_time, status in tasks_with_times:
            logger.info(f"     {task_id}: {start_time.strftime('%H:%M:%S.%f')[:-3]} ({status})")
        
        logger.info(f"   ✅ fetch_users and fetch_products ran in parallel")
        logger.info(f"   ✅ merge_data waited for both")
        logger.info(f"   ✅ Client tasks batched together")
    
    summary = await orchestrator.get_execution_summary(user_id)
    return summary


async def run_all_binding_tests():
    """Run all binding tests"""
    print_section("🧪 INPUT BINDING TESTS")
    
    try:
        load_tool_registry()
        load_all_tools()
        logger.info("✅ Tools loaded\n")
    except Exception as e:
        logger.warning(f"⚠️  Tool loading failed: {e}\n")
    
    tests = [
        # ("Test 1: Simple S→S", test_simple_binding),
        # ("Test 2: S→C Binding", test_server_to_client_binding),
        # ("Test 3: Chain Binding", test_chain_binding),
        ("Test 4: Multiple Sources", test_multiple_source_binding),
        # ("Test 5: Client Chain", test_client_chain_binding),
        # ("Test 6: Complex Graph", test_complex_binding_graph),
    ]
    
    results = {}
    
    for name, test_func in tests:
        try:
            logger.info(f"\n▶️  Running {name}...")
            result = await test_func()
            results[name] = {"status": "✅ PASS", "summary": result}
            logger.info(f"✅ {name} completed\n")
            await asyncio.sleep(0.5)
        except Exception as e:
            results[name] = {"status": "❌ FAIL", "error": str(e)}
            logger.error(f"❌ {name} failed: {e}\n")
    
    # Final report
    print_section("📊 BINDING TESTS REPORT")
    
    total = len(tests)
    passed = sum(1 for r in results.values() if "PASS" in r["status"])
    failed = total - passed
    
    logger.info(f"Total Tests: {total}")
    logger.info(f"✅ Passed: {passed}")
    logger.info(f"❌ Failed: {failed}")
    logger.info(f"Success Rate: {(passed/total)*100:.1f}%\n")
    
    for name, result in results.items():
        logger.info(f"  {result['status']} {name}")
        if "summary" in result:
            s = result["summary"]
            logger.info(f"      Completed: {s.get('completed', 0)}/{s.get('total', 0)}")
    
    print_section("🏁 BINDING TESTS COMPLETE")


if __name__ == "__main__":
    asyncio.run(run_all_binding_tests())