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
            "text": "[happy] YouTube's opening — looking for something specific or just random stuff? [chuckle]",
            "lang": "en"
        },
        {
            "filename": "test_output_en2.wav",
            "text": "[thinking] bored... hmm. wanna break something or build something? [chuckle] both options available.",
            "lang": "en"
        },
        {
            "filename": "test_output_hi1.wav",
            "text": "[thinking] बोर... हम्म। कुछ तोड़ना है या बनाना है? [chuckle] दोनों ऑप्शन अवेलेबल हैं।",
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
