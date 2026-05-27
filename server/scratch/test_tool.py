import asyncio
import sys
sys.path.insert(0, '.')

from plugins.installed.web.tools.entity_search import EntitySearchTool

async def main():
    tool = EntitySearchTool()
    res = await tool._execute({
        "query": "cafe",
        "intent": "restaurant_search",
        "location": "Kathmandu, Nepal",
        "latitude": 27.7172,
        "longitude": 85.3240,
    })
    print("Success:", res.success)
    if res.success:
        print("Entities count:", len(res.data.get("entities", [])))
        for e in res.data.get("entities", [])[:3]:
            print("Name:", e.get("name"))
            print("Website:", e.get("website"))
            print("Images:", e.get("images"))
            print("-" * 20)

if __name__ == "__main__":
    asyncio.run(main())
