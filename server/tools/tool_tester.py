import sys, os
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "server"))

from dotenv import load_dotenv
load_dotenv(os.path.join(_root, "server", ".env"))

import json


from tools_plugin.tools.system import app, battery, brightness, sound, network, clipboard, screenshot, location, weather , screen
from tools_plugin.tools.media import music
from tools_plugin.tools.google import gmail
from tools_plugin.tools.web import WebResearchTool

async def main():

    tool =  WebResearchTool()
    res = await tool._execute({"query": "Who got arrested yesterday in nepal ?"})
    print(json.dumps(res.data, indent=2))

    
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())