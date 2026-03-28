# from app.cache import cache_manager
# import json
# c = cache_manager
# user_id = "695e2bbaf8efc966aaf9f218"


# async def main():
#   q = input("Query : ")
#   rtx = await c.get_last_n_messages(user_id=user_id)
#   print("RTX : -*-------------------------------------------------",json.dumps(rtx, indent=2))

#   rtx = await c.process_query_and_get_context(user_id=user_id, current_query=q)
#   print("QTX : -*-------------------------------------------------",json.dumps(rtx, indent=2))

# if __name__ == "__main__":
#   import asyncio
#   while True:
#     asyncio.run(main())  

import asyncio
from dotenv import load_dotenv
load_dotenv()

from app.features.external_service.token_manager import get_valid_access_token
from app.db.mongo import connect_to_mongo
from app.cache import local_kv_manager , key_config

async def main():
    kv = local_kv_manager.LocalKVManager()
    # This triggers the full flow:
    # MongoDB → Google refresh → cache in LocalKVManager
    # await connect_to_mongo()
    # token = await get_valid_access_token(
    #     user_id="695e2bbaf8efc966aaf9f218",
    #     service="gmail"
    # )
    # print("Access token:", token[:30], "...")  # print first 30 chars
    token = await kv.get(f"oauth_access_token:gmail:695e2bbaf8efc966aaf9f218")
    print(token)
    
    token = await kv.get(f"oauth_refresh_token:gmail:695e2bbaf8efc966aaf9f218")
    print(token)

asyncio.run(main())