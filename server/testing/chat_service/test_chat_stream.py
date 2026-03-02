"""
Client Example for LLM Reasoning Microservice
----------------------------------------------
Demonstrates how to get clean JSON responses from the API.

Key settings for JSON output:
- json_mode: True (enforces valid JSON via grammar)
- temperature: 0.1 (low for deterministic output)
- Use qwen2.5-coder-1.5b model (best for structured output)
"""

import requests
import json
import sys

from app.registry.tool_index import get_tools_index

# Configuration - Update port to match your server (default: 9001)
API_URL = "http://localhost:9001/api/v1/llm/reasoning/chat"


def get_json_response(prompt: str, system_prompt: str | None = None):
    """
    Get a clean JSON response from the LLM.
    Uses json_mode=True for guaranteed valid JSON output.
    """
    print(f"\n📝 User: {prompt}")
    print("-" * 50)

    messages = []
    
    # Add system prompt if provided
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    
    messages.append({"role": "user", "content": prompt})

    payload = {
        "messages": messages,
        "max_tokens": 512,
        "temperature": 0.1,      # Low temp for deterministic JSON
        "json_mode": True,       # Enforce valid JSON output
        "stream": False          # Non-streaming for clean JSON
    }

    try:
        response = requests.post(API_URL, json=payload)
        response.raise_for_status()
        
        result = response.json()
        json_response = result.get("response", "")
        
        # Pretty print the JSON
        try:
            parsed = json.loads(json_response)
            print("✅ Valid JSON Response:")
            print(json.dumps(parsed, indent=2, ensure_ascii=False))
            return parsed
        except json.JSONDecodeError:
            print("⚠️ Response (not valid JSON):")
            print(json_response)
            return json_response

    except requests.exceptions.ConnectionError:
        print(f"\n❌ Could not connect to {API_URL}")
        print("   Is the server running? Start with: python run.py")
    except Exception as e:
        print(f"\n❌ Error: {e}")
    
    return None


def get_streaming_response(prompt: str, system_prompt: str | None = None):
    """
    Get a streaming response from the LLM.
    Note: Streaming with json_mode may produce partial JSON chunks.
    """
    print(f"\n📝 User: {prompt}")
    print("🤖 Assistant: ", end="", flush=True)

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "messages": messages,
        "max_tokens": 512,
        "temperature": 0.1,
        "json_mode": False,
        "stream": True
    }

    try:
        with requests.post(API_URL, json=payload, stream=True) as response:
            response.raise_for_status()

            full_response = ""
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    
                    if decoded_line.startswith('data: '):
                        data_str = decoded_line[6:]
                        
                        if data_str.strip() == "[DONE]":
                            break
                        
                        try:
                            data = json.loads(data_str)
                            chunk = data.get("response", "")
                            full_response += chunk
                            print(chunk, end="", flush=True)
                        except json.JSONDecodeError:
                            continue
                            
            print("\n" + "-" * 50)
            
            # Try to parse the full response as JSON
            try:
                parsed = json.loads(full_response)
                print("✅ Valid JSON received")
                return parsed
            except json.JSONDecodeError:
                print("⚠️ Response was not valid JSON")
                return full_response

    except requests.exceptions.ConnectionError:
        print(f"\n❌ Could not connect to {API_URL}")
    except Exception as e:
        print(f"\n❌ Error: {e}")
    
    return None


def test_spark_prompt():
    """
    Test with your SPARK system prompt for JSON output.
    """
    system_prompt = """You are SPARK - Siddhant's Personal AI. Respond ONLY with valid JSON.

    OUTPUT FORMAT:
    ```json
    {
    "cognitive_state": {
        "user_query": "exact input echo",
        "emotion": "neutral",
        "thought_process": "brief reasoning",
        "answer": "Pure English response",
        "answer_english": "English translation"
    },
    "requested_tool": ["tool_name"] OR []
    }
    ```

    RULES:
    - Output ONLY the JSON object, nothing else
    - No markdown code blocks
    - No explanations before or after
    - Pure JSON only"""

    user_query = "hey there"
    
    print("\n" + "=" * 60)
    print("🧪 Testing SPARK JSON Response")
    print("=" * 60)
    
    result = get_json_response(user_query, system_prompt)
    return result


def test_simple_json():
    """
    Test simple JSON generation without complex system prompt.
    """
    system_prompt = "You are a helpful assistant. Always respond with valid JSON only."
    user_query = "What is 2+2? Respond with JSON: {\"answer\": <number>, \"explanation\": \"<text>\"}"
    
    print("\n" + "=" * 60)
    print("🧪 Testing Simple JSON Response")
    print("=" * 60)
    
    result = get_json_response(user_query, system_prompt)
    return result

async def get_prompt():
    from app.prompts import stream_prompt, pqh_prompt
    from app.cache import cache_manager
    user_id = "695e2bbaf8efc966aaf9f218"
    prompt = input("Enter a query to test prompt building: ")
    recent_context = await cache_manager.get_last_n_messages(user_id, 10)
    query_based_context, _ = await cache_manager.process_query_and_get_context(user_id, prompt)
    tools_index = get_tools_index()
    print("tools index",tools_index)
    # prompt =  pqh_prompt.build_prompt_en(prompt, tools_index)
    prompt =  stream_prompt.build_prompt_en("neutral", prompt, recent_context,query_based_context, user_details=None)
    return prompt

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 LLM Reasoning Microservice - JSON Mode Client")
    print("=" * 60)
    print(f"📡 API URL: {API_URL}")
    print("\nRecommended model: qwen2.5-coder-1.5b (best for JSON)")
    print("Set in app/core/config.py or MODEL_NAME env var")
    
    if len(sys.argv) > 1:
        # Custom prompt from command line
        prompt = sys.argv[1]
        get_json_response(prompt, "Respond only with valid JSON.")
    else:
        while True:
            import asyncio
            prompt = asyncio.run(get_prompt())
            get_streaming_response(prompt, "respond plain")
            # get_json_response(prompt, "Respond only with valid JSON.")
           
