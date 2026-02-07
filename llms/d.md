Refactor InferenceService to use Persistent llama-server
The current implementation of 
InferenceService
 uses llama-cli.exe via subprocess for every request. This causes the model to be reloaded from disk for every single generation, resulting in significant latency (10s+ per request). The proposed change is to use llama-server.exe, which loads the model once and keeps it in memory, providing an OpenAI-compatible HTTP API for fast inference.

User Review Required
IMPORTANT

This change introduces a background process (llama-server.exe) that listens on port 8080 (default). Please ensure this port is available or configure it via environment variables if needed.

Proposed Changes
App Services
[MODIFY] 
inference_service.py
Change 
_find_llama_binary
 to look for llama-server.exe instead of llama-cli.exe.
Update 
setup()
 to:
Start llama-server.exe as a persistent background process using subprocess.Popen.
Use standard arguments: -m <model_path> --port 8080 --host 127.0.0.1 -c 4096.
Implement a "wait for healthy" loop polling http://127.0.0.1:8080/health.
Update 
generate()
 and 
chat()
 to send HTTP requests to the local llama-server instance.
Add shutdown() method to terminate the server process.
App Core
[MODIFY] 
lifespan.py
call inference_service.shutdown() during application shutdown to clean up the background process.
Verification Plan
Manual Verification
Start the Server: Run the API server as usual.
powershell
python run.py
Verify Startup: Watch the logs to see "llama-server started" and "Model loaded".
Test Inference: Send a request to the API.
The first request might take a second.
Subsequent requests should be instant (<1s) for short prompts, as the model is already loaded.
Shutdown: Stop the server (Ctrl+C) and verify the llama-server.exe process is terminated.