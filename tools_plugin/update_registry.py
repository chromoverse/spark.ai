import json
import os

registry_path = r"d:\siddhant-files\projects\ai_assistant\ai_local\tools_plugin\registry\tool_registry.json"

with open(registry_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

for category_name, category_data in data.get("categories", {}).items():
    for tool in category_data.get("tools", []):
        if tool.get("tool_name", "").startswith("email_"):
            params = tool.get("params_schema", {})
            if "service" in params:
                del params["service"]
            
            # Ensure user_id is the primary requirement
            params["user_id"] = {
                "type": "string",
                "required": True,
                "description": "The user ID."
            }
            tool["params_schema"] = params

with open(registry_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)

print("Registry updated successfully.")
