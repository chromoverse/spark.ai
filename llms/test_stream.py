"""
Simple streaming test client for the local LLM service.

Usage:
    python test_stream.py "What is 2 + 2?"
    python test_stream.py --system "You are helpful." "Explain recursion simply."
"""

import argparse
import json
import sys
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
    """Send a prompt to the local LLM service and print streamed chunks."""
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

    print("=" * 60)
    print(f"API: {API_URL}")
    print(f"User: {prompt}")
    print("Assistant: ", end="", flush=True)

    full_response = ""

    try:
        with requests.post(API_URL, json=payload, stream=True, timeout=300) as response:
            response.raise_for_status()

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

                full_response += chunk
                print(chunk, end="", flush=True)

    except requests.exceptions.ConnectionError:
        print("\n\nCould not connect to the LLM service.")
        print("Start it first with: python run.py")
        return ""
    except requests.HTTPError as exc:
        print(f"\n\nHTTP error: {exc}")
        if exc.response is not None:
            try:
                print(exc.response.json())
            except ValueError:
                print(exc.response.text)
        return ""
    except requests.RequestException as exc:
        print(f"\n\nRequest failed: {exc}")
        return ""

    print("\n" + "=" * 60)
    return full_response


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the streaming test."""
    parser = argparse.ArgumentParser(description="Stream a response from the local LLM service.")
    parser.add_argument("prompt", nargs="*", help="User prompt to send to the LLM")
    parser.add_argument("--system", dest="system_prompt", help="Optional system prompt")
    parser.add_argument("--max-tokens", type=int, default=256, help="Maximum tokens to generate")
    parser.add_argument("--temperature", type=float, default=0.1, help="Sampling temperature")
    parser.add_argument("--json", dest="json_mode", action="store_true", help="Enable JSON mode")
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint."""
    args = parse_args()
    prompt = " ".join(args.prompt).strip()

    if not prompt:
        try:
            prompt = input("Enter your prompt: ").strip()
        except EOFError:
            prompt = ""

    if not prompt:
        print("No prompt provided.")
        return 1

    result = stream_query(
        prompt=prompt,
        system_prompt=args.system_prompt,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        json_mode=args.json_mode,
    )
    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
