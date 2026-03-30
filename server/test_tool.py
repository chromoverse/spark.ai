from tools.tools.system import app, sound, screenshot , screen, system_info,weather, notification, network, clipboard, brightness
from tools.tools.web import WebScrapeTool, WebSearchTool, WebResearchTool
import asyncio
import json

async def test_tools():
    tool = WebResearchTool()
    result = await tool.execute({"query": "who is current pm of nepal ? and who was last ?"})
    print(json.dumps(result.data, indent=2))

if __name__ == "__main__":
  asyncio.run(test_tools())