from app.ai.providers.manager import llm_chat
from app.agent.shared.tools.ai.init import AiSummarizeTool
import asyncio

async def chat(text):
  response, provider = await llm_chat([{"role": "user", "content": text}], model="openai/gpt-oss-20b")
  return response, provider

async def main():
  query = input("Enter your query: ")
  response, provider = await chat(query, )
  tool = AiSummarizeTool()
  tool_res = await tool._execute({"context": "Summarize from this as hey i am siddthecoder", "query": "who is siddthecoder"})
  print("Provider", provider , "Response",response)
  print(tool_res.data)

if __name__ == "__main__":
  while True :
    asyncio.run(main())