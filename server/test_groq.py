from app.ai.providers.manager import llm_stream, llm_chat
from app.config import settings
from datetime import datetime

GROQ_DEFAULT_MODEL: str = "llama-3.3-70b-versatile"  # streaming
GROQ_REASONING_MODEL: str = "openai/gpt-oss-20b"                           # non-streaming only
GROQ_FALLBACK_MODEL: str = "meta-llama/llama-4-scout-17b-16e-instruct"  # lightweight fallback

async def test_groq_stream():
  query = input("Enter your query: ")
  print("Time",datetime.now())
  async for chunk in llm_stream([{"role": "user", "content": query}], model=GROQ_DEFAULT_MODEL):
    print(chunk, end="", flush=True)
  print("Time",datetime.now())


if __name__ == "__main__": 
  import asyncio
  while True:
    asyncio.run(test_groq_stream())