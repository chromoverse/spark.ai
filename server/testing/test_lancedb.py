"""
Debug script for LanceDB - inspect and clean data
WITH MODEL PRELOADING - Load models once, run tests multiple times
"""
import asyncio
import json
from app.cache import RedisManager

# Global flag to track if models are loaded
_MODELS_LOADED = False

async def ensure_models_loaded():
    """Load models once at startup"""
    global _MODELS_LOADED
    
    if _MODELS_LOADED:
        print("✅ Models already loaded, skipping...")
        return
    
    print("\n" + "=" * 80)
    print("🔄 LOADING MODELS (one-time initialization)...")
    print("=" * 80)
    
    try:
        from app.services.embedding_services import embedding_service
        
        # Trigger model loading by embedding a dummy text
        print("Loading embedding model...")
        await embedding_service.embed_single("test")
        
        print("✅ All models loaded successfully!")
        _MODELS_LOADED = True
        
    except Exception as e:
        print(f"❌ Error loading models: {e}")
        raise


async def inspect_all_data():
    """Show all data in LanceDB"""
    config = RedisManager()
    
    print("\n" + "=" * 80)
    print("INSPECTING LANCEDB DATA")
    print("=" * 80)
    
    # Get stats
    if hasattr(config.client, 'get_table_stats'):
        stats = await config.client.get_table_stats()
        print("\n📊 DATABASE STATS:")
        print(json.dumps(stats, indent=2))
    
    # Get all messages for user123
    print("\n" + "=" * 80)
    print("ALL MESSAGES FOR user123:")
    print("=" * 80)
    
    messages = await config.get_last_n_messages("user123", 1000)
    
    if not messages:
        print("❌ No messages found!")
        return
    
    print(f"\nTotal messages: {len(messages)}\n")
    
    # Group by content to find duplicates
    content_count = {}
    for msg in messages:
        content = msg.get("content", "")
        content_count[content] = content_count.get(content, 0) + 1
    
    print("📝 Message frequency:")
    for content, count in sorted(content_count.items(), key=lambda x: x[1], reverse=True):
        emoji = "🔴" if count > 1 else "✅"
        print(f"{emoji} [{count}x] {content[:60]}...")
    
    print("\n" + "=" * 80)
    print("FULL MESSAGE LIST (chronological):")
    print("=" * 80)
    for i, msg in enumerate(messages, 1):
        print(f"\n{i}. [{msg.get('role', 'unknown')}] @ {msg.get('timestamp', 'no-timestamp')}")
        print(f"   Content: {msg.get('content', '')[:100]}")


async def clear_all_user123_data():
    """Clear all data for user123"""
    config = RedisManager()
     
    print("\n" + "=" * 80)
    print("🗑️  CLEARING ALL DATA FOR user123")
    print("=" * 80)
    
    result = await config.client.clear_user_data("user123")
    
    if result:
        print("✅ Data cleared successfully!")
    else:
        print("❌ Failed to clear data")
    
    # Verify
    messages = await config.get_last_n_messages("user123", 10)
    print(f"\nVerification: {len(messages)} messages remaining")


async def add_test_messages():
    """Add clean test messages"""
    config = RedisManager()
    
    print("\n" + "=" * 80)
    print("📝 ADDING TEST MESSAGES")
    print("=" * 80)
    
    test_messages = [
        ("user", "Hello, how are you today?"),
        ("assistant", "I'm doing great! How can I help you?"),
        ("user", "I loved the movie Inception, it was mind-blowing!"),
        ("assistant", "Inception is indeed a masterpiece! The dream layers concept was brilliant."),
        ("user", "Loving someone from the heart is the most beautiful feeling."),
        ("assistant", "That's a wonderful sentiment. Love truly is special."),
        ("user", "AI and machine learning are shaping the future of technology."),
        ("assistant", "Absolutely! The advancements in AI are transforming many industries."),
        ("user", "What's your opinion on quantum computing?"),
        ("assistant", "Quantum computing has incredible potential for solving complex problems."),
    ]
    
    # Try batch method if available
    if hasattr(config, 'add_messages_batch'):
        print("Using batch method for faster insertion...")
        count = await config.add_messages_batch("user123", test_messages)
        print(f"✅ Batch added {count}/{len(test_messages)} messages")
    else:
        # Fallback to individual adds
        print("Using individual add method...")
        for role, content in test_messages:
            await config.add_message("user123", role, content)
            print(f"✅ Added: [{role}] {content[:50]}...")
            await asyncio.sleep(0.1)  # Small delay to ensure different timestamps
        print(f"\n✅ Added {len(test_messages)} messages")


async def test_semantic_search():
    """Test semantic search functionality"""
    config = RedisManager()
    
    print("\n" + "=" * 80)
    print("🔍 TESTING SEMANTIC SEARCH")
    print("=" * 80)
    
    queries = [
        ("Love is the purest emotion", 0.5),
        ("Tell me about artificial intelligence", 0.5),
        ("Christopher Nolan films", 0.4),
        ("Computing and technology", 0.5),
    ]
    
    for query, threshold in queries:
        print(f"\n{'=' * 80}")
        print(f"Query: '{query}' (threshold={threshold})")
        print('=' * 80)
        
        results = await config.semantic_search_messages(
            "user123", 
            query, 
            top_k=3,
            threshold=threshold
        )
        
        if not results:
            print("❌ No results found")
            continue
        
        print(f"\nFound {len(results)} results:\n")
        for i, result in enumerate(results, 1):
            score = result.get("_similarity_score", 0)
            content = result.get("content", "")
            role = result.get("role", "unknown")
            
            print(f"{i}. Score: {score:.4f} | [{role}]")
            print(f"   {content[:100]}...")


async def custom_search():
    """Run a custom search query"""
    config = RedisManager()
    
    print("\n" + "=" * 80)
    print("🔍 CUSTOM SEMANTIC SEARCH")
    print("=" * 80)
    
    query = input("\nEnter your search query: ").strip()
    if not query:
        print("❌ Empty query!")
        return
    
    threshold = input("Enter similarity threshold (default 0.5): ").strip()
    threshold = float(threshold) if threshold else 0.5
    
    top_k = input("Enter number of results (default 5): ").strip()
    top_k = int(top_k) if top_k else 5
    
    print(f"\n{'=' * 80}")
    print(f"Searching for: '{query}'")
    print(f"Threshold: {threshold}, Top K: {top_k}")
    print('=' * 80)
    
    results = await config.semantic_search_messages(
        "user123", 
        query, 
        top_k=top_k,
        threshold=threshold
    )
    
    if not results:
        print("\n❌ No results found!")
        return
    
    print(f"\n✅ Found {len(results)} results:\n")
    for i, result in enumerate(results, 1):
        score = result.get("_similarity_score", 0)
        content = result.get("content", "")
        role = result.get("role", "unknown")
        timestamp = result.get("timestamp", "unknown")
        
        print(f"{i}. Score: {score:.4f}")
        print(f"   Role: {role}")
        print(f"   Time: {timestamp}")
        print(f"   Content: {content}")
        print()


async def show_menu():
    """Display interactive menu"""
    print("\n" + "=" * 80)
    print("LANCEDB DEBUG TOOL - INTERACTIVE MODE")
    print("=" * 80)
    print("\nAvailable commands:")
    print("  1. Inspect all data")
    print("  2. Clear all user123 data")
    print("  3. Add test messages")
    print("  4. Test semantic search (predefined queries)")
    print("  5. Custom semantic search (your own query)")
    print("  6. Full cleanup and rebuild (2 → 3 → 4)")
    print("  7. Quick test (1 → 4)")
    print("  0. Exit")
    print("=" * 80)


async def run_interactive_loop():
    """Main interactive loop - models loaded once"""
    
    # Load models ONCE at startup
    await ensure_models_loaded()
    
    while True:
        await show_menu()
        
        choice = input("\nEnter your choice (0-7): ").strip()
        
        if choice == "0":
            print("\n👋 Goodbye!")
            break
        
        elif choice == "1":
            await inspect_all_data()
        
        elif choice == "2":
            confirm = input("\n⚠️  This will delete all user123 data! Continue? (yes/no): ").strip().lower()
            if confirm == "yes":
                await clear_all_user123_data()
            else:
                print("❌ Cancelled")
        
        elif choice == "3":
            await add_test_messages()
        
        elif choice == "4":
            await test_semantic_search()
        
        elif choice == "5":
            await custom_search()
        
        elif choice == "6":
            confirm = input("\n⚠️  This will delete all user123 data and rebuild! Continue? (yes/no): ").strip().lower()
            if confirm == "yes":
                await clear_all_user123_data()
                await asyncio.sleep(0.5)
                await add_test_messages()
                await asyncio.sleep(0.5)
                await test_semantic_search()
            else:
                print("❌ Cancelled")
        
        elif choice == "7":
            await inspect_all_data()
            await asyncio.sleep(0.5)
            await test_semantic_search()
        
        else:
            print("❌ Invalid choice! Please enter 0-7.")
        
        # Pause before showing menu again
        input("\nPress Enter to continue...")


async def main():
    """Entry point"""
    try:
        await run_interactive_loop()
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user. Goodbye!")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())