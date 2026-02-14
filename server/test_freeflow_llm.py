import asyncio

from freeflow_llm import FreeFlowClient
from freeflow_llm.providers import GeminiProvider, GroqProvider
import os

def main():
    with FreeFlowClient(
        providers=[GroqProvider(api_key=os.getenv("GROQ_API_KEY"))]
    ) as client:
        stream = client.chat_stream(
            messages=[{"role": "user", "content": "Write a story..."}]
        )
        
        for chunk in stream:
            print(chunk.content, end="", flush=True)

# main()


from app.registry.tool_index import get_tools_index


print(os.getenv("GROQ_API_KEY"))

def fun_plain():
  # Initialize client (automatically finds keys in env)
  while True:
      prompt = asyncio.run(get_prompt())
      print(f"Prompt: {prompt}")
      print("\n\n Response:")
      with FreeFlowClient() as client:
          response = client.chat(
              messages=[
                  {"role": "user", "content": prompt}
              ]
          )
          
          print(f"AI: {response.content}")

def stream():
   import asyncio
   while True:
         prompt = asyncio.run(get_prompt())
         print("\n\n Response:")
         with FreeFlowClient() as client:
             stream = client.chat_stream(
                 messages=[{"role": "user", "content": prompt}]
             )
             
             for chunk in stream:
                 print(chunk.content, end="", flush=True)


async def get_prompt():
    from app.prompts import stream_prompt, pqh_prompt
    from app.cache import redis_manager
    user_id = "695e2bbaf8efc966aaf9f218"
    prompt = input("\n\nEnter a query to test prompt building: ")
    recent_context = await redis_manager.get_last_n_messages(user_id, 10)
    query_based_context, _ = await redis_manager.process_query_and_get_context(user_id, prompt)
    tools_index = get_tools_index()
    # print("tools index",tools_index)
    prompt =  pqh_prompt.build_prompt_en(prompt, tools_index)
    # prompt =  stream_prompt.build_prompt_en("neutral", prompt, recent_context,query_based_context, user_details=None)
    return prompt

# stream()
# fun_plain()


# cleint = FreeFlowClient()
# print(cleint.list_providers())
#  this work : $env:GROQ_API_KEY='["REMOVED"]'
# but not this : [System.Environment]::SetEnvironmentVariable("GROQ_API_KEY", '["REMOVED"]', "User")


from app.ai.providers import llm_chat,llm_stream

async def test_stream():
   res =  await llm_chat(messages=[{"role": "user", "content": "Write a story..."}])
   print("res",res)


import asyncio
asyncio.run(test_stream())