from app.services.chat_service import chat
import asyncio


async def init():
    """Run full startup: DB + agent system init"""
    from app.db.mongo import connect_to_mongo
    await connect_to_mongo()
    
    # Run startup registrations (loads tools, wires emitter, etc.)
    import app.startup_registrations  # noqa: F401 - registers initializers
    from app.auto_initializer import run_all
    await run_all()


async def test_chat():
    user_id = "695e2bbaf8efc966aaf9f218"
    query = input("Enter your query: ")
    response = await chat(query, user_id=user_id, wait_for_execution=True, execution_timeout=30.0)
    print(response)


if __name__ == "__main__":
    # Init once
    asyncio.run(init())
    
    # Chat loop
    while True:
        asyncio.run(test_chat())
