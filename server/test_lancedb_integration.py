import sys
import asyncio
import os
from datetime import datetime

async def test_redis_manager():
    print("🚀 Starting RedisManager Integration Test")
  
    from app.cache import redis_manager
    
    # Ensure initialization
    await redis_manager._ensure_client()
    
    if redis_manager:
        print("✅ RedisManager successfully initialized with LanceDB")
    else:
        print("❌ RedisManager failed to initialize with LanceDB")
        return

    # 3. Test User Details (KV Store)
    print("\n--- Testing User Details (KV Store) ---")
    user_id = "test_user_123"
    user_details = {
        "name": "Test User",
        "email": "test@example.com",
        "quota_reached": False
    }
    
    await redis_manager.set_user_details(user_id, user_details)
    retrieved = await redis_manager.get_user_details(user_id)
    print(f"Set/Get User Details: {retrieved}")
    
    if retrieved and retrieved.get("name") == "Test User":
        print("✅ User details Set/Get working")
    else:
        print("❌ User details Set/Get failed")

    # 4. Test Chat History
    print("\n--- Testing Chat History ---")
    
    # Clear previous data
    await redis_manager.clear_conversation_history(user_id)
    
    # Add messages using RedisManager
    print("Adding messages via redis_manager.add_message()...")
    await redis_manager.add_message(user_id, "user", "I love artificial intelligence")
    await redis_manager.add_message(user_id, "assistant", "That's great! AI is fascinating.")
    await redis_manager.add_message(user_id, "assistant", "Artificial intelligence can solve complex problems.")
    await redis_manager.add_message(user_id, "assistant", "LLMs can do amazing things.")
    await redis_manager.add_message(user_id, "user", "What is your favorite programming language?")
    await redis_manager.add_message(user_id, "user", "I loved myself so much.")
    await redis_manager.add_message(user_id, "user", "I was sick and tired.")
    await redis_manager.add_message(user_id, "user", "Girl is the best")
    await redis_manager.add_message(user_id, "user", "Snacks are best.")
    
    # Small delay for embeddings
    await asyncio.sleep(1)
    
    # Get History using RedisManager
    history = await redis_manager.get_last_n_messages(user_id, 10)
    print(f"\nHistory Retrieved: {len(history)} messages")
    for msg in history:
        print(f" - [{msg['role']}] {msg['content']}")
    
    if len(history) == 5:
        print("✅ Chat history working (no duplicates)")
    else:
        print(f"⚠️ Chat history returned {len(history)} messages (expected 5)")

    # 5. Semantic Search using RedisManager
    print("\n--- Testing Semantic Search ---")
    query = "how does it feel to get sick girl ?"
    results = await redis_manager.semantic_search_messages(user_id, query, top_k=5, threshold=0.2)
    
    print(f"\nSearch results for '{query}':")
    found_love = False
    for res in results:
        print(f" - Score: {res['_similarity_score']:.4f} | {res['content']}")
        if "love" in res['content'].lower():
            found_love = True
    
    if found_love and len(results) > 0:
        print("✅ Semantic search working correctly")
    else:
        print("⚠️ Semantic search might need threshold adjustment")

    # # 6. Test Generic Cache
    # print("\n--- Testing Generic Cache ---")
    # await redis_manager.set_cache(user_id, "test_key", {"data": "test_value"}, expire=300)
    # cached_data = await redis_manager.get_cache(user_id, "test_key")
    # print(f"Generic cache result: {cached_data}")
    
    # if cached_data and cached_data.get("data") == "test_value":
    #     print("✅ Generic cache working")
    # else:
    #     print("❌ Generic cache failed")

    # # 7. Test Batch Message Add
    # print("\n--- Testing Batch Message Add ---")
    # batch_messages = [
    #     ("user", "Python is amazing"),
    #     ("assistant", "Indeed, Python is a versatile language."),
    #     ("user", "Do you like coffee?"),
    # ]
    
    # added_count = await redis_manager.add_messages_batch(user_id, batch_messages)
    # print(f"Batch added {added_count} messages")
    
    # if added_count == 3:
    #     print("✅ Batch message add working")
    # else:
    #     print(f"⚠️ Batch add returned {added_count} (expected 3)")

    # # 8. Get updated history
    # all_history = await redis_manager.get_last_n_messages(user_id, 20)
    # print(f"\n📊 Total messages in history: {len(all_history)}")

    # # 9. Test Clear All User Data
    # print("\n--- Testing Clear All User Data ---")
    # await redis_manager.clear_all_user_data(user_id)
    # history_after_clear = await redis_manager.get_last_n_messages(user_id, 10)
    # print(f"Messages after clear: {len(history_after_clear)}")
    
    # if len(history_after_clear) == 0:
    #     print("✅ Clear all user data working")
    # else:
    #     print(f"⚠️ Still {len(history_after_clear)} messages remain after clear")

    print("\n✅ RedisManager Integration Test Completed")


async def test_convenience_functions():
    print("\n🔧 Testing Convenience Functions")
    
    from app.cache import (
        add_message,
        get_last_n_messages,
        semantic_search_messages,
        set_user_details,
        
        get_user_details, load_user, clear_user_details
    )

    from app.db.mongo import connect_to_mongo
    await connect_to_mongo()
    
    user_id = "695e2bbaf8efc966aaf9f218"
    await clear_user_details(user_id)
    user_data = await load_user(user_id)
    # Test via convenience functions
    await set_user_details(user_id, user_data)
    details = await get_user_details(user_id)
    print(f"Convenience get_user_details: {details}")
    
    # await add_message(user_id, "user", "Testing convenience functions")
    # history = await get_last_n_messages(user_id, 5)
    # print(f"Convenience get_last_n_messages: {len(history)} messages")
    
    # results = await semantic_search_messages(user_id, "convenience", top_k=2)
    # print(f"Convenience semantic_search: {len(results)} results")
    
    print("✅ Convenience functions working")


if __name__ == "__main__":
    # asyncio.run(test_redis_manager())
    asyncio.run(test_convenience_functions())