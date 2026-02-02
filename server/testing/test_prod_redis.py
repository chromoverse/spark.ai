"""
Complete Test Suite for Redis Manager
Tests all functionality with both local and Upstash Redis
"""
import asyncio
import json
from app.cache.redis.config import (
    redis_manager,
    # Cache functions
    set_cache, get_cache, delete_cache, clear_cache,
    # Conversation functions
    add_message, get_last_n_messages, clear_conversation_history,
    # User details functions
    set_user_details, get_user_details, clear_user_details, 
    update_user_details, clear_all_user_data,
    # Embedding & search functions
    get_embeddings_for_messages, semantic_search_messages,
    warm_embedding_cache, clear_embedding_cache, 
    get_embedding_cache_stats, process_query_and_get_context
)


async def test_basic_operations():
    """Test basic Redis operations"""
    print("\n=== Testing Basic Operations ===")
    user_id = "test_user_123"
    
    # Test set/get
    await redis_manager.set(f"test:{user_id}:key1", "value1")
    value = await redis_manager.get(f"test:{user_id}:key1")
    print(f"✓ Set/Get: {value}")
    assert value == "value1"
    
    # Test delete
    await redis_manager.delete(f"test:{user_id}:key1")
    value = await redis_manager.get(f"test:{user_id}:key1")
    print(f"✓ Delete: {value}")
    assert value is None
    
    # Test with expiration
    await redis_manager.set(f"test:{user_id}:key2", "value2", ex=60)
    value = await redis_manager.get(f"test:{user_id}:key2")
    print(f"✓ Set with expiration: {value}")
    assert value == "value2"
    
    print("✅ Basic operations passed!")


async def test_cache_operations():
    """Test cache operations"""
    print("\n=== Testing Cache Operations ===")
    user_id = "test_user_123"
    
    # Set cache
    # await set_cache(user_id, "preferences", {"theme": "dark", "lang": "en"})
    # await set_cache(user_id, "session", {"token": "abc123", "expires": "2024-12-31"})
    
    # Get cache
    prefs = await get_cache(user_id, "preferences")
    print(f"✓ Set/Get cache: {prefs}")
    prefs = await get_cache(user_id, "session")
    print(f"✓ Set/Get cache: {prefs}")
    prefs = await get_cache(user_id, "settings")
    print(f"✓ Set/Get cache: {prefs}")
    prefs = await get_cache(user_id, "profile")
    print(f"✓ Set/Get cache: {prefs}")
    
    # # Set multiple cache items
    # await set_cache(user_id, "settings", {"notifications": True})
    # await set_cache(user_id, "profile", {"name": "Test User"})
    
    # Delete specific cache
    # await delete_cache(user_id, "settings")
    # settings = await get_cache(user_id, "settings")
    # print(f"✓ Delete cache: {settings}")
    # assert settings is None
    
    # Clear all cache
    # await clear_cache(user_id)
    # prefs = await get_cache(user_id, "preferences")
    # print(f"✓ Clear all cache: {prefs}")
    # assert prefs is None
    
    print("✅ Cache operations passed!")


async def test_conversation_history():
    """Test conversation history"""
    print("\n=== Testing Conversation History ===")
    user_id = "test_user_123"
    
    # Clear previous history
    # await clear_conversation_history(user_id)
    
    # Add messages
    await add_message(user_id, "user", "Hello, how are you?")
    await add_message(user_id, "assistant", "I'm doing well, thank you!")
    await add_message(user_id, "user", "What's the weather like?")
    await add_message(user_id, "assistant", "I don't have access to weather data.")
    
    # Get last 2 messages
    messages = await get_last_n_messages(user_id)
    print(f"✓ Last  messages: {messages}")
    
    # Get all messages
    all_messages = await get_last_n_messages(user_id, 10)
    print(f"✓ All messages: {len(all_messages)} messages")
    assert len(all_messages) == 4
    
    # Verify message structure
    msg = all_messages[0]
    assert "role" in msg
    assert "content" in msg
    assert "timestamp" in msg
    print(f"✓ Message structure: {msg.keys()}")
    
    # Clear history
    # await clear_conversation_history(user_id)
    # messages = await get_last_n_messages(user_id, 10)
    # print(f"✓ Clear history: {len(messages)} messages")
    # assert len(messages) == 0
    
    print("✅ Conversation history passed!")


async def test_user_details():
    """Test user details operations"""
    print("\n=== Testing User Details ===")
    user_id = "test_user_123"
    
   
    from app.cache.load_user import load_user
    details = await load_user("695e2bbaf8efc966aaf9f218")
    await set_user_details("guest", details)
    
    # Get user details
    details = await get_user_details("guest")
    print(f"✓ User details: {details}")
    
    print("✅ User details passed!")


async def test_embedding_cache():
    """Test embedding cache operations"""
    print("\n=== Testing Embedding Cache ===")
    user_id = "test_user_123"
    
    # Clear previous cache
    await clear_embedding_cache(user_id)
    
    # Add some messages for embedding
    await clear_conversation_history(user_id)
    messages = [
        "What is machine learning?",
        "How does neural network work?",
        "Explain deep learning",
        "What is artificial intelligence?"
    ]
    
    for msg in messages:
        await add_message(user_id, "user", msg)
    
    # Wait a bit for background embedding caching
    await asyncio.sleep(1)
    
    # Get cache stats
    stats = await get_embedding_cache_stats(user_id)
    print(f"✓ Cache stats: {stats}")
    if stats:
        print(f"  - Total cached: {stats.get('total_cached', 0)}")
        print(f"  - Memory: {stats.get('estimated_memory_mb', 0):.2f} MB")
    
    # Warm cache (pre-compute embeddings)
    cached_count = await warm_embedding_cache(user_id, 10)
    print(f"✓ Warmed cache: {cached_count} messages")
    
    # Get stats again
    stats = await get_embedding_cache_stats(user_id)
    print(f"✓ Cache stats after warming: {stats}")
    
    # Clear cache
    cleared = await clear_embedding_cache(user_id)
    print(f"✓ Cleared cache: {cleared} entries")
    
    print("✅ Embedding cache passed!")


async def test_semantic_search():
    """Test semantic search functionality"""
    print("\n=== Testing Semantic Search ===")
    user_id = "test_user_123"
    
    # Clear and setup
    await clear_conversation_history(user_id)
    await clear_embedding_cache(user_id)
    
    # Add diverse messages
    messages = [
        "I love programming in Python",
        "Machine learning is fascinating",
        "The weather is nice today",
        "Neural networks are powerful",
        "I enjoy hiking in the mountains",
        "Deep learning requires lots of data",
        "My favorite food is pizza",
        "AI is transforming the world",
        "Love to read books on technology",
        "I liked one girl who loved artificial intelligence"
    ]
    
    for msg in messages:
        await add_message(user_id, "user", msg)
    
    # Warm cache for faster search
    await warm_embedding_cache(user_id, 10)
    
    # Search for AI-related content
    print("\n🔍 Searching for 'artificial intelligence'...")
    results = await semantic_search_messages(
        user_id=user_id,
        query="i loved her so much",
        n=10,
        top_k=3,
        threshold=0.3
    )
    
    print(f"✓ Found {len(results)} results")
    for result in results:
        print(f"  [{result['_rank']}] Score: {result['_similarity_score']:.3f} - {result['content'][:60]}")
    
    # Search for food-related content
    print("\n🔍 Searching for 'food and eating'...")
    results = await semantic_search_messages(
        user_id=user_id,
        query="food and eating",
        n=10,
        top_k=2,
        threshold=0.3
    )
    
    print(f"✓ Found {len(results)} results")
    for result in results:
        print(f"  [{result['_rank']}] Score: {result['_similarity_score']:.3f} - {result['content'][:60]}")
    
    assert len(results) > 0
    
    print("✅ Semantic search passed!")


async def test_process_query_context():
    """Test process_query_and_get_context (hybrid Redis/Pinecone)"""
    print("\n=== Testing Process Query Context ===")
    user_id = "test_user_123"
    
    # Setup conversation
    # await clear_conversation_history(user_id)
    
    messages = [
        "Tell me about Python programming",
        "How do I use async/await in Python?",
        "What are decorators?",
    ]
    
    for msg in messages:
        await add_message(user_id, "user", msg)
    
    # Warm cache
    await warm_embedding_cache(user_id, 10)
    
    # Process query and get context
    print("\n🔍 Processing query: 'explain Python asyncio'...")
    context, is_pinecone = await process_query_and_get_context(
        user_id=user_id,
        current_query="explain Python asyncio"
    )
    
    print(f"✓ Context source: {'Pinecone' if is_pinecone else 'Redis'}")
    print(f"✓ Context items: {len(context)}")
    
    if context:
        print("\nTop context:")
        for i, item in enumerate(context[:3], 1):
            content = item.get('content', str(item))[:60]
            print(f"  [{i}] {content}")
    
    print("✅ Process query context passed!")


async def test_pipeline_operations():
    """Test pipeline batch operations"""
    print("\n=== Testing Pipeline Operations ===")
    user_id = "test_user_123"
    
    # Test batch set using pipeline
    pipeline = await redis_manager.pipeline()
    
    for i in range(5):
        pipeline.setex(f"test:{user_id}:batch_{i}", 60, f"value_{i}")
    
    results = await pipeline.execute()
    print(f"✓ Batch set: {len(results)} operations")
    
    # Test batch get using pipeline
    pipeline = await redis_manager.pipeline()
    
    for i in range(5):
        pipeline.get(f"test:{user_id}:batch_{i}")
    
    values = await pipeline.execute()
    print(f"✓ Batch get: {values}")
    assert len(values) == 5
    
    # Cleanup
    keys = [f"test:{user_id}:batch_{i}" for i in range(5)]
    await redis_manager.delete(*keys)
    
    print("✅ Pipeline operations passed!")


async def test_clear_all_data():
    """Test clearing all user data"""
    print("\n=== Testing Clear All Data ===")
    user_id = "test_user_cleanup"
    
    # Create various data
    await set_cache(user_id, "test1", {"data": "value1"})
    await set_cache(user_id, "test2", {"data": "value2"})
    await add_message(user_id, "user", "Test message")
    await set_user_details(user_id, {"name": "Test"})
    
    # Clear all
    await clear_all_user_data(user_id)
    
    # Verify all cleared
    cache = await get_cache(user_id, "test1")
    messages = await get_last_n_messages(user_id, 10)
    details = await get_user_details(user_id)
    
    print(f"✓ Cache cleared: {cache}")
    print(f"✓ Messages cleared: {len(messages)}")
    print(f"✓ Details cleared: {details}")
    
    assert cache is None
    assert len(messages) == 0
    assert details is None
    
    print("✅ Clear all data passed!")


async def test_connection_info():
    """Display connection information"""
    print("\n=== Connection Information ===")
    
    # Initialize the client
    await redis_manager.initialize()
    
    print(f"✓ Redis Type: {'Upstash' if redis_manager._is_upstash else 'Local Docker'}")
    print(f"✓ Client initialized: {redis_manager.client is not None}")
    
    # Test ping
    try:
        await redis_manager._ensure_client()
        print("✓ Connection: Active")
    except Exception as e:
        print(f"✗ Connection: Failed - {e}")


async def main():
    """Run all tests"""
    print("=" * 60)
    print("🧪 REDIS MANAGER TEST SUITE")
    print("=" * 60)
    
    try:
        # Connection info
        await test_connection_info()
        
        # # Basic tests
        # await test_basic_operations()
        # await test_cache_operations()
        # await test_conversation_history()
        await test_user_details()
        # await test_pipeline_operations()
        
        # # # Advanced tests (require embedding service)
        # try:
        #     await test_embedding_cache()
        #     await test_semantic_search()
        #     await test_process_query_context()
        # except ImportError:
        #     print("\n⚠️  Skipping embedding tests (embedding_service not available)")
        
        # # # Cleanup tests
        # # await test_clear_all_data()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())