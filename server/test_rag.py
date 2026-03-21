from app.cache import cache_manager
import json
c = cache_manager
user_id = "695e2bbaf8efc966aaf9f218"


async def main():
  q = input("Query : ")
  rtx = await c.get_last_n_messages(user_id=user_id)
  print("RTX : -*-------------------------------------------------",json.dumps(rtx, indent=2))

  rtx = await c.process_query_and_get_context(user_id=user_id, current_query=q)
  print("QTX : -*-------------------------------------------------",json.dumps(rtx, indent=2))

if __name__ == "__main__":
  import asyncio
  while True:
    asyncio.run(main())  

