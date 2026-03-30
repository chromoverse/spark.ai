from tools.system import app
import asyncio

async def test_tools():
    tool = app.AppOpenTool()
    result = await tool.execute({"target": "notepad"})

if __name__ == "__main__":
  asyncio.run(test_tools())