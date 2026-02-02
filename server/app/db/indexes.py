from app.db.mongo import get_db
from pymongo.errors import PyMongoError
import logging

async def create_indexes():
    try:
        db = get_db()

        await db.chats.create_index(
            [("user_id", 1), ("created_at", -1)],
            background=True
        )

        await db.memory.create_index(
            "user_id",
            background=True
        )

        await db.memory.create_index(
            "importance",
            background=True
        )

        logging.info("✅ MongoDB indexes created")

    except PyMongoError as e:
        logging.error(f"⚠️ MongoDB index creation failed: {e}")

    except Exception as e:
        logging.error(f"⚠️ Unexpected error while creating indexes: {e}")
