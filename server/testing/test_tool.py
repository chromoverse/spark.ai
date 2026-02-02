from app.registry.loader import get_tool_registry,load_tool_registry
from app.tools.loader import load_all_tools

def main():
  load_tool_registry()
  registry = get_tool_registry()
  data = registry.get_tool("web_search")
  print("data as params schema",data.params_schema)
  print("data as output schema",data.output_schema)

main()  