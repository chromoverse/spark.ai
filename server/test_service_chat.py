from app.services.chat_service import chat
import asyncio

async def test_chat():
  user_id = "695e2bbaf8efc966aaf9f218"
  from app.db.mongo import connect_to_mongo
  await connect_to_mongo()
  response = await chat("open notepad", user_id=user_id, wait_for_execution=True, execution_timeout=30.0)
  print(response)

if __name__ == "__main__":
  asyncio.run(test_chat())  
