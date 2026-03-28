import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json


from tools_plugin.tools.system import app, battery, brightness, sound, network, clipboard, screenshot, location, weather , screen
from tools_plugin.tools.media import music
from tools_plugin.tools.google import gmail

async def main():

    tool =  screen.LockScreenTool()
    res = await tool._execute({"detailed": True})
    print(json.dumps(res.data, indent=2))

    
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())