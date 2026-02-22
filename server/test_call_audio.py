from app.agent.shared.tools.messaging.call_audio import CallAudioTool

async def main():
  tool = CallAudioTool()
  await tool._execute({"contact": "Daddy", "platform": "whatsapp"})

if __name__ == "__main__": 
  import asyncio
  asyncio.run(main())