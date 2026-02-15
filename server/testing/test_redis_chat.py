from app.cache import RedisManager 
import asyncio
import json
from app.cache import load_user
from app.utils.format_context import format_context

async def main():
    config = RedisManager()
  
    # await config.add_message("user123", "user", "Hello, World!")
    # await config.add_message("user123", "user", "I loved the movie Inception.")
    # await config.add_message("user123", "user", "Loving someone from heart is beautiful.")
    # await config.add_message("user123", "user", "AI and machine learning are the future.")
    # await config.add_message("user123", "assistant", "Hi there!")
    # await config.add_message("user123", "user", "Hey what is up?")
    # await config.add_message("user123", "assistant", "Not much!")

    user_id = "695e2bbaf8efc966aaf9f218"
    messages = await config.get_last_n_messages(user_id, 10)
    print(json.dumps(messages, indent=4))

    # search = await config.semantic_search_messages(user_id, "Love is the purest flavor", top_k=3)
    # print("\nSemantic Search Results:")
    # print(json.dumps(search, indent=4))


if __name__ == "__main__":
    asyncio.run(main()) 
