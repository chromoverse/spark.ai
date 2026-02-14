from app.cache import redis_manager
import asyncio
from app.utils.format_context import format_context

async def main():
    user_id = "695e2bbaf8efc966aaf9f218"
    current_query = input("Enter a query to test context retrieval: ")
    context, from_cache = await redis_manager.process_query_and_get_context(user_id, current_query)
    # print(f"Context for query '{current_query}': {context}")
    recent_context = await redis_manager.get_last_n_messages(user_id, 10)
    rcx, formatted_context = format_context(recent_context, context)
    print(f"Formatted recent_context:\n" ,rcx)
    print(f"Formatted query_context:\n" ,formatted_context)
    print(f"Context retrieved from cache: {from_cache}")

if __name__ == "__main__":
    while True:
        asyncio.run(main())    