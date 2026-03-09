# Codex Prompt — Voice Assistant Latency Optimization

## Project Overview

I am building a **real-time voice AI assistant** using:
- **Frontend**: Electron (React)
- **Backend**: FastAPI (Python)
- **STT**: Groq Whisper (free tier)
- **LLM**: Groq LLaMA 3.3 70B (free tier, streaming)
- **RAG**: LanceDB + (currently slow embedding — needs replacing)
- **TTS**: Using Groq TTS, we have others too as edge_tts, kokoro,
- **Transport**: WebSocket between Electron and FastAPI

---

## Current Broken Pipeline (What Exists Now)

```
User speaks → [wait for full silence] → send full audio blob
→ Groq STT (~800ms) 
→ RAG retrieval (~300-400ms, embedding is slow) 
→ Groq LLM Stream -> TTS
→ Play audio
Total felt latency: ~2.5 seconds
```

**Problems:**
1. Sending full audio blob instead of cutting on speech end = +500ms wasted
2. Embedding model is slow (likely API-based or heavy model) = +300ms wasted

---

## Target Architecture (What You Must Build)

```
User speaks
  ↓
[Electron] Silero VAD (@ricky0123/vad-web) — detects speech end at 150ms
  ↓ sends raw PCM Float32Array over WebSocket immediately
[FastAPI WebSocket]
  ↓
Groq Whisper STT — short clean clip now = ~250-300ms
  ↓
fastembed (BAAI/bge-small-en-v1.5) + LanceDB — ~30-50ms total
  ↓
Groq LLaMA 3.3 streaming — tokens stream out
  ↓ (every complete sentence, NOT full response)
groqtts/edge-tts streaming — audio chunks stream back over WebSocket
  ↓
[Electron] plays audio chunks in real-time as they arrive
Target felt latency: ~500-700ms
```

---

## Task 1 — Electron Frontend (React)

### 1a. Install and integrate Silero VAD

```bash
npm install @ricky0123/vad-web
```

Modify electron/src/renderer/components/local/device/AudioInput.tsx microphone/recording logic with this also lets not make it messy as groq mode. remove that we are now sending the audio chunks streams. :

```javascript
import { useMicVAD } from "@ricky0123/vad-web"

const vad = useMicVAD({
  startOnLoad: true,
  positiveSpeechThreshold: 0.6,
  negativeSpeechThreshold: 0.45,
  minSpeechFrames: 4,
  redemptionFrames: 8,

  onSpeechStart: () => {
    console.log("Speech started")
    // Optional: show UI indicator
  },

  onSpeechEnd: (audioFloat32Array) => {
    // audioFloat32Array is Float32Array at 16kHz sample rate
    // Convert to 16-bit PCM and send over WebSocket immediately
    sendAudioToBackend(audioFloat32Array)
  }
})
```

### 1b. Audio conversion and WebSocket send

```javascript
function float32ToPCM16(float32Array) {
  const pcm = new Int16Array(float32Array.length)
  for (let i = 0; i < float32Array.length; i++) {
    const clamped = Math.max(-1, Math.min(1, float32Array[i]))
    pcm[i] = clamped < 0 ? clamped * 32768 : clamped * 32767
  }
  return pcm.buffer
}

function sendAudioToBackend(audioFloat32Array) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    const pcmBuffer = float32ToPCM16(audioFloat32Array)
    ws.send(pcmBuffer)
  }
}
```

### 1c. WebSocket — receive and play audio chunks in real-time

```javascript
const audioContext = new AudioContext({ sampleRate: 24000 })
let audioQueue = []
let isPlaying = false

ws.onmessage = async (event) => {
  if (event.data instanceof ArrayBuffer) {
    // It's an audio chunk from TTS — queue and play
    audioQueue.push(event.data)
    if (!isPlaying) playNextChunk()
  } else {
    // It's a text event (transcript, LLM token, status)
    const msg = JSON.parse(event.data)
    handleTextEvent(msg)
  }
}

async function playNextChunk() {
  if (audioQueue.length === 0) { isPlaying = false; return }
  isPlaying = true
  const chunk = audioQueue.shift()
  const audioBuffer = await audioContext.decodeAudioData(chunk)
  const source = audioContext.createBufferSource()
  source.buffer = audioBuffer
  source.connect(audioContext.destination)
  source.onended = playNextChunk
  source.start()
}
```

---

## Task 2 — FastAPI Backend

```python
async def transcribe_audio(pcm_bytes: bytes, groq_client) -> str:
    # Convert raw PCM16 (16kHz mono) to WAV format for Groq
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wf:
        wf.setnchannels(1)       # mono
        wf.setsampwidth(2)       # 16-bit
        wf.setframerate(16000)   # 16kHz (VAD outputs this)
        wf.writeframes(pcm_bytes)
    wav_buffer.seek(0)
    wav_buffer.name = "audio.wav"  # Groq needs a filename hint

    transcription = groq_client.audio.transcriptions.create(
        file=wav_buffer,
        model="whisper-large-v3-turbo",  # fastest Groq whisper model
        language="en"
    )
    return transcription.text.strip()
```

### 2e. RAG — fast local embedding + LanceDB search

```python
async def retrieve_context(query: str, table, embedder) -> str:
    # Local embedding — no API call, ~15ms
    vector = list(embedder.embed([query]))[0].tolist()
    
    # LanceDB vector search ~10-30ms
    results = (
        table.search(vector)
             .limit(3)
             .select(["text"])   # only fetch text column
             .to_list()
    )
    
    context = "\n\n".join([r["text"] for r in results])
    return context
```

### 2f. LLM → TTS pipeline — sentence-level streaming (THE MOST IMPORTANT PART)

```python
async def llm_to_tts_stream(query: str, context: str, websocket: WebSocket, groq_client):
    SENTENCE_ENDINGS = {'.', '!', '?'}
    buffer = ""

    # Notify frontend that AI is starting to respond
    await websocket.send_text(json.dumps({"type": "ai_start"}))

    stream = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": "You are a helpful voice assistant. Keep responses concise and conversational. Respond in 2-3 sentences max unless asked for more detail."
            },
            {
                "role": "user",
                "content": f"Context from knowledge base:\n{context}\n\nUser question: {query}"
            }
        ],
        stream=True,
        max_tokens=250,      # keep short for voice = faster
        temperature=0.7
    )

    for chunk in stream:
        token = chunk.choices[0].delta.content
        if token is None:
            continue
        
        buffer += token
        
        # Send token to frontend for live text display
        await websocket.send_text(json.dumps({"type": "token", "text": token}))

        # also we gotta add this in the electron socket.types.ts
        
        # Check if we have a complete sentence (minimum 15 chars to avoid tiny fragments)
        if buffer[-1] in SENTENCE_ENDINGS and len(buffer.strip()) > 15:
            sentence = buffer.strip()
            buffer = ""
            # Fire TTS immediately — don't wait for rest of LLM response
            await synthesize_and_stream(sentence, websocket)

    # Flush any remaining buffer
    if buffer.strip():
        await synthesize_and_stream(buffer.strip(), websocket)

    await websocket.send_text(json.dumps({"type": "ai_end"}))
```

## Success Criteria

- Felt latency from end of speech to first audio from assistant: **under 700ms**
- No full audio blob waiting — VAD triggers send immediately at speech end
- LLM response appears as streaming tokens in the UI
- TTS speaks sentence 1 while LLM is still generating sentence 2
- All free, no paid APIs beyond Groq free tier