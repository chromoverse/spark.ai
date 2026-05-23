import asyncio
import os
import sys

# Add server directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from plugins.installed.web.tools.research import WebResearchTool

async def test():
    tool = WebResearchTool()
    inputs = {
        "query": "hotels near me",
        "intent": "hotel_search",
        "max_results": 5
    }
    
    # Mock context or inputs
    print("Executing WebResearchTool...")
    output = await tool.execute(inputs)
    print("Success:", output.success)
    if output.data:
        entities = output.data.get("entities", [])
        print(f"Number of entities returned: {len(entities)}")
        for i, ent in enumerate(entities[:3]):
            print(f"Entity {i+1}: {ent.get('name')} | price: {ent.get('price_per_night')} | rating: {ent.get('rating')}")
    else:
        print("No data in output")

if __name__ == "__main__":
    asyncio.run(test())
