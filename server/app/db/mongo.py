from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings
import logging
from typing import Optional


client: Optional[AsyncIOMotorClient] = None
db = None


async def connect_to_mongo():
    global client, db

    try:
        client = AsyncIOMotorClient(settings.mongo_uri)
        db = client[settings.db_name]
        print("✅ Async MongoDB connected")

    except Exception as e:
        logging.error(f"❌ MongoDB connection failed: {e}")
        raise e


async def close_mongo_connection():
    global client

    if client:
        client.close()
        print("✅ MongoDB connection closed")


def get_db():
    if db is None:
        raise RuntimeError("MongoDB not initialized")
    return db
