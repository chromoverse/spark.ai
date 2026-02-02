import asyncio
import edge_tts

async def main():
    communicate = edge_tts.Communicate(
        text="Hello Siddhant, Edge TTS test",
        voice="en-US-AriaNeural"
    )
    await communicate.save("test.mp3")

asyncio.run(main())
