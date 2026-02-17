import asyncio

from app.agent.shared.tools.system.operations import (
    AppOpenTool,
    AppCloseTool,
    AppRestartTool,
    AppMinimizeTool,
    AppMaximizeTool,
    AppFocusTool,

    BrightnessStatusTool,
    BrightnessIncreaseTool,
    BrightnessDecreaseTool,

    SoundStatusTool,
    SoundIncreaseTool,
    SoundDecreaseTool,

    ClipboardReadTool,
    ClipboardWriteTool,

    ScreenshotCaptureTool,

    SystemInfoTool,

    NotificationPushTool,
    NetworkStatusTool,

    BatteryStatusTool,
)

async def test_app_controls():
    print("--- Starting App Control Tests ---")
    
    open_tool = AppOpenTool()
    close_tool = AppCloseTool()
    restart_tool = AppRestartTool()
    minimize_tool = AppMinimizeTool()
    maximize_tool = AppMaximizeTool()
    focus_tool = AppFocusTool()
    
    target_app = "bluetooth"  # Change this to an app you have installed for testing
    
    # 1. Open Notepad
    # print(f"\n[1] Opening {target_app}...")
    # res = await open_tool._execute({"target": target_app})
    # print(f"Result: {res.success}, {res.data.get('status')}")
    # if not res.success:
    #     print(f"Error: {res.error}")
    #     return

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

    # 5. Restart
    print(f"\n[5] Restarting {target_app}...")
    res = await restart_tool._execute({"target": target_app})
    print(f"Result: {res.success}, {res.data.get('status')}")
    if not res.success: print(res.error)

    await asyncio.sleep(2)

    # # 6. Close
    # print(f"\n[6] Closing {target_app}...")
    # res = await close_tool._execute({"target": target_app})
    # print(f"Result: {res.success}, {res.data.get('status')}")
    # if not res.success: print(res.error)

    print("\n--- Test Finished ---")


async def test_brightness_controls():
    print("--- Starting Brightness Control Tests ---")
    
    status_tool = BrightnessStatusTool()
    increase_tool = BrightnessIncreaseTool()
    decrease_tool = BrightnessDecreaseTool()
    
    # 1. Get current brightness
    print("\n[1] Getting current brightness...")
    res = await status_tool._execute({})
    print(f"Result: {res.success}, Current Brightness: {res.data.get('brightness')}")
    if not res.success:
        print(f"Error: {res.error}")
        return

    await asyncio.sleep(2)

    # 2. Increase brightness
    print("\n[2] Increasing brightness...")
    res = await increase_tool._execute({"amount": 10})
    print(f"Result: {res.success}, New Brightness: {res.data.get('brightness')}")
    if not res.success: print(res.error)

    # await asyncio.sleep(2)

    # 3. Decrease brightness
    # print("\n[3] Decreasing brightness...")
    # res = await decrease_tool._execute({"amount": 10})
    # print(f"Result: {res.success}, New Brightness: {res.data.get('brightness')}")
    # if not res.success: print(res.error)

    print("\n--- Test Finished ---")


async def test_sound_controls():
    print("--- Starting Sound Control Tests ---")
    
    status_tool = SoundStatusTool()
    increase_tool = SoundIncreaseTool()
    decrease_tool = SoundDecreaseTool()
    
    # 1. Get current volume
    print("\n[1] Getting current volume...")
    res = await status_tool._execute({})
    print(f"Result: {res.success}, Current Volume: {res.data.get('volume')}")
    if not res.success:
        print(f"Error: {res.error}")
        return

    await asyncio.sleep(2)

    # 2. Increase volume
    # print("\n[2] Increasing volume...")
    # res = await increase_tool._execute({})
    # print(f"Result: {res.success}, New Volume: {res.data.get('volume')}")
    # if not res.success: print(res.error)

    # await asyncio.sleep(2)

    # 3. Decrease volume
    print("\n[3] Decreasing volume...")
    res = await decrease_tool._execute({"amount": 10})
    print(f"Result: {res.success}, New Volume: {res.data.get('volume')}")
    if not res.success: print(res.error)

    print("\n--- Test Finished ---")


async def test_clipboard_controls():
    print("--- Starting Clipboard Control Tests ---")
    
    read_tool = ClipboardReadTool()
    write_tool = ClipboardWriteTool()
    
    # 1. Write to clipboard
    print("\n[1] Writing to clipboard...")
    res = await write_tool._execute({"content": "Hello from AI Assistant!"})
    print(f"Result: {res.success}")
    if not res.success:
        print(f"Error: {res.error}")
        return

    await asyncio.sleep(2)

    # 2. Read from clipboard
    print("\n[2] Reading from clipboard...")
    res = await read_tool._execute({})
    print(f"Result: {res.success}, Clipboard Content: {res.data.get('content')}")
    if not res.success: print(res.error)

    print("\n--- Test Finished ---")


async def test_screenshot_capture():
    print("--- Starting Screenshot Capture Test ---")
    
    capture_tool = ScreenshotCaptureTool()
    
    # 1. Capture screenshot
    print("\n[1] Capturing screenshot...")
    res = await capture_tool._execute({})
    print(f"Result: {res.success}, Screenshot Path: {res.data.get('file_path')}")
    if not res.success:
        print(f"Error: {res.error}")
        return

    print("\n--- Test Finished ---")


async def test_system_info():
    print("--- Starting System Info Test ---")
    
    info_tool = SystemInfoTool()
    
    # 1. Get system info
    print("\n[1] Getting system info...")
    res = await info_tool._execute({})
    print(res.data)
    print(f"Result: {res.success}, System Info: {res.data.get('system_info')}")
    if not res.success:
        print(f"Error: {res.error}")
        return

    print("\n--- Test Finished ---")


async def test_notification_push():
    print("--- Starting Notification Push Test ---")
    
    notification_tool = NotificationPushTool()
    
    # 1. Push a notification
    print("\n[1] Pushing notification...")
    res = await notification_tool._execute({"title": "Test Notification", "message": "This is a test notification from AI Assistant."})
    print(f"Result: {res.success}")
    if not res.success:
        print(f"Error: {res.error}")
        return

    print("\n--- Test Finished ---")


async def test_network_status():
    print("--- Starting Network Status Test ---")
    
    network_tool = NetworkStatusTool()
    
    # 1. Get network status
    print("\n[1] Getting network status...")
    res = await network_tool._execute({"check_internet": True})
    print(f"Result: {res.success}, Network Status: {res.data}")
    if not res.success:
        print(f"Error: {res.error}")
        return

    print("\n--- Test Finished ---")


async def test_battery_status():
    print("--- Starting Battery Status Test ---")
    
    battery_tool = BatteryStatusTool()
    
    # 1. Get battery status
    print("\n[1] Getting battery status...")
    res = await battery_tool._execute({})
    print(f"Result: {res.success}, Battery Status: {res.data}")
    if not res.success:
        print(f"Error: {res.error}")
        return

    print("\n--- Test Finished ---")

if __name__ == "__main__":
    # asyncio.run(test_app_controls())
    asyncio.run(test_brightness_controls())
    asyncio.run(test_sound_controls())
    # asyncio.run(test_clipboard_controls())
    # asyncio.run(test_screenshot_capture())
    # asyncio.run(test_system_info())
    # asyncio.run(test_notification_push())
    # asyncio.run(test_network_status())
    # asyncio.run(test_battery_status())
