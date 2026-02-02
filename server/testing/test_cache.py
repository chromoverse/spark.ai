
import asyncio
import sys
import os

# Add app root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.cache import load_user, get_current_user_cached, log_cache_performance

async def main():
    print("\n--- Testing User Cache ---")
    user = await load_user("guest")
    print("User Data:", user)
    
    a = log_cache_performance()
    print("Cache Performance Logged:", a)

if __name__ == "__main__":
    asyncio.run(main())