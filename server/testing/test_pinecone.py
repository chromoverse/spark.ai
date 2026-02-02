from app.db.pinecone.config import (
    upsert_query, 
    get_user_all_queries, 
    search_user_queries,
    get_index_stats,
    delete_user_all_queries
)
import time
import json

def test_upsert():
    """Test upserting queries"""
    print("\n=== Testing Upsert ===")
    upsert_query("user_1", "Hey i loved one girl very much, Her name was ankita.")
    upsert_query("user_1", "I thought she would love me as i do . ")
    upsert_query("user_1", "I loved her so much , i could not stop thinking about her and i was so happy.")
    
    # Wait for indexing
    print("\n⏳ Waiting 5 seconds for Pinecone to index...")
    time.sleep(5)


def test_get_all():
    queries = get_user_all_queries("user_1", top_k=5)
    print(f"\nAll queries for user_1 {json.dumps(queries, indent=2)} found):")
    


def test_search():
    results = search_user_queries("user_1", "Ankita was the love of my life", top_k=5)
    print(f"{json.dumps(results, indent=2)}")
    # for i, result in enumerate(results, 1):
    #     print(f"  {i}. Query: {result['query']}")
    #     print(f"     Score: {result['score']:.4f}")
    #     print()


def test_stats():
    """Test index statistics"""
    print("\n=== Index Statistics ===")
    stats = get_index_stats()
    print(f"Total vectors: {stats.get('total_vector_count', 0)}")
    namespaces = stats.get('namespaces', {})
    for ns_name, ns_data in namespaces.items():
        print(f"Namespace '{ns_name}': {ns_data.get('vector_count', 0)} vectors")

def test_delete_all():
    """Test deleting all queries for a user"""
    print("\n=== Testing Delete All Queries ===")
    delete_user_all_queries("user_1")
    print("All queries for user_1 deleted.")

if __name__ == "__main__":
    # Uncomment the test you want to run:
    
    # First time: Insert data
    # test_upsert()
    
    # # # # After data is inserted and indexed:
    # test_get_all()
    test_delete_all()
    # test_search()
    # test_stats()
