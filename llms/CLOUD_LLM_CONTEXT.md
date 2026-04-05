# LLMs Directory: Real Runtime Flow

This file is a clean, pasteable summary of how the `llms/` service actually works.

If you are giving this project to another LLM, treat `llms/app/...` as the source of truth for the running service. The top-level scripts in `llms/` are mostly older standalone helpers, examples, or migration notes.

## 1. Source of truth

Real runtime path:

```text
llms/run.py
  -> llms/app/main.py
    -> llms/app/core/lifespan.py
      -> llms/app/services/inference_service.py
        -> llms/app/services/model_manager.py
        -> llms/app/services/path_manager.py
    -> llms/app/api/v1/llm/router.py
    -> llms/app/api/v1/llm/schemas.py
```

Not the main server flow:

```text
llms/qwen_inference.py      # older direct llama-cli flow
llms/model_manager.py       # older standalone model manager
llms/path_manager.py        # older standalone path manager
llms/test_model_manager.py  # test script for old standalone manager
llms/client_example.py      # example API client
llms/d.md                   # migration note, not runtime docs
```

## 2. Architecture style

The service uses this pattern:

- Thin entrypoint with `uvicorn`
- FastAPI app with startup/shutdown handled by `lifespan`
- Singleton service objects for path/model/inference management
- A persistent local `llama-server` process instead of spawning `llama-cli` per request
- Router layer for validation + HTTP response shaping
- Service layer for prompt formatting, binary/model setup, and llama.cpp calls
- `app.state.inference_service` as the runtime dependency container

In short: this is a FastAPI wrapper around a long-running local `llama-server`.

## 3. End-to-end request flow

```text
python run.py
  -> uvicorn starts app.main:app
  -> FastAPI lifespan startup runs
  -> InferenceService singleton is created
  -> ModelManager chooses device + model path
  -> model is downloaded if missing
  -> llama-server binary is found or downloaded
  -> llama-server process starts on 127.0.0.1:8080
  -> FastAPI stores InferenceService in app.state

Client POST /api/v1/llm/reasoning/chat
  -> router validates ChatRequest
  -> router gets app.state.inference_service
  -> router calls service.chat(...)
  -> service.chat() converts messages into a single prompt
  -> service.generate() POSTs to local llama-server /completion
  -> response text or streaming chunks are returned to the API caller
```

## 4. Server bootstrap

### `run.py`

This is the real server entrypoint:

```python
import uvicorn
from app.core.config import settings

def main():
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info"
    )

if __name__ == "__main__":
    main()
```

Important:

- Public FastAPI port defaults to `9001`
- Debug reload comes from `settings.debug`

## 5. FastAPI app setup

### `app/main.py`

The app is created once, CORS is opened wide, and the LLM router is mounted under `/api/v1/llm`.

```python
app = FastAPI(
    title="Reasoning LLM Microservice",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(llm_router, prefix="/api/v1/llm")
```

Health endpoint behavior:

```python
@app.get("/health")
async def health_check() -> HealthResponse:
    service = getattr(app.state, "inference_service", None)
    if service and service.is_ready:
        return HealthResponse(status="healthy", model_ready=True, device=service.device_type)
    return HealthResponse(status="unhealthy", model_ready=False, device=None)
```

## 6. Startup and shutdown flow

### `app/core/lifespan.py`

Startup is where the model/backend gets prepared.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    inference_service = get_inference_service()

    try:
        inference_service.setup(
            auto_download_binary=settings.auto_download_binary
        )

        if settings.warmup_on_startup:
            inference_service.warmup()

        app.state.inference_service = inference_service
    except Exception:
        app.state.inference_service = None

    yield

    if app.state.inference_service:
        app.state.inference_service.shutdown()
        app.state.inference_service = None
```

Key idea:

- FastAPI owns the service lifecycle
- The inference backend is prepared before requests are served
- Cleanup explicitly kills the background `llama-server`

## 7. API contract

### `app/api/v1/llm/schemas.py`

Request shape:

```python
class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]
    max_tokens: int = 512
    temperature: float = 0.1
    stream: bool = False
    json_mode: bool = False
```

Response shape:

```python
class ChatResponse(BaseModel):
    response: str
    model: str
    usage: Optional[Dict[str, Any]] = None
```

This means the public API is chat-style, not raw prompt-style.

## 8. Router behavior

### `app/api/v1/llm/router.py`

The route is:

```text
POST /api/v1/llm/reasoning/chat
```

Service lookup:

```python
def get_service(request: Request) -> InferenceService:
    service = request.app.state.inference_service
    if not service or not service.is_ready:
        raise HTTPException(
            status_code=503,
            detail="Inference service not ready. Model is still loading."
        )
    return service
```

Non-streaming path:

```python
response_text = service.chat(
    messages=messages,
    max_tokens=body.max_tokens,
    temperature=body.temperature,
    stream=False,
    json_mode=body.json_mode
)

return ChatResponse(
    response=response_text,
    model=settings.model_name,
    usage=None
)
```

Streaming path:

```python
sync_generator = service.chat(
    messages=messages,
    max_tokens=body.max_tokens,
    temperature=body.temperature,
    stream=True,
    json_mode=body.json_mode
)

async def event_generator():
    loop = asyncio.get_event_loop()

    def get_next_chunk():
        try:
            return next(sync_generator)
        except StopIteration:
            return None

    while True:
        chunk = await loop.run_in_executor(None, get_next_chunk)
        if chunk is None:
            break
        yield f"data: {json.dumps({'response': chunk, 'model': settings.model_name})}\\n\\n"

    yield "data: [DONE]\\n\\n"

return StreamingResponse(event_generator(), media_type="text/event-stream")
```

Router style:

- Validate with Pydantic
- Pull singleton service from `app.state`
- Return normal JSON or SSE depending on `stream`
- Keep llama.cpp details out of the HTTP layer

## 9. Inference service: the real backend logic

### `app/services/inference_service.py`

This is the most important file in the whole directory.

It does four jobs:

1. Resolve or download the right `llama-server` binary
2. Ask `ModelManager` for the correct model file
3. Start a persistent `llama-server` subprocess
4. Proxy chat/generation requests into the local backend over HTTP

### Singleton pattern

```python
_inference_service: Optional[InferenceService] = None
_singleton_lock = Lock()

def get_inference_service() -> InferenceService:
    global _inference_service
    if _inference_service is None:
        with _singleton_lock:
            if _inference_service is None:
                _inference_service = InferenceService()
    return _inference_service
```

### Setup flow

```python
def setup(self, auto_download_binary: bool = True) -> None:
    with self._lock:
        if self._is_ready:
            return

        self.model_path = self.model_manager.get_model_path(
            settings.model_name,
            auto_download=settings.auto_download_model
        )

        self.server_path = self._find_llama_binary()
        if not self.server_path and auto_download_binary:
            self.server_path = self._download_llama_binary()

        if not self.server_path:
            raise FileNotFoundError("llama-server not found.")

        self._start_server()
        self._is_ready = True
```

Meaning:

- Load model path first
- Find/download backend binary second
- Launch backend third
- Mark the service ready only after backend startup succeeds

### Starting the persistent backend

The service uses `llama-server`, not `llama-cli`.

```python
cmd = [
    str(self.server_path),
    "-m", str(self.model_path),
    "--host", self.SERVER_HOST,
    "--port", str(self.SERVER_PORT),
    "-c", "32768",
    "--n-gpu-layers", n_gpu_layers
]

self.server_process = subprocess.Popen(
    cmd,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
)
```

Backend defaults:

- Internal host: `127.0.0.1`
- Internal port: `8080`
- Context window: `32768`
- GPU layers: `"99"` for `gpu`/`vulkan`, otherwise `"0"`

Health wait loop:

```python
for i in range(max_retries):
    if self.server_process.poll() is not None:
        self.shutdown()
        raise RuntimeError("llama-server process died unexpectedly")

    try:
        response = requests.get("http://127.0.0.1:8080/health", timeout=1)
        if response.status_code == 200:
            return
        time.sleep(1)
    except requests.RequestException:
        time.sleep(1)
```

So the app does not assume readiness just because the subprocess exists. It waits for the backend health endpoint.

### Prompt-building style

The public API takes chat messages, but the backend call is prompt-based. The conversion happens here:

```python
def chat(self, messages, max_tokens=None, temperature=None, stream=False, json_mode=False):
    system_content = ""
    conversation = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "system":
            system_content = content
        elif role == "user":
            conversation.append(f"User: {content}")
        elif role == "assistant":
            conversation.append(f"Assistant: {content}")

    if system_content:
        prompt = f"{system_content}\\n\\n" + "\\n".join(conversation) + "\\nAssistant:"
    else:
        prompt = "\\n".join(conversation) + "\\nAssistant:"

    return self.generate(
        prompt,
        max_tokens,
        temperature,
        stream=stream,
        json_mode=json_mode
    )
```

Chat formatting style:

- `system` becomes a plain prepended instruction block
- `user` becomes `User: ...`
- `assistant` becomes `Assistant: ...`
- The final generation cue is always `Assistant:`

This is a simple manual chat template, not a tokenizer-native chat template.

### Generation flow

Actual inference is done by HTTP POST to the local `llama-server`:

```python
payload = {
    "prompt": full_prompt,
    "n_predict": token_limit,
    "temperature": temperature or settings.temperature,
    "stop": stop_sequences,
    "stream": stream,
    "repeat_penalty": 1.15,
    "frequency_penalty": 0.3,
    "presence_penalty": 0.3,
    "top_p": 0.9,
    "top_k": 40,
}

response = requests.post(
    "http://127.0.0.1:8080/completion",
    json=payload,
    stream=stream,
    timeout=timeout
)
```

Default stop sequence strategy:

```python
stop_sequences = [
    "</s>",
    "<|im_end|>",
    "<|endoftext|>",
    "<|eot_id|>",
    "\n\nUser:",
    "\n\nAssistant:",
    "\n\n\n",
]
```

Notable behavior:

- `max_tokens` is not artificially capped anymore
- timeout becomes `120` seconds when requested tokens are large
- response cleanup is intentionally light

### JSON mode

If `json_mode=True`, the service attaches a grammar:

```python
if json_mode:
    payload["grammar"] = self.JSON_GRAMMAR
```

Then it tries to cleanly extract a JSON object:

```python
def _extract_json(self, text: str) -> str:
    json_match = re.search(r"\{[\s\S]*\}", text)
    if json_match:
        try:
            json.loads(json_match.group())
            return json_match.group()
        except json.JSONDecodeError:
            pass
    return text
```

So JSON mode has two layers:

- llama.cpp grammar constraint during generation
- regex + JSON validation cleanup after generation

### Streaming style

For streaming, the service reads llama-server event lines and yields text chunks:

```python
for line in response.iter_lines():
    if line:
        decoded_line = line.decode("utf-8")
        if decoded_line.startswith("data: "):
            data = json.loads(decoded_line[6:])
            content = data.get("content", "")
            if content:
                yield content
```

Critical stop tokens terminate the stream:

```python
critical_stops = ["</s>", "<|eot_id|>", "<|im_end|>"]
```

### Shutdown style

```python
def shutdown(self):
    if self.server_process:
        if os.name == "nt":
            subprocess.call(["taskkill", "/F", "/T", "/PID", str(self.server_process.pid)])
        else:
            os.killpg(os.getpgid(self.server_process.pid), signal.SIGTERM)

        self.server_process = None
        self._is_ready = False
```

Important: the service cleans up the whole background process tree on Windows.

## 10. Model management

### `app/services/model_manager.py`

This file decides which model file should be used and downloads it if needed.

### Singleton pattern

```python
_model_manager: Optional[ModelManager] = None

def get_model_manager() -> ModelManager:
    global _model_manager
    if _model_manager is None:
        _model_manager = ModelManager()
    return _model_manager
```

### Config loading

The manager reads `llms/model_config.json` through `get_config_path()`.

```python
self.config_path = config_path or get_config_path()
self.config = self._load_config()
```

### Device detection style

Device selection is automatic:

```python
if self.config.get("settings", {}).get("force_cpu", False):
    return "cpu"

try:
    result = subprocess.run(["nvidia-smi"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3)
    if result.returncode == 0:
        return "gpu"
except (FileNotFoundError, subprocess.TimeoutExpired):
    pass

try:
    cmd = "wmic path win32_VideoController get name"
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True)
    output = result.stdout.lower()
    if "amd" in output or "radeon" in output or "intel" in output:
        return "vulkan"
except Exception:
    pass

return "cpu"
```

Selection priority:

1. `force_cpu`
2. NVIDIA -> `gpu`
3. AMD/Intel GPU -> `vulkan`
4. fallback -> `cpu`

### Model selection rule

The main selection method is:

```python
def get_model_path(self, model_name: str = "qwen2.5-7b", auto_download: bool = True) -> Path:
    if model_name not in self.config.get("models", {}):
        raise ValueError(...)

    if self.device_type == "cpu" and model_name == "qwen2.5-7b":
        model_name = "qwen2.5-1.5b"

    model_config = self.config["models"][model_name][self.device_type]
    model_path = self.models_dir / model_config["filename"]

    if model_path.exists():
        return model_path

    if not auto_download:
        raise FileNotFoundError(...)

    self._download_file(model_config["url"], model_path)
    return model_path
```

Important runtime behavior:

- If the requested model is `qwen2.5-7b` but the device is CPU, it silently falls back to `qwen2.5-1.5b`
- Quantized model filename depends on device type
- Downloads are automatic in non-interactive server mode

### Available models from `model_config.json`

Configured models include:

- `qwen2.5-coder-1.5b`
- `smollm2-1.7b`
- `llama-3.2-1b`
- `qwen2.5-7b`
- `mistral-7b`
- `qwen2.5-1.5b`

Each model has separate `cpu`, `gpu`, and `vulkan` entries with:

- download URL
- filename
- size
- quantization
- description

## 11. Path management

### `app/services/path_manager.py`

This file centralizes all important directories.

Core behavior:

```python
if getattr(sys, "frozen", False):
    self.BUNDLE_DIR = self._get_meipass()
    self.EXE_DIR = Path(sys.executable).parent
else:
    self.BUNDLE_DIR = Path(__file__).parent.parent.parent
    self.EXE_DIR = None
```

User data directories:

```python
self.USER_DATA_DIR = Path(
    self.env.get("JARVIS_DATA_DIR", self._default_user_data_dir())
)

self.MODELS_DIR = Path(
    self.env.get("JARVIS_MODELS_DIR", self.USER_DATA_DIR / "models")
)

self.BINARIES_DIR = self.USER_DATA_DIR / "binaries"
self.LOGS_DIR = self.USER_DATA_DIR / "logs"
```

Environment override style:

- `JARVIS_DATA_DIR`
- `JARVIS_MODELS_DIR`

OS default user data location:

- Windows -> `~/AppData/Local/SparkAI`
- macOS -> `~/Library/Application Support/SparkAI`
- Linux -> `~/.local/share/SparkAI`

So models and llama binaries live outside the repo by default, under user data directories.

## 12. Config behavior

### `app/core/config.py`

Settings are loaded with `pydantic-settings`.

Main defaults:

```python
host: str = "0.0.0.0"
port: int = 9001
debug: bool = False

model_name: str = "qwen2.5-7b"
max_tokens: int = 512
temperature: float = 0.1

auto_download_model: bool = True
auto_download_binary: bool = True
warmup_on_startup: bool = False
```

Important environment-controlled behavior:

- `HOST`
- `PORT`
- `DEBUG`
- `MODEL_NAME`
- `MAX_TOKENS`
- `TEMPERATURE`

There are also optional path overrides through settings fields:

- `data_dir`
- `models_dir`

But note: actual path resolution is mostly implemented through `PathManager` and `JARVIS_*` environment variables.

## 13. Binary management

The real runtime binary logic is inside `app/services/inference_service.py`, not in `model_config.json`.

The service has its own `LLAMA_CPP_RELEASES` mapping for:

- Windows CPU / GPU / Vulkan
- macOS CPU
- Linux CPU / GPU / Vulkan

Runtime binary behavior:

- look for `llama-server` in bundled and user-data locations
- if missing, download the platform/device-specific archive
- extract it
- search recursively for the executable
- delete the downloaded archive

This is why the production path works with `llama-server`, while some older files still mention `llama-cli`.

## 14. Legacy files and what they mean

### `qwen_inference.py`

This is an older standalone inference flow. It:

- uses `llama-cli`, not `llama-server`
- runs one subprocess per generation
- is not wired into FastAPI
- is useful as historical context, not current runtime behavior

### Top-level `model_manager.py` and `path_manager.py`

These are older standalone versions of the app services. They are not the main imports used by `run.py` -> `app/...`.

### `client_example.py`

This is a consumer script showing how to call the API, especially `json_mode=True` and streaming.

### `d.md`

This is a migration/refactor note describing the move from per-request `llama-cli` to persistent `llama-server`.

## 15. Real behavior summary for another LLM

If another model needs the shortest accurate summary, use this:

```text
This repo's llms service is a FastAPI wrapper around a local persistent llama.cpp backend.
The real runtime code lives under llms/app.
Startup creates a singleton InferenceService, which uses ModelManager and PathManager,
downloads the selected GGUF model if needed, finds/downloads llama-server, launches it
as a background process on 127.0.0.1:8080, and stores the service in app.state.

The public endpoint is POST /api/v1/llm/reasoning/chat.
The router validates chat messages, then calls InferenceService.chat().
That method converts messages into a manual prompt format:
system block + "User: ..." / "Assistant: ..." lines + trailing "Assistant:".
InferenceService.generate() sends the prompt to the local llama-server /completion API.
Responses are returned either as plain JSON or SSE stream chunks.

Model/device selection is automatic:
NVIDIA -> gpu, AMD/Intel -> vulkan, else cpu.
If cpu and requested model is qwen2.5-7b, it falls back to qwen2.5-1.5b.
PathManager stores models and binaries in user data directories by default.
json_mode adds a llama.cpp JSON grammar and then does JSON extraction/validation cleanup.
```

## 16. Important mismatches and caveats

These details are useful if another LLM is reasoning about the codebase:

- README says port `8000`, but `app/core/config.py` actually defaults to `9001`
- Real runtime uses `llama-server`; old helper code still references `llama-cli`
- `warmup_on_startup` exists, but `InferenceService.warmup()` is currently a no-op because server mode already keeps the model loaded
- `model_config.json` contains model definitions and old llama.cpp binary metadata, but real binary download logic for production is hardcoded in `InferenceService.LLAMA_CPP_RELEASES`
- The chat template is manual string formatting, not a tokenizer/model-native chat template

## 17. Best files to paste into a cloud LLM if context is limited

If you cannot paste everything, prioritize these in order:

1. `llms/app/services/inference_service.py`
2. `llms/app/services/model_manager.py`
3. `llms/app/api/v1/llm/router.py`
4. `llms/app/core/lifespan.py`
5. `llms/app/core/config.py`
6. `llms/app/services/path_manager.py`
7. `llms/model_config.json`

That set is enough to reconstruct most runtime behavior accurately.
