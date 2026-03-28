import json
import os
import re

base_dir = r"d:\siddhant-files\projects\ai_assistant\ai_local\tools_plugin"
registry_path = os.path.join(base_dir, "registry", "tool_registry.json")
manifest_path = os.path.join(base_dir, "manifest.json")
tools_dir = os.path.join(base_dir, "tools")

with open(registry_path, 'r', encoding='utf-8') as f:
    reg_data = json.load(f)

# Build a map of tool_name -> schemas
tool_schemas = {}
for cat_name, cat_data in reg_data.get("categories", {}).items():
    for tool in cat_data.get("tools", []):
        tool_schemas[tool["tool_name"]] = {
            "params": tool.get("params_schema", {}),
            "outputs": tool.get("output_schema", {"data": {}})
        }

with open(manifest_path, 'r', encoding='utf-8') as f:
    man_data = json.load(f)

# Group by file to minimize I/O
file_updates = {}
for plugin in man_data.get("plugins", []):
    tool_name = plugin["tool_name"]
    # Skip if we don't have schema for it
    if tool_name not in tool_schemas:
        continue
        
    module_parts = plugin["module"].split(".")
    filepath = os.path.join(tools_dir, *module_parts) + ".py"
    class_name = plugin["class_name"]
    
    if filepath not in file_updates:
        file_updates[filepath] = []
        
    file_updates[filepath].append({
        "class_name": class_name,
        "tool_name": tool_name,
        "schemas": tool_schemas[tool_name]
    })

def generate_docstring_append(schemas):
    lines = []
    lines.append("    Inputs:")
    params = schemas["params"]
    if not params:
        lines.append("    - (None)")
    else:
        for p_name, p_data in params.items():
            p_type = p_data.get("type", "any")
            req = "required" if p_data.get("required") else "optional"
            desc = p_data.get("description", "")
            if desc:
                # remove newlines from description
                desc = desc.replace("\n", " ").strip()
                lines.append(f"    - {p_name} ({p_type}, {req}): {desc}")
            else:
                lines.append(f"    - {p_name} ({p_type}, {req})")
                
    lines.append("\n    Outputs:")
    output_data = schemas["outputs"].get("data", {})
    if not output_data:
        lines.append("    - (None)")
    else:
        for o_name, o_data in output_data.items():
            o_type = o_data.get("type", "any")
            desc = o_data.get("description", "")
            if desc:
                desc = desc.replace("\n", " ").strip()
                lines.append(f"    - {o_name} ({o_type}): {desc}")
            else:
                lines.append(f"    - {o_name} ({o_type})")
                
    return "\n".join(lines)

for filepath, classes in file_updates.items():
    if not os.path.exists(filepath):
        continue
        
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    modified = False
    
    for cls_info in classes:
        cname = cls_info["class_name"]
        
        # Pattern 1: Class has a docstring """...""" immediately following
        pattern_with_doc = re.compile(rf'(class\s+{cname}\b.*?:[ \t]*\n[ \t]*\"\"\")(.*?)(\"\"\")', re.DOTALL)
        match_doc = pattern_with_doc.search(content)
        
        if match_doc:
            head = match_doc.group(1)
            body = match_doc.group(2)
            tail = match_doc.group(3)
            
            # Remove any previous Inputs/Outputs block injected
            body = re.sub(r'\n[ \t]*Inputs:.*?(?=\n[ \t]*\"\"\")', '', body, flags=re.DOTALL)
            body = re.sub(r'\n[ \t]*Outputs:.*?(?=\n[ \t]*\"\"\")', '', body, flags=re.DOTALL)
            
            append_str = "\n" + generate_docstring_append(cls_info["schemas"])
            new_body = body.rstrip() + "\n" + append_str + "\n    "
            
            content = content[:match_doc.start()] + head + new_body + tail + content[match_doc.end():]
            modified = True
            
        else:
            # Pattern 2: Class has NO docstring.
            pattern_no_doc = re.compile(rf'(class\s+{cname}\b.*?:[ \t]*\n)')
            match_no = pattern_no_doc.search(content)
            if match_no:
                head = match_no.group(1)
                
                append_str = generate_docstring_append(cls_info["schemas"])
                new_docstring = f'    """\n{append_str}\n    """\n'
                
                content = content[:match_no.start()] + head + new_docstring + content[match_no.end():]
                modified = True
            
    if modified:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated docstrings in {os.path.basename(filepath)}")
        
print("All tool docstrings successfully updated.")
