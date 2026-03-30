from tools.tools.system import app, sound, screenshot , screen, system_info,weather, notification, network, clipboard, brightness
import asyncio
import json

async def test_tools():
    tool = app.AppFocusTool()
    result = await tool.execute({"target": "notepad"})
    print(json.dumps(result.data, indent=2))

if __name__ == "__main__":
  asyncio.run(test_tools())