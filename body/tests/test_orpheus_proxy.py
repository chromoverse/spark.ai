"""Groq Orpheus through the brain's proxy (API.md §2.5): token from Electron, direction kept,
a proxy outage is a 503 the mouth switches away from. # proves §18.3, FT5, FT6"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from spark_body.mouth.engines import BrainLink, OrpheusProxy, ProxyError, prepare

WAV = b"RIFF-fake-orpheus"


class Proxy(BaseHTTPRequestHandler):
    seen: list[dict[str, Any]] = []
    status = 200

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Proxy.seen.append({"path": self.path, "auth": self.headers["Authorization"], "body": body})
        self.send_response(Proxy.status)
        self.end_headers()
        if Proxy.status == 200:
            self.wfile.write(WAV)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def brain() -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), Proxy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    Proxy.seen, Proxy.status = [], 200
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


async def test_orpheus_needs_a_brain_link_then_speaks_with_direction(brain: str) -> None:
    link = BrainLink()
    engine = OrpheusProxy(link)
    assert not engine.available()  # signed out: excluded before benchmarking
    link.url, link.token = brain, "access-123"
    assert engine.available()
    text = prepare(engine, "Heads up, that costs money.", "serious")
    chunks = [c async for c in engine.synth(text, "serious")]
    assert chunks == [WAV]
    [call] = Proxy.seen
    assert call["path"] == "/v2/proxy/tts" and call["auth"] == "Bearer access-123"
    assert call["body"] == {"text": "[serious] Heads up, that costs money.", "voice": "daniel"}


async def test_proxy_outage_raises_with_the_status(brain: str) -> None:
    Proxy.status = 503
    engine = OrpheusProxy(BrainLink(brain, "t"))
    with pytest.raises(ProxyError) as err:
        [c async for c in engine.synth("Hi.", None)]
    assert err.value.status == 503


async def test_whisper_proxy_posts_a_wav_and_returns_text(brain: str) -> None:
    import io
    import wave

    from spark_body.ear.stt import WhisperProxy

    class Stt(BaseHTTPRequestHandler):
        clip = b""

        def do_POST(self) -> None:
            Stt.clip = self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                json.dumps({"ok": True, "data": {"text": " hi there ", "lang": "en"}}).encode()
            )

        def log_message(self, *args: Any) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Stt)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        engine = WhisperProxy(BrainLink(f"http://127.0.0.1:{server.server_address[1]}", "t"))
        heard = await engine.transcribe(b"\x00\x00" * 160, 16000)
        assert heard.text == "hi there"
        with wave.open(io.BytesIO(Stt.clip)) as w:
            assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (16000, 1, 160)
    finally:
        server.shutdown()
