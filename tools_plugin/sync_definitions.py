import json
import importlib
import inspect
from pathlib import Path
import sys
import os
from dotenv import load_dotenv

# Ensure tools_plugin and server are in path
sys.path.insert(0, r"d:\siddhant-files\projects\ai_assistant\ai_local")
sys.path.insert(0, r"d:\siddhant-files\projects\ai_assistant\ai_local\server")

# Load environment variables so Pydantic Settings don't fail
load_dotenv(r"d:\siddhant-files\projects\ai_assistant\ai_local\server\.env")

from tools_plugin.tools.base import BaseTool

def main():
    base_dir = Path(r"d:\siddhant-files\projects\ai_assistant\ai_local\tools_plugin")
    tools_dir = base_dir / "tools"
    registry_path = base_dir / "registry" / "tool_registry.json"
    index_path = base_dir / "registry" / "tool_index.json"
    manifest_path = base_dir / "manifest.json"

    # 1. Load the original registry
    with open(registry_path, "r", encoding="utf-8") as f:
        registry = json.load(f)

    # Convert registry categories into a flat lookup for index mapping
    registry_flat = {}
    for cat_name, cat_data in registry.get("categories", {}).items():
        for t in cat_data.get("tools", []):
            t["_category"] = cat_name
            registry_flat[t["tool_name"]] = t

    # 2. Dynamically introspect all Tool classes from Python source to build Manifest
    plugins = []
    
    # We walk through all files inside tools_plugin.tools.*
    # Exclude base files
    excluded_files = ["base.py", "loader.py", "schema_generator.py", "__init__.py"]
    
    for py_file in tools_dir.rglob("*.py"):
        if py_file.name in excluded_files:
            continue
        # Skip top level files that are not grouped in category folders if any
        if py_file.parent == tools_dir:
            continue
            
        rel_path = py_file.relative_to(tools_dir)
        module_path = ".".join(rel_path.with_suffix("").parts)
        full_module = f"tools_plugin.tools.{module_path}"
        
        try:
            mod = importlib.import_module(full_module)
            for cls_name, cls_obj in inspect.getmembers(mod, inspect.isclass):
                if issubclass(cls_obj, BaseTool) and cls_obj is not BaseTool:
                    if cls_obj.__module__ == full_module:
                        try:
                            instance = cls_obj()
                            t_name = instance.get_tool_name()
                            
                            if t_name in ["web_search", "web_scrape"]:
                                continue
                                
                            plugins.append({
                                "tool_name": t_name,
                                "module": module_path,
                                "class_name": cls_name
                            })
                        except Exception as e:
                            print(f"Skipping instantiation of {cls_name}: {e}")
        except Exception as e:
            print(f"Failed to load {full_module}: {e}")

    # 3. Build tool_index.json from discovered plugins and their registry definitions
    index_tools = []
    for p in plugins:
        t_name = p["tool_name"]
        reg_data = registry_flat.get(t_name)
        if not reg_data:
            print(f"Warning: Tool '{t_name}' found in code but missing from tool_registry.json!")
            continue
            
        index_tools.append({
            "name": t_name,
            "description": reg_data.get("description", ""),
            "category": reg_data.get("_category", "system"),
            "execution_target": reg_data.get("execution_target", "server")
        })

    # 4. Save manifest.json
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    
    manifest_version = manifest.get("version", "2.4.0")
    
    # Optional: we can match existing manifest layout
    new_manifest = {
        "version": manifest_version,
        "source": "tools_plugin",
        "registry_relpath": "registry/tool_registry.json",
        "plugins": plugins,
        "total_tools": len(plugins)
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(new_manifest, f, indent=2)

    # 5. Save tool_index.json
    new_index = {
        "version": registry.get("version", "2.4.1"),
        "total_tools": len(index_tools),
        "tools": index_tools
    }
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(new_index, f, indent=2)

    print(f"Sync complete! Excluded web_search and web_scrape. Total tools synced: {len(plugins)}")

if __name__ == "__main__":
    main()
