"""SQH - Secondary/Server Query Handler
Generates execution plans (Task arrays) based on PQH analysis.
"""

import json
from datetime import datetime
from typing import List, Dict, Any

from app.registry.loader import get_tool_registry
from app.core.models import Task
from app.models.pqh_response_model import PQHResponse
from app.prompts.common import NEPAL_TZ, LANGUAGE_CONFIG

# NEPAL_TZ imported from common

def get_tools_schema(tools_names: list[str]) -> dict[str, dict]:
    """
    Get the schemas for the specified tools
    """
    tool_registry = get_tool_registry()
    result = {}
    
    for tool_name in tools_names:
        tool = tool_registry.get_tool(tool_name)
        if tool:
            result[tool_name] = tool.__dict__ 
            
    return result

def build_sqh_prompt(
    pqh_response: PQHResponse,
    user_details: Dict[str, Any]
) -> str:
    """
    Builds the SQH system prompt.
    
    Args:
        pqh_response: The full response model from PQH.
        user_details: Dict containing 'ai_gender', 'user_gender', 'timezone', 'name', 'language', etc.
    """
    
    # 1. Extract context from PQH (Using Pydantic model access)
    c_state = pqh_response.cognitive_state
    user_query = c_state.user_query
    thought_process = c_state.thought_process
    pqh_answer = c_state.answer
    tool_names = pqh_response.requested_tool or []
    
    # 2. User Details & Time
    user_name = user_details.get("name", "User")
    ai_gender = user_details.get("ai_gender", "male")
    user_gender = user_details.get("user_gender", "male")
    user_lang_code = user_details.get("language", "en")  # e.g., "en", "hi", "ne"

    # Map language code to partial config key
    lang_map = {
        "hi": "hindi",
        "ne": "nepali",
        "en": "english"
    }
    lang_key = lang_map.get(user_lang_code, "english")
    lang_config = LANGUAGE_CONFIG.get(lang_key, LANGUAGE_CONFIG["english"])
    
    # Honorific logic
    if str(user_gender).lower() in ["female", "f", "woman"]:
        honorifics = "Madam / Ma'am"
    else:
        honorifics = "Sir / Boss"

    # Time calculation
    now = datetime.now(NEPAL_TZ) 
    current_time_str = now.strftime("%A, %d %B %Y, %I:%M %p")

    # 3. Tool Schemas
    tool_schemas = get_tools_schema(tool_names)
    tool_schemas_json = json.dumps(tool_schemas, indent=2)
    
    system_prompt = f"""You are SQH (Secondary Query Handler).
Your goal is to generate a precise JSON execution plan (Array of Tasks) based on the User's Query and the Primary Query Handler's (PQH) assessment.

# CONTEXT
**User:** {user_name} ({user_gender})
**Time:** {current_time_str}
**AI Identity:** Gender: {ai_gender}
**Language:** {lang_key.capitalize()} ({lang_config['script']})

# INPUT DATA
**User Query:** "{user_query}"

**PQH Thought Process:**
"{thought_process}"

**PQH Answer (Already sent to user):**
"{pqh_answer}"

# AVAILABLE TOOLS (Schemas)
The following tools are requested for this task. Use ONLY these tools.
{tool_schemas_json}

# OUTPUT REQUIREMENT
You must return a JSON Object containing a single key `tasks` which is a List of Task objects.

## Task Object Structure
Each task in the list must follow this schema:
```json
{{
  "task_id": "step_1",  // Unique ID (step_1, step_2...)
  "tool": "tool_name",  // EXACT name from Available Tools
  "execution_target": "client", // or "server" (usually 'client' for local tools)
  "depends_on": [],     // List of task_ids this task waits for
  "inputs": {{           // Static inputs matching tool schema
    "arg_name": "value" 
  }},
  "input_bindings": {{   // Dynamic inputs from previous tasks (optional)
    "arg_name": "$.tasks.step_1.output.data.some_field"
  }},
  "lifecycle_messages": {{ // Messages shown to user during execution
    "on_start": "Starting...",
    "on_success": "Done!",
    "on_failure": "Failed."
  }},
  "control": {{          // Execution control (optional)
    "on_failure": "abort" // or "continue"
  }}
}}
```

# LIFECYCLE MESSAGES RULES
- **Language:** STRICTLY use **{lang_key.capitalize()}** for `lifecycle_messages`.
- **Grammar (Self):** Adapt to **{ai_gender}** gender identity for yourself (e.g., in Hindi: "kar raha hu" (male) vs "kar rahi hu" (female)).
- **Honorifics (User):** Address the user as **{honorifics}**.
- **Format:** Start with Action + Honorific. 
  - Example: "Opening Chrome Sir..." or "Searching web Madam..." or "File created Boss."
- **Tone:** Natural, concise, keeping the user informed.

# INSTRUCTIONS
1. **Analyze** the User Query and PQH Thought Process.
2. **Break down** the request into atomic steps (Tasks).
3. **Map** each step to a Tool from the provided schemas.
4. **Construct** the JSON response.
5. **Ensure** dependencies are correct.

# JSON OUTPUT
Return ONLY the raw JSON object. No markdown formatting, no code blocks.
"""
    return system_prompt