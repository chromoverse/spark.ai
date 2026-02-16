import asyncio
import os
import sys

# Adjust path to enable imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from server.app.agent.shared.tools.system.operations import (
    AppOpenTool,
    AppCloseTool,
    AppRestartTool,
    AppMinimizeTool,
    AppMaximizeTool,
    AppFocusTool
)

async def test_app_controls():
    print("--- Starting App Control Tests ---")
    
    open_tool = AppOpenTool()
    close_tool = AppCloseTool()
    restart_tool = AppRestartTool()
    minimize_tool = AppMinimizeTool()
    maximize_tool = AppMaximizeTool()
    focus_tool = AppFocusTool()
    
    target_app = "device manager"  # Change this to an app you have installed for testing
    
    # 1. Open Notepad
    print(f"\n[1] Opening {target_app}...")
    res = await open_tool._execute({"target": target_app})
    print(f"Result: {res.success}, {res.data.get('status')}")
    if not res.success:
        print(f"Error: {res.error}")
        return

    # await asyncio.sleep(2)
    
    # # 2. Minimize
    # print(f"\n[2] Minimizing {target_app}...")
    # res = await minimize_tool._execute({"target": target_app})
    # print(f"Result: {res.success}")
    # if not res.success: print(res.error)
    
    # await asyncio.sleep(1)

    # # 3. Maximize
    # print(f"\n[3] Maximizing {target_app}...")
    # res = await maximize_tool._execute({"target": target_app})
    # print(f"Result: {res.success}")
    # if not res.success: print(res.error)

    # await asyncio.sleep(1)

    #  # 2. Minimize
    # print(f"\n[2] Minimizing {target_app}...")
    # res = await minimize_tool._execute({"target": target_app})
    # print(f"Result: {res.success}")
    # if not res.success: print(res.error)
    
    # await asyncio.sleep(1)
    
    # # 4. Focus
    # print(f"\n[4] Focusing {target_app}...")
    # res = await focus_tool._execute({"target": target_app})
    # print(f"Result: {res.success}")
    # if not res.success: print(res.error)

    # await asyncio.sleep(1)

    # # 5. Restart
    # print(f"\n[5] Restarting {target_app}...")
    # res = await restart_tool._execute({"target": target_app})
    # print(f"Result: {res.success}, {res.data.get('status')}")
    # if not res.success: print(res.error)

    # await asyncio.sleep(2)

    # # 6. Close
    # print(f"\n[6] Closing {target_app}...")
    # res = await close_tool._execute({"target": target_app})
    # print(f"Result: {res.success}, {res.data.get('status')}")
    # if not res.success: print(res.error)

    print("\n--- Test Finished ---")

if __name__ == "__main__":
    asyncio.run(test_app_controls())
