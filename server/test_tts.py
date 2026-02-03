import asyncio
import os
from app.services.tts_services import tts_service
import logging

# Configure logging to see which engine is being used
logging.basicConfig(level=logging.INFO)

async def test_generation():
    print("🚀 Starting TTS Generation Test...")
    
    test_cases = [
        {
            "filename": "test_output_en1.wav",
            "text": "Hello! I am verifying that the new modular TTS system is working correctly.",
            "lang": "en"
        },
        {
            "filename": "test_output_hi1.wav",
            "text": "नमस्ते! मैं देख रहा हूँ कि नया टीटीएस सिस्टम ठीक से काम कर रहा है या नहीं।",
            "lang": "hi"
        }
    ]
    
    for case in test_cases:
        print(f"\n🗣️ Generating: '{case['text']}'")
        try:
            # Generate audio
            audio_data = await tts_service.generate_complete_audio(
                text=case["text"],
                lang=case["lang"]
            )
            
            # Save to file
            with open(case["filename"], "wb") as f:
                f.write(audio_data)
                
            file_size = len(audio_data)
            print(f"✅ Success! Saved to {case['filename']} ({file_size} bytes)")
            
            if file_size < 1000:
                print("⚠️ Warning: File size seems too small for audio.")
                
        except Exception as e:
            print(f"❌ Failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_generation())
