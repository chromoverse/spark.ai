import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json


from tools_plugin.tools.system import app, battery, brightness, sound, network, clipboard, screenshot
from tools_plugin.tools.media import music

async def main():
    tool = music.MusicPlayTool()
    res = await tool.execute({"title" : "Lover"})
    print(json.dumps(res.data, indent=2))

    
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())