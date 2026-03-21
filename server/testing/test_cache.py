from app.cache import cache_manager
import asyncio
from app.utils.format_context import format_context

async def main():
    user_id = "695e2bbaf8efc966aaf9f218"
    current_query = "So Spark, tell me, who is your CEO?"
    print(f"Testing query: {current_query}")
    context, from_cache = await cache_manager.process_query_and_get_context(user_id, current_query)
    recent_context = await cache_manager.get_last_n_messages(user_id, 10)
    rcx, formatted_context = format_context(recent_context, context)
    print(f"Formatted recent_context:\n" ,rcx)
    print(f"Formatted query_context:\n" ,formatted_context)
    print(f"Context retrieved from cache: {from_cache}")

if __name__ == "__main__":
    asyncio.run(main())