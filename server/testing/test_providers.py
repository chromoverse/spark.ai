r"""
Test script for the AI provider system.

Tests:
  1. llm_chat  — non-streaming chat with provider fallback
  2. llm_stream — async streaming with provider fallback
  3. Provider status — key counts, availability, quota blocks

Usage (from server/ directory):
    .venv\Scripts\python.exe test_providers.py
"""
import asyncio
import time
import sys


async def test_chat() -> bool:
    """Test llm_chat — should return (response_text, provider_name)."""
    from app.ai.providers import llm_chat

    print("\n" + "=" * 60)
    print("TEST 1: llm_chat")
    print("=" * 60)

    try:
        start = time.perf_counter()
        response, provider = await llm_chat(
            messages=[{"role": "user", "content": "tell me a joke where i am your boss and you are my employee"}],
        )
        elapsed = time.perf_counter() - start

        print(f"  ✅ Provider : {provider}")
        print(f"  ✅ Response : {response[:100]}")
        print(f"  ⏱️  Latency  : {elapsed:.2f}s")
        return True

    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        return False


async def test_stream() -> bool:
    """Test llm_stream — should yield text chunks."""
    from app.ai.providers import llm_stream

    print("\n" + "=" * 60)
    print("TEST 2: llm_stream")
    print("=" * 60)

    try:
       while True : 
            start = time.perf_counter()
            chunks: list[str] = []
            prompt = input("Enter a prompt to test streaming (e.g. 'Write a story...'): ")
            print("  📡 Streaming: ", end="", flush=True)
            async for chunk in llm_stream(
                messages=[{"role": "user", "content": prompt}],
            ):
                chunks.append(chunk)
                print(chunk, end="", flush=True)

            elapsed = time.perf_counter() - start
            full_response = "".join(chunks)

            print()  # newline after stream
            # print(f"  ✅ Chunks    : {len(chunks)}")
            # print(f"  ✅ Total len : {len(full_response)} chars")
            # print(f"  ⏱️  Latency  : {elapsed:.2f}s")
            return True

    except Exception as e:
        print(f"\n  ❌ FAILED: {e}")
        return False


async def test_status() -> bool:
    """Test get_status — should show all providers and their key state."""
    from app.ai.providers import get_llm_manager

    print("\n" + "=" * 60)
    print("TEST 3: Provider Status")
    print("=" * 60)

    try:
        manager = get_llm_manager()
        status = manager.get_status()

        for name, info in status.items():
            avail = "✅" if info["available"] else "❌"
            blocked = "🚫 BLOCKED" if info["blocked"] else "🟢 OK"
            print(
                f"  {avail} {name:15s} | "
                f"keys: {info['total_keys']} total, {info['failed_keys']} failed | "
                f"{blocked}"
            )

        return True

    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        return False


async def main() -> None:
    # print("🧪 AI Provider Test Suite")
    # print(f"   Python: {sys.version.split()[0]}")

    # results: dict[str, bool] = {}

    # # Run status first (no API call)
    # results["status"] = await test_status()

    # # Run chat test
    # results["chat"] = await test_chat()

    # # Run stream test
    # results["stream"] = await test_stream()

    # # Summary
    # print("\n" + "=" * 60)
    # print("SUMMARY")
    # print("=" * 60)
    # for name, passed in results.items():
    #     icon = "✅ PASS" if passed else "❌ FAIL"
    #     print(f"  {icon} — {name}")

    # total = len(results)
    # passed = sum(results.values())
    # print(f"\n  {passed}/{total} tests passed")

    # if passed < total:
    #     sys.exit(1)

    await test_stream()


if __name__ == "__main__":
    asyncio.run(main())
