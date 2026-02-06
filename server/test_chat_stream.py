import requests
import json
import sys

# Configuration
API_URL = "http://localhost:9001/api/v1/llm/reasoning/chat"

def get_streaming_response(prompt):
    """
    Example of how your Main Server can consume the stream.
    """
    print(f"\nUser: {prompt}")
    print("Assistant: ", end="", flush=True)

    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "stream": True  # Enable streaming
    }

    try:
        # 1. Make a POST request with stream=True
        with requests.post(API_URL, json=payload, stream=True) as response:
            response.raise_for_status()

            # 2. Iterate over the response lines
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    
                    # 3. Parse Server-Sent Events (SSE)
                    if decoded_line.startswith('data: '):
                        data_str = decoded_line[6:]  # Remove "data: " prefix
                        
                        # Handle [DONE] signal
                        if data_str.strip() == "[DONE]":
                            break
                        
                        try:
                            # 4. Parse JSON chunk
                            data = json.loads(data_str)
                            chunk_content = data.get("response", "")
                            
                            # 5. Process/Forward the chunk
                            # Here we just print it, but your server would yield this to its client
                            print(chunk_content, end="", flush=True)
                            
                        except json.JSONDecodeError:
                            continue
                            
        print("\n\n [Stream Complete]")

    except requests.exceptions.ConnectionError:
        print("\n❌ Could not connect to the microservice. Is it running on port 8000?")
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        prompt = sys.argv[1]
    else:
        prompt = "do you know i am creating you n dmaking a fully jarvis like ai ?"
    
    get_streaming_response(prompt)
