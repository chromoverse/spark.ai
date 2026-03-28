import json
import os

base_dir = r"d:\siddhant-files\projects\ai_assistant\ai_local\tools_plugin"
files_to_sync = [
    os.path.join(base_dir, "registry", "tool_registry.json"),
    os.path.join(base_dir, "registry", "tool_index.json"),
    os.path.join(base_dir, "manifest.json")
]

NEW_VERSION = "2.4.0"

for filepath in files_to_sync:
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Update version
        if "version" in data:
            data["version"] = NEW_VERSION
            
        # Update tool count
        count = 0
        if "categories" in data:
            for cat_data in data["categories"].values():
                count += len(cat_data.get("tools", []))
            data["total_tools"] = count
            
        elif "tools" in data and isinstance(data["tools"], list):
            count = len(data["tools"])
            data["total_tools"] = count
            
        elif "plugins" in data and isinstance(data["plugins"], list):
            count = len(data["plugins"])
            # manifest.json doesn't typically have total_tools, but if requested we can add it or just ignore
            # the user said: "update the tool count and version in the tool_registry.json and tool_index.json and manifest.json"
            data["total_tools"] = count

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            
        print(f"Updated {os.path.basename(filepath)}: Version {NEW_VERSION}, Count {count}")
    else:
        print(f"File not found: {filepath}")

print("Sync complete.")
