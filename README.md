x: 
llm_stream
 Returns 0 Chunks and 
llm_chat
 Fallback Fails in stream_service
Root Cause Analysis
From the logs, here's what happens on every voice query:

llm_stream
 via Groq completes with 0 chunks (no error thrown)
llm_chat
 fallback is triggered (because produced == 0)
Groq's 
llm_chat
 returns empty content → "Groq returned empty content"
Gemini fails (model name format error — separate issue)
OpenRouter has no keys → all providers exhausted → hardcoded fallback
Why the stream returns 0 chunks
_model_kwargs()
 at 
stream_service.py:122-133
 injects model="openai/gpt-oss-20b" when groq_mode is on. This model (GROQ_REASONING_MODEL) is a reasoning model that likely:

Returns content via reasoning_content instead of delta.content during streaming
Returns empty/no content for simple short queries
The Groq streaming code in groq_client.py:112 does check delta.content or getattr(delta, "reasoning_content", None), but the model may simply not stream any content chunks for short queries — it completes without error but yields nothing.

Why the 
llm_chat
 fallback also fails
The fallback at 
stream_service.py:265
 calls 
llm_chat(**kwargs)
 — reusing the same 
kwargs
 from 
_model_kwargs()
, which includes model="openai/gpt-oss-20b". This model returns empty content for simple queries even in non-streaming chat mode.

Meanwhile, the other successful 
llm_chat
 calls in the logs (intent detection, SQH) work fine because they don't pass a model parameter — so Groq uses its default model (meta-llama/llama-4-scout-17b-16e-instruct), which works.

Proposed Changes
Stream Service
[MODIFY] 
stream_service.py
Change 1: Remove the 
model
 override from 
_model_kwargs()
 so both 
llm_stream
 and 
llm_chat
 use the provider's default model (which works):

diff
def _model_kwargs(messages: List[Dict[str, str]]) -> Dict[str, Any]:
     """Build LLM call kwargs — injects model name only when groq_mode is on."""
     kwargs: Dict[str, Any] = dict(
         messages=messages,
         temperature=_LLM_TEMPERATURE,
         max_tokens=_LLM_MAX_TOKENS,
     )
-    if settings.groq_mode:
-        model = str(getattr(settings, "GROQ_REASONING_MODEL", "")).strip()
-        if model:
-            kwargs["model"] = model
     return kwargs
IMPORTANT

This removes the GROQ_REASONING_MODEL override from the stream pipeline entirely, falling back to the default model (meta-llama/llama-4-scout-17b-16e-instruct). If there was a specific reason to use the reasoning model for streaming, we should discuss an alternative approach (e.g., only using it for the stream but not the fallback chat).

Change 2: Add a warning log when stream produces 0 chunks without an exception (currently it silently falls through):

diff
# ── Stream produced nothing → try llm_chat as fallback ───────────────
         if produced == 0:
-            if stream_exc:
-                logger.warning("[%s] stream produced nothing — falling back to llm_chat", request_id)
+            logger.warning(
+                "[%s] stream produced 0 chunks (exc=%s) — falling back to llm_chat",
+                request_id, stream_exc,
+            )
Verification Plan
Automated Tests
The existing test at 
server/testing/test_stream_service_latency.py
 patches internal helpers (_iter_stream_with_fast_model, _chat_with_fast_model) that no longer exist in the current code, so it will need updating separately. For now, the verification is:

Restart the server and test a voice query like "Hello" or "open camera"
Check logs for:
✅ Groq stream done (N chunks) where N > 0
No "Groq returned empty content" errors
No "llm_chat fallback also failed" errors
Manual Verification
Ask the user to:

Restart the server after the change
Send a few voice queries ("Hello", "open camera", etc.)
Confirm the response is spoken (not the hardcoded fallback "Got it, sir!")
Share the relevant log lines to verify the stream produced chunks
