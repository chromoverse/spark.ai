from app.cache import RedisManager 
import asyncio
import json
from app.cache import load_user
from app.utils.format_context import format_context
from app.registry.loader import load_tool_registry, get_tool_registry
from app.tools.loader import load_all_tools

async def main():
    config = RedisManager()
    
    
    # await config.add_message("user123", "user", "Hello, World!")
    # await config.add_message("user123", "ai", "Hi there!")
    # await config.add_message("user123", "user", "Hey what is up?")
    # await config.add_message("user123", "ai", "Not much!")
    from app.db.mongo import connect_to_mongo
    await connect_to_mongo()
    # doc = await config.get_last_n_messages("guest",5)
    # print(json.dumps(doc, indent=4))
    # plain, a = format_context(doc, [])
    # print(plain)

    from app.services.chat_service import chat
    await chat("open notepad", user_id="guest")
    
    # Wait for background tasks to complete
    print("Waiting for background tasks...")
    await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main()) 


# {
#   "request_id": "20260117_082700_001",
#   "cognitive_state": {
#     "user_query": "Lets do some code open vscode and also write something related to AI in notepad",
#     "emotion": "neutral",
#     "thought_process": "The user wants to open VS Code and write something about AI in Notepad. This requires two app launches and one file creation. I need to use 'open_app' for VS Code, 'open_app' for Notepad, and 'file_create' to put content in Notepad. No special date today. Emotion is neutral.",
#     "answer": "Alright, opening VS Code for you. And I'll open Notepad to write something about AI.",
#     "answer_english": "Alright, opening VS Code for you. And I'll open Notepad to write something about AI."
#   },
#   "requested_tool": [
#     "open_app",
#     "open_app",
#     "file_create"
#   ]
# }         