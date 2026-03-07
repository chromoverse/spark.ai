import asyncio
from pathlib import Path
import logging
from app.services.tts.groq_engine import GroqEngine

# Configure logging to see which engine is being used
logging.basicConfig(level=logging.INFO)

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "electron" / "src" / "renderer" / "pages" / "Onboarding" / "voices" / "assets"
VOICE_SAMPLES = [
    {
        "name": "Heart",
        "voice": "af_heart",
        "groq_voice": "autumn",
        "filename": "voice-af-heart.wav",
    },
    {
        "name": "Bella",
        "voice": "af_bella",
        "groq_voice": "diana",
        "filename": "voice-af-bella.wav",
    },
    {
        "name": "Nicole",
        "voice": "af_nicole",
        "groq_voice": "hannah",
        "filename": "voice-af-nicole.wav",
    },
    {
        "name": "Sarah",
        "voice": "af_sarah",
        "groq_voice": "autumn",
        "filename": "voice-af-sarah.wav",
    },
    {
        "name": "Michael",
        "voice": "am_michael",
        "groq_voice": "daniel",
        "filename": "voice-am-michael.wav",
    },
    {
        "name": "Fenrir",
        "voice": "am_fenrir",
        "groq_voice": "austin",
        "filename": "voice-am-fenrir.wav",
    },
    {
        "name": "Puck",
        "voice": "am_puck",
        "groq_voice": "troy",
        "filename": "voice-am-puck.wav",
    },
]


def build_sample_text(voice_name: str) -> str:
    return (
        f"[happy] Hey, I am {voice_name}. I am part of Spark Industries. "
        "Siddhant is my CEO. [laugh] I can sound warm, calm, and playful when the moment needs it. "
        "[thinking] Sometimes I pause, explain slowly, and help you focus on the next clear move. "
        "[sad] Sometimes I soften the tone, stay patient, and keep the conversation grounded. "
        "[whisper] When things get intense, I can speak more gently and keep the room steady. "
        "[laugh] I am here to guide, organize, and keep your work flowing with personality. "
        "If you are ready, Spark is ready too."
    )

async def test_generation():
    print("Generating onboarding voice previews with Groq TTS only...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    engine = GroqEngine()

    if not await engine.is_available():
        raise RuntimeError("No Groq API key available for TTS generation.")

    for case in VOICE_SAMPLES:
        target_path = OUTPUT_DIR / case["filename"]
        print(f"\nGenerating {case['voice']} with Groq voice {case['groq_voice']} -> {target_path}")
        try:
            chunks = []
            async for chunk in engine.generate_stream(
                text=build_sample_text(case["name"]),
                voice=case["groq_voice"],
                speed=1.0,
                lang="en",
            ):
                chunks.append(chunk)

            audio_data = b"".join(chunks)

            with target_path.open("wb") as f:
                f.write(audio_data)

            file_size = len(audio_data)
            print(f"Success. Saved to {target_path.name} ({file_size} bytes)")

            if file_size < 1000:
                print("Warning: File size seems too small for audio.")
        except Exception as e:
            print(f"Failed for {case['voice']}: {e}")

if __name__ == "__main__":
    asyncio.run(test_generation())
