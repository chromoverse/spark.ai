from app.cache.redis.config import get_last_n_messages,compute_similarity,add_message,set_cache
from app.db.pinecone.config import search_user_queries,get_user_all_queries,upsert_query
import json

def test(query :str):
    """
    1. First fetch the local cached messages from redis
    2. If the messages is empty then load from pinecone
    3. Compute similarity between the current query and the cached messages
    4. If similarity is greater than threshold then use only redis context
    5. If similarity is less than threshold then fetch from pinecone
    6. Build the final prompt and generate response
    
    """
    context = []
    threshold = 0.35
    #1. First fetch the local cached messages from redis
    messages = get_last_n_messages("user_1", n=3)
    print("Last 3 Messages:", json.dumps(messages, indent=2))
    #2. If the messages is empty then load from pinecone
    if not messages:
        print("No messages found in Redis, fetching from Pinecone")
        messages = get_user_all_queries("user_1")
        for m in messages:
            add_message("user_1", "user", m["query"])
        print("Messages from Pinecone:", json.dumps(messages, indent=2))

    #3. Compute similarity between the current query and the cached messages
    similarity = compute_similarity(query, messages)
    print("Similarity score:", similarity)

    #4. If similarity is greater than threshold then use only redis context
    if similarity > threshold:
        print("Using Redis context")
        context = messages
    else:
        print("Fetching context from Pinecone")
        #5. If similarity is less than threshold then fetch from pinecone
        context = search_user_queries("user_1", query, top_k=3)
        print("Context from Pinecone:", json.dumps(context, indent=2))

    #6. Build the final prompt and generate response
    # final_prompt = build_prompt(query, context)
    # print("Final Prompt:", final_prompt)

test("what was name of my love girl?")    