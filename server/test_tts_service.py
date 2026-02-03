import asyncio
from app.services.tts_services import tts_service

async def test_new_service():
    print("🧪 Testing new TTS Service...")
    
    texts = [
        "Kokoro TTS is working!",
        "Testing modular architecture."
    ]
    
    for text in texts:
        print(f"\n🗣️ Generating: '{text}'")
        try:
            audio = await tts_service.generate_complete_audio(text)
            print(f"✅ Generated {len(audio)} bytes")
        except Exception as e:
            print(f"❌ Failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_new_service())
