from app.registry.loader import get_tool_registry, load_tool_registry
import json

def main():
    load_tool_registry()
    tools_names = ["file_open", "web_search"]
    tool_schemas = get_tools_schema(tools_names)
    print(json.dumps(tool_schemas, indent=2))
    
def get_tools_schema(tools_names: list[str]) -> dict[str, dict]:
    """
    Get the schemas for the specified tools

    Args:
        tools_names: List of tool names to fetch schemas for
    """
    tool_registry = get_tool_registry()
    result = {}
    for tool_name in tools_names:
        tool = tool_registry.get_tool(tool_name)
        if tool:
            result[tool_name] = tool.__dict__
    return result
                                                                                    
if __name__ == "__main__":
    main()