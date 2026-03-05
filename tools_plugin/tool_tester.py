from tools_plugin.tools.messaging import message_send

async def main():
  await message_send.MessageSendTool().execute({"contact": "Rajesh Vaiya", "message": "Hello, world! Testing message"})

if __name__ == "__main__":
  import asyncio
  asyncio.run(main())