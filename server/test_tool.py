from tools.tools.system import app, sound, screenshot , screen, system_info,weather, notification, network, clipboard, brightness, shell_agent, artifacts
import asyncio
import json

async def test_tools():
    tool = artifacts.ArtifactListTool()
    result = await tool.execute({"kind": "screenshot", "user_id" : "695e2bbaf8efc966aaf9f218"})
    print(json.dumps(result.data, indent=2))

if __name__ == "__main__":
  asyncio.run(test_tools())