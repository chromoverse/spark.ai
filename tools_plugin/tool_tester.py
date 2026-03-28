import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json


from tools_plugin.tools.system import app, battery, brightness, sound, network, clipboard, screenshot
from tools_plugin.tools.media import music
from tools_plugin.tools.google import gmail

async def main():

    tool = gmail.EmailListTool()
    res = await tool.execute({"user_id": "695e2bbaf8efc966aaf9f218" , "to" : "siddhantyadav4040@gmail.com", "subject" : "Test Subject", "body" : "Test Body"})
    print(json.dumps(res.data, indent=2))


    ids = [email["id"] for email in res.data["emails"]]
    print(ids)

    tool = gmail.EmailMarkReadTool()
    res = await tool.execute({"user_id": "695e2bbaf8efc966aaf9f218" , "message_ids" : ids})
    print(json.dumps(res.data, indent=2))

    
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())