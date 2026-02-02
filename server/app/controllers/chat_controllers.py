from app.db.mongo import get_db
from pydantic import BaseModel
from datetime import datetime,timezone

class ChatController(BaseModel):
    user_id: str
    user_query: str
    ai_response: str

async def add_chat_message_to_mongo(data : ChatController) :
   """Adds a chat message to the MongoDB database.
   Args:
       user_id (str): The ID of the user.
       user_query (str): The user's query.
       ai_response (str): The AI's response.
    Returns:
        str: The ID of the inserted chat message.
   """
   try:
       db = get_db()
       chat_message = {
           "user_id": data.user_id,
           "user_query": data.user_query,
           "ai_response": data.ai_response,
           "created_at": datetime.now(timezone.utc)
       }
       result = await db.chats.insert_one(chat_message)
       print(f"Chat message added with id: {result.inserted_id}")
       return str(result.inserted_id)
   except Exception as e:
       raise e