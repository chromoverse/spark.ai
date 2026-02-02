# import warnings
# warnings.filterwarnings("ignore")

# import torch
import soundfile as sf
# from kokoro import KPipeline

# pipeline = KPipeline(
#     repo_id="hexgrad/Kokoro-82M",
#     lang_code="h",        # 🔥 Hindi
# )

# text = """
# नमस्ते सर।
# मैं आपका आर्टिफ़िशियल इंटेलिजेंस सहायक हूँ।
# मैं आपकी कैसे सहायता कर सकता हूँ?
# """

# audio_chunks = []

# with torch.inference_mode():
#     for _, _, audio in pipeline(text, voice="af_heart"):
#         audio_chunks.append(audio)

# import numpy as np
# final_audio = np.concatenate(audio_chunks)

# sf.write("hindi_output.wav", final_audio, 24000)

# print("✅ Hindi TTS generated")

async def main():
    from app.services.tts_services import tts_service
        # Simple English TTS
    audio = await tts_service.generate_complete_audio(
        text="Hello! This is a test of the text to speech system.",
        lang="en"
    )
    print(f"✓ Generated {len(audio):,} bytes of audio")
    sf.write("english_output.wav", audio, 24000)
    
    # Auto-detect language
    audio_hindi = await tts_service.generate_complete_audio(
        text="नमस्ते, यह एक परीक्षण है।"
        # lang will be auto-detected as Hindi
    )
    print(f"✓ Generated {len(audio_hindi):,} bytes of Hindi audio")
    sf.write("hindi_output.wav", audio_hindi, 24000)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())    