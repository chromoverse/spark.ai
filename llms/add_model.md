# Task: Add Gemma 4 E4B Support to the LLM Inference Service

## Context

This project is a FastAPI wrapper around a persistent `llama-server` (llama.cpp) backend.
Runtime source of truth is under `llms/app/`. The public API is `POST /api/v1/llm/reasoning/chat`.
Model/device detection is automatic: NVIDIA → `gpu`, AMD/Intel → `vulkan`, else → `cpu`.

---

## What You Need to Do

### 1. Add Gemma 4 E4B to `llms/model_config.json`

Add a new entry `"gemma-4-e4b"` under `"models"` with three device variants:

```json
"gemma-4-e4b": {
  "cpu": {
    "url": "https://huggingface.co/google/gemma-4-e4b-it-GGUF/resolve/main/gemma-4-e4b-it-Q4_K_M.gguf",
    "filename": "gemma-4-e4b-it-Q4_K_M.gguf",
    "size": "~4.5GB",
    "quantization": "Q4_K_M",
    "description": "Gemma 4 E4B - CPU optimized"
  },
  "vulkan": {
    "url": "https://huggingface.co/google/gemma-4-e4b-it-GGUF/resolve/main/gemma-4-e4b-it-Q5_K_M.gguf",
    "filename": "gemma-4-e4b-it-Q5_K_M.gguf",
    "size": "~5.9GB",
    "quantization": "Q5_K_M",
    "description": "Gemma 4 E4B - Vulkan/AMD GPU optimized"
  },
  "gpu": {
    "url": "https://huggingface.co/google/gemma-4-e4b-it-GGUF/resolve/main/gemma-4-e4b-it-Q8_0.gguf",
    "filename": "gemma-4-e4b-it-Q8_0.gguf",
    "size": "~6.5GB",
    "quantization": "Q8_0",
    "description": "Gemma 4 E4B - NVIDIA GPU optimized"
  }
}
```

> ⚠️ Before writing the URLs, check the actual available filenames at:
> https://huggingface.co/google/gemma-4-e4b-it-GGUF
> Update the `url` and `filename` fields to match exactly what is listed there.

---

### 2. Add CPU Fallback in `llms/app/services/model_manager.py`

Find the existing CPU fallback block (currently handles `qwen2.5-7b → qwen2.5-1.5b`).
Add a new fallback right after it:

```python
# If CPU and E4B requested, fall back to E2B
if self.device_type == "cpu" and model_name == "gemma-4-e4b":
    model_name = "gemma-4-e2b"
```

> Also add `"gemma-4-e2b"` to `model_config.json` following the same structure,
> using the E2B GGUF files from https://huggingface.co/google/gemma-4-e2b-it-GGUF

---

### 3. Add Gemma Chat Template in `llms/app/services/inference_service.py`

#### 3a. Add a helper method `_format_prompt()` to the `InferenceService` class:

```python
def _format_prompt(self, messages: list, model_name: str) -> str:
    """Route to the correct chat template based on the active model."""
    if "gemma" in model_name.lower():
        return self._gemma_template(messages)
    return self._legacy_template(messages)

def _gemma_template(self, messages: list) -> str:
    """Gemma 4 native chat template using special turn tokens."""
    prompt = ""
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            prompt += f"<start_of_turn>system\n{content}<end_of_turn>\n"
        elif role == "user":
            prompt += f"<start_of_turn>user\n{content}<end_of_turn>\n"
        elif role == "assistant":
            prompt += f"<start_of_turn>model\n{content}<end_of_turn>\n"
    prompt += "<start_of_turn>model\n"  # generation cue
    return prompt

def _legacy_template(self, messages: list) -> str:
    """Existing User:/Assistant: format for Qwen, Mistral, Llama, etc."""
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
        return f"{system_content}\n\n" + "\n".join(conversation) + "\nAssistant:"
    return "\n".join(conversation) + "\nAssistant:"
```

#### 3b. Update the existing `chat()` method to call `_format_prompt()`:

Replace the existing manual prompt-building block inside `chat()` with:

```python
prompt = self._format_prompt(messages, settings.model_name)
```

Remove the old inline `system_content / conversation` building logic from `chat()` —
it is now handled by `_legacy_template()`.

#### 3c. Add Gemma stop tokens to the `stop_sequences` list inside `generate()`:

```python
"<end_of_turn>",         # Gemma 4 turn end token
"<start_of_turn>user",   # Gemma 4 user turn start (prevents bleeding)
```

Add these alongside the existing stop tokens. Do not remove any existing ones.

---

### 4. Do NOT change anything else

- Do not touch the llama-server launch logic
- Do not touch the streaming or JSON mode logic
- Do not touch path management or binary download logic
- Do not change the public API schema

---

## How to Test After Changes

Set the environment variable and start the server:

```bash
MODEL_NAME=gemma-4-e4b python llms/run.py
```

Then send a test request:

```bash
curl -X POST http://localhost:9001/api/v1/llm/reasoning/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "What is 2 + 2? Think step by step."}
    ],
    "max_tokens": 256,
    "temperature": 0.1
  }'
```

Expected: a valid JSON response with a `"response"` field containing a reasoned answer.

---

## Summary of Files to Modify

| File | What to change |
|---|---|
| `llms/model_config.json` | Add `gemma-4-e4b` and `gemma-4-e2b` model entries |
| `llms/app/services/model_manager.py` | Add CPU fallback for `gemma-4-e4b → gemma-4-e2b` |
| `llms/app/services/inference_service.py` | Add `_format_prompt`, `_gemma_template`, `_legacy_template`; update `chat()`; add stop tokens |