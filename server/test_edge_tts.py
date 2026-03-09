import asyncio
import time
from pathlib import Path
import logging

from app.services.tts.groq_engine import GroqEngine
from app.services.tts.edge_engine import EdgeEngine

logging.basicConfig(level=logging.INFO)

OUTPUT_DIR = Path(__file__).resolve().parent
TEXT = "Hello Sir. I am back again after a long time."

def save_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(data)

async def generate_groq(text: str, output_file: str = "speech1.mp3"):
    start = time.perf_counter()
    engine = GroqEngine()

    if not await engine.is_available():
        raise RuntimeError("GroqEngine is not available")

    chunks = []
    async for chunk in engine.generate_stream(
        text=text,
        voice="autumn",
        speed=1.0,
        lang="en",
    ):
        chunks.append(chunk)

    audio_data = b"".join(chunks)
    output_path = OUTPUT_DIR / output_file
    save_bytes(output_path, audio_data)

    elapsed = time.perf_counter() - start
    return {
        "engine": "groq",
        "file": str(output_path),
        "bytes": len(audio_data),
        "seconds": elapsed,
    }

async def generate_edge(text: str, output_file: str = "speech2.mp3"):
    start = time.perf_counter()
    engine = EdgeEngine()

    chunks = []
    async for chunk in engine.generate_stream(
        text=text,
        voice="en-US-AriaNeural",
        speed=1.0,
        lang="en-US",
    ):
        chunks.append(chunk)

    audio_data = b"".join(chunks)
    output_path = OUTPUT_DIR / output_file
    save_bytes(output_path, audio_data)

    elapsed = time.perf_counter() - start
    return {
        "engine": "edge",
        "file": str(output_path),
        "bytes": len(audio_data),
        "seconds": elapsed,
    }

async def main():
    total_start = time.perf_counter()

    groq_task = generate_groq(TEXT, "speech1.mp3")
    edge_task = generate_edge(TEXT, "speech2.mp3")

    results = await asyncio.gather(groq_task, edge_task, return_exceptions=True)

    total_elapsed = time.perf_counter() - total_start

    print("\n=== Results ===")
    for result in results:
        if isinstance(result, Exception):
            print(f"Failed: {result}")
        else:
            print(
                f"{result['engine']:>5} | "
                f"{result['seconds']:.2f}s | "
                f"{result['bytes']} bytes | "
                f"{result['file']}"
            )

    print(f"\nTotal wall time: {total_elapsed:.2f}s")

if __name__ == "__main__":
    asyncio.run(main())