"""
Interactive streaming test client for the local LLM service.

Usage:
    python test_stream.py                          # interactive REPL
    python test_stream.py "What is 2 + 2?"         # single query then REPL
    python test_stream.py --once "one-shot query"   # single query then exit
"""

import argparse
import json
import sys
import time
from typing import Optional

import requests

API_URL = "http://localhost:9001/api/v1/llm/reasoning/chat"


def stream_query(
    prompt: str,
    system_prompt: Optional[str] = None,
    max_tokens: int = 256,
    temperature: float = 0.1,
    json_mode: bool = False,
) -> str:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
        "json_mode": json_mode,
    }

    full_response = ""
    token_count = 0
    t_start = time.perf_counter()
    t_first_token = None

    try:
        with requests.post(API_URL, json=payload, stream=True, timeout=300) as response:
            response.raise_for_status()

            print("Assistant: ", end="", flush=True)

            for line in response.iter_lines():
                if not line:
                    continue

                decoded_line = line.decode("utf-8")
                if not decoded_line.startswith("data: "):
                    continue

                data_str = decoded_line[6:]
                if data_str.strip() == "[DONE]":
                    break

                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                chunk = data.get("response", "")
                if not chunk:
                    continue

                if t_first_token is None:
                    t_first_token = time.perf_counter()

                full_response += chunk
                token_count += 1
                print(chunk, end="", flush=True)

    except requests.exceptions.ConnectionError:
        print("\nCould not connect. Is the server running?")
        return ""
    except requests.HTTPError as exc:
        print(f"\nHTTP error: {exc}")
        return ""
    except requests.RequestException as exc:
        print(f"\nRequest failed: {exc}")
        return ""

    t_end = time.perf_counter()
    total_s = t_end - t_start
    first_token_ms = (t_first_token - t_start) * 1000 if t_first_token else 0
    gen_s = t_end - t_first_token if t_first_token else total_s
    tok_per_s = token_count / gen_s if gen_s > 0 else 0

    print(f"\n\n--- {token_count} chunks | "
          f"first token: {first_token_ms:.0f}ms | "
          f"gen: {gen_s:.1f}s | "
          f"{tok_per_s:.1f} tok/s | "
          f"total: {total_s:.1f}s ---")

    return full_response


def repl(
    system_prompt: Optional[str] = None,
    max_tokens: int = 256,
    temperature: float = 0.1,
    json_mode: bool = False,
):
    """Interactive loop — type prompts, get streamed answers, repeat."""
    print("=" * 60)
    print("  SparkAI Local LLM — Interactive Test")
    print(f"  API: {API_URL}")
    print("  Type 'quit' or Ctrl+C to exit")
    print("=" * 60)

    while True:
        try:
            prompt = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not prompt:
            continue
        if prompt.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break

        stream_query(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=json_mode,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive streaming test for local LLM.")
    parser.add_argument("prompt", nargs="*", help="Initial prompt (enters REPL after)")
    parser.add_argument("--system", dest="system_prompt", help="System prompt")
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parser.add_argument("--once", action="store_true", help="Single query, no REPL")
    args = parser.parse_args()

    initial_prompt = " ".join(args.prompt).strip()

    if initial_prompt:
        stream_query(
            prompt=initial_prompt,
            system_prompt=args.system_prompt,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            json_mode=args.json_mode,
        )
        if args.once:
            return 0

    repl(
        system_prompt=args.system_prompt,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        json_mode=args.json_mode,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
