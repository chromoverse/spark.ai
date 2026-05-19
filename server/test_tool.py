  
from scripts.tool_tester import list_tools, describe_tool, test_tool, tools
  
list_tools()                          # all tools, grouped by category
# describe_tool("app_open")             # full schema + examples
# await test_tool("app_open", target="chrome")
# await tools.app_open(target="chrome") # IDE autocompletes after stub gen
  
if __name__ == "__main__":
  import asyncio
  asyncio.run(test_tool("sound_increase", target="chrome"))  