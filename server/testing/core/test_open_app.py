from app.client_core.tools.system.operations import OpenAppTool

async def main():
    tool = OpenAppTool()
    result = await tool.execute({"target": "cursor"})
    if result.success:
        print(f"OpenAppTool Result: {result.data}")

if __name__ == "__main__":
    import asyncio    
    asyncio.run(main())     