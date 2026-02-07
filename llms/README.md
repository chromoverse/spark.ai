# Reasoning LLM Microservice

A high-performance, self-contained microservice for hosting reasoning LLMs (like Qwen 2.5 and Llama 3.2).

**Key Features:**
*   **🚀 Auto-Optimized**: Automatically detects NVIDIA (CUDA), AMD/Intel (Vulkan), or CPU and downloads the correct backend.
*   **🛠️ Zero Native Dependencies**: We use standalone `llama.cpp` binaries. No need for `ctransformers`, `llama-cpp-python`, or complex C++ compilation.
*   **🧠 Logic Fallback**: Automatically switches to lighter models (1.5B) on CPU for speed, or uses full 7B/3B models on GPU.
*   **⚡ Streaming API**: Single endpoint for both streaming (SSE) and full-text responses.
*   **🔌 Drop-in Ready**: Persistent `llama-server` process eliminates model loading latency.

## Prerequisites

*   **OS**: Windows, Linux, or macOS.
*   **Python**: 3.10 or higher.
*   **Hardware**:
    *   **GPU (Recommended)**: NVIDIA (4GB+ VRAM) or AMD/Intel (Vulkan support).
    *   **CPU**: AVX2 support (fallback mode available).

## Installation

1.  **Clone the repository**:
    ```bash
    git clone <repo-url>
    cd <repo-name>
    ```

2.  **Create a virtual environment**:
    ```bash
    python -m venv venv
    .\venv\Scripts\activate   # Windows
    # source venv/bin/activate # Linux/Mac
    ```

3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

## Usage

Simply run the start script. The service will handle everything else (downloading binaries, models, etc.).

```bash
python run.py
```

*   **Port**: `8000` (API), `8080` (Internal Backend - Ignore)
*   **First Run**: It will download the necessary `llama.cpp` binary and the default model. This may take a few minutes.

## Configuration

You can configure the service via specific environment variables or by editing `app/core/config.py`.

### Models (`model_config.json`)
The system comes pre-configured with:
1.  **Qwen 2.5 1.5B** (Default): Ultra-fast, great for CPU/older GPUs.
2.  **Qwen 2.5 7B**: Stronger reasoning, requires ~6GB+ VRAM for good speed.
3.  **Llama 3.2 3B**: 128k context window, balanced performance.

To switch models, set the `MODEL_NAME` env var or edit `app/core/config.py`:
```python
model_name: str = "llama-3.2-3b"
```

## API Reference

**Endpoint**: `POST /api/v1/llm/reasoning/chat`

### 1. Standard Request (JSON)
```bash
curl -X POST "http://localhost:8000/api/v1/llm/reasoning/chat" \
     -H "Content-Type: application/json" \
     -d '{
           "messages": [{"role": "user", "content": "Hello!"}],
           "stream": false
         }'
```

### 2. Streaming Request (SSE)
```bash
curl -N -X POST "http://localhost:8000/api/v1/llm/reasoning/chat" \
     -H "Content-Type: application/json" \
     -d '{
           "messages": [{"role": "user", "content": "Count to 5."}],
           "stream": true
         }'
```

### 3. Python Client Example
Use the included `client_example.py` for a robust implementation effectively demonstrating how to consume the streaming API in your Python applications.

```python
import requests
import json

response = requests.post(
    "http://localhost:8000/api/v1/llm/reasoning/chat",
    json={"messages": [{"role": "user", "content": "Hello"}], "stream": True},
    stream=True
)

for line in response.iter_lines():
    if line:
        decoded_line = line.decode('utf-8')
        if decoded_line.startswith('data: '):
            print(json.loads(decoded_line[6:]))
```

## How It Works

1.  **Initialization**: `ModelManager` checks `nvidia-smi` and `wmic`.
    *   If **NVIDIA**: Downloads CUDA binary + GPU model.
    *   If **AMD/Intel**: Downloads Vulkan binary + compatible model.
    *   If **CPU**: Downloads AVX2 binary + Lightweight model (1.5B).
2.  **Server**: Starts a background `llama-server` process.
3.  **Inference**: The FastAPI wrapper forwards requests to the background server, managing queuing and formatting.
