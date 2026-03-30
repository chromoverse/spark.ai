import requests
import websocket
import pyaudio
import json
import threading
import time

API_KEY = "7b5043ca-e958-48c8-873d-5749873f97e7"  # Paste your key here or load it from env

# Audio config — must match what we tell Gladia
SAMPLE_RATE   = 16000
CHANNELS      = 1
CHUNK_SIZE    = 1024   # frames per chunk (~64ms per chunk)
FORMAT        = pyaudio.paInt16

# ─── Step 1: Init a live session → get WebSocket URL ───────────────────────
print("🔌 Initializing Gladia live session...")
t0 = time.time()

resp = requests.post(
    "https://api.gladia.io/v2/live",
    headers={"x-gladia-key": API_KEY, "Content-Type": "application/json"},
    json={
        "encoding":    "wav/pcm",
        "sample_rate": SAMPLE_RATE,
        "bit_depth":   16,
        "channels":    CHANNELS,
        "model":       "solaria-1",   # latest fast model
    }
)

if resp.status_code != 201:
    print(f"❌ Session init failed: {resp.status_code} - {resp.text}")
    exit()

ws_url     = resp.json()["url"]
session_id = resp.json()["id"]
print(f"✅ Session: {session_id}")
print(f"⏱️  Session init: {(time.time() - t0)*1000:.0f}ms")
print(f"\n🎙️  Speak into your mic... (Press Ctrl+C to stop)\n")

# ─── Step 2: Open WebSocket ─────────────────────────────────────────────────
t_first_transcript = None

def on_message(ws, message):
    global t_first_transcript
    data = json.loads(message)
    msg_type = data.get("type")

    if msg_type == "transcript":
        utterance = data["data"]["utterance"]
        text      = utterance.get("text", "").strip()
        is_final  = data["data"].get("is_final", False)

        if not text:
            return

        now = time.time()
        if t_first_transcript is None:
            t_first_transcript = now

        tag = "✅ FINAL  " if is_final else "💬 partial"
        print(f"  {tag} → {text}")

    elif msg_type == "error":
        print(f"❌ Error from Gladia: {data}")

def on_error(ws, error):
    print(f"❌ WebSocket error: {error}")

def on_close(ws, code, msg):
    print(f"\n🔒 WebSocket closed (code={code})")

def on_open(ws):
    print("🟢 WebSocket connected — streaming mic audio...\n")

    def stream_mic():
        pa     = pyaudio.PyAudio()
        stream = pa.open(
            rate=SAMPLE_RATE,
            channels=CHANNELS,
            format=FORMAT,
            input=True,
            frames_per_buffer=CHUNK_SIZE
        )
        try:
            t_stream_start = time.time()
            while True:
                chunk = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                ws.send(chunk, websocket.ABNF.OPCODE_BINARY)  # send raw PCM bytes directly
                
        except (KeyboardInterrupt, websocket.WebSocketConnectionClosedException):
            pass
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()
            # Gracefully tell Gladia we're done
            try:
                ws.send(json.dumps({"type": "stop_recording"}))
            except:
                pass
            print("\n⏹️  Stopped recording.")

    threading.Thread(target=stream_mic, daemon=True).start()

ws_app = websocket.WebSocketApp(
    ws_url,
    on_open=on_open,
    on_message=on_message,
    on_error=on_error,
    on_close=on_close
)

try:
    ws_app.run_forever()
except KeyboardInterrupt:
    print("\n👋 Exiting.")