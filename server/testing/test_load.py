from app.cache.user_cache import UserCache


async def get_user_cache():
  ca = UserCache()
  id = "695e2bbaf8efc966aaf9f218"
  await ca.update_user_field(id, "ai_gender", "male")
  data = await ca.get_user(id)
  print(data)

if __name__ == "__main__" :
  import asyncio
  asyncio.run(get_user_cache())  