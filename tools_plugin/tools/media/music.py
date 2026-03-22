"""
Music playback tools — direct audio playback, no browser required.

Playback engine  (tried in order until one succeeds)
----------------------------------------------------
  Tier 1 – CLI stream   : mpv --no-video  (best: supports yt-dlp natively)
  Tier 2 – CLI stream   : vlc  --intf dummy --no-video
  Tier 3 – CLI stream   : ffplay  (ships with ffmpeg, common on Windows)
  Tier 4 – yt-dlp fetch : extract direct audio URL → feed to any available player
  Tier 5 – yt-dlp dl    : download best-audio to %TEMP% / /tmp → OS default player

yt-dlp is the only hard requirement for online playback.
For local playback any of tier 1-3 players work, or the OS default.

System audio tracking
---------------------
  Linux   : pactl (PulseAudio / PipeWire)
  macOS   : lsof → CoreAudio process enumeration
  Windows : PowerShell WASAPI session enumeration

Tools
-----
  MusicPlayTool    – start playback
  MusicStopTool    – stop a session
  MusicStatusTool  – list our sessions + query OS for all active audio streams
"""

from __future__ import annotations

import os
import sys
import json
import tempfile
import subprocess
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

from ..base import BaseTool, ToolOutput

log = logging.getLogger("music_tools")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_LOCAL_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus", ".mp4"
}

# In-memory session store  →  session_id: { "proc": Popen|None, "meta": dict }
_sessions: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------

def _has(cmd: str) -> bool:
    """True if `cmd` is on PATH."""
    return shutil.which(cmd) is not None


def _require_ytdlp() -> None:
    if not _has("yt-dlp"):
        raise RuntimeError(
            "'yt-dlp' is not installed.\n"
            "  Windows : pip install yt-dlp   (or)   winget install yt-dlp.yt-dlp\n"
            "  macOS   : brew install yt-dlp\n"
            "  Linux   : pip install yt-dlp"
        )


def _detect_cli_player() -> Optional[str]:
    """Return the first usable CLI audio player, or None."""
    for p in ("mpv", "vlc", "ffplay"):
        if _has(p):
            return p
    return None


def _player_args(player: str, target: str) -> List[str]:
    """Build the subprocess argv for a given player + audio target."""
    if player == "mpv":
        return ["mpv", "--no-video", "--really-quiet",
                "--ytdl-format=bestaudio/best", target]
    if player == "vlc":
        return ["vlc", "--intf", "dummy", "--no-video",
                "--play-and-exit", target]
    if player == "ffplay":
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", target]
    return [player, target]


# ---------------------------------------------------------------------------
# Online playback — tiered launcher
# ---------------------------------------------------------------------------

def _ytdlp_extract_url(query_uri: str) -> str:
    """
    Ask yt-dlp for the direct best-audio stream URL without downloading.
    Returns the URL string on success, raises on failure.
    """
    result = subprocess.run(
        ["yt-dlp", "--get-url", "--format", "bestaudio/best",
         "--no-playlist", query_uri],
        capture_output=True, text=True, timeout=30
    )
    url = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    if not url:
        raise RuntimeError(
            f"yt-dlp could not extract a stream URL.\n"
            f"stderr: {result.stderr.strip()[:300]}"
        )
    return url


def _ytdlp_download_temp(query_uri: str) -> str:
    """
    Download best audio to a temp file and return its path.
    Used as a last resort when no CLI player can handle a URL directly.
    """
    tmp_dir  = tempfile.mkdtemp(prefix="music_play_")
    out_tmpl = os.path.join(tmp_dir, "%(title)s.%(ext)s")

    result = subprocess.run(
        ["yt-dlp", "--format", "bestaudio/best",
         "--extract-audio", "--audio-format", "mp3",
         "--no-playlist", "-o", out_tmpl, query_uri],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"yt-dlp download failed.\nstderr: {result.stderr.strip()[:300]}"
        )

    files = list(Path(tmp_dir).glob("*"))
    if not files:
        raise RuntimeError("yt-dlp download produced no output file.")

    return str(files[0])


def _os_default_open(file_path: str) -> Optional[subprocess.Popen]:
    """Open a file with the OS default application. Returns Popen or None."""
    if sys.platform == "win32":
        os.startfile(file_path)       # no Popen on Windows startfile
        return None
    elif sys.platform == "darwin":
        return subprocess.Popen(["open", file_path],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
    else:
        return subprocess.Popen(["xdg-open", file_path],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)


def _launch_online(title: str, artist: str, album: str, source: str) -> Tuple[Optional[subprocess.Popen], str]:
    """
    Try each tier in order, return (Popen, method_used).

    Tier 1 – mpv  with ytdl:// URI        (mpv handles yt-dlp internally)
    Tier 2 – vlc / ffplay  with ytdl URL  (extract URL first via yt-dlp)
    Tier 3 – OS default player            (download to temp via yt-dlp)
    """
    _require_ytdlp()

    query     = " ".join(filter(None, [title, artist, album]))
    query_uri = f"scsearch1:{query}" if source == "soundcloud" else f"ytdl://ytsearch1:{query}"
    # yt-dlp search syntax for extract-url doesn't use ytdl:// prefix
    ytdlp_search = f"scsearch1:{query}" if source == "soundcloud" else f"ytsearch1:{query}"

    player = _detect_cli_player()

    # ── Tier 1: mpv (native yt-dlp integration) ────────────────────────
    if player == "mpv":
        proc = subprocess.Popen(
            _player_args("mpv", query_uri),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.info("Online playback via mpv (tier 1)")
        return proc, "mpv (native yt-dlp)"

    # ── Tier 2: vlc or ffplay — extract direct URL first ───────────────
    if player in ("vlc", "ffplay"):
        try:
            stream_url = _ytdlp_extract_url(ytdlp_search)
            proc = subprocess.Popen(
                _player_args(player, stream_url),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info("Online playback via %s + yt-dlp URL (tier 2)", player)
            return proc, f"{player} + yt-dlp stream URL"
        except Exception as e:
            log.warning("Tier 2 (%s + URL extract) failed: %s — falling to tier 3", player, e)

    # ── Tier 3: no CLI player — download to temp, OS default ───────────
    log.info("No CLI player found. Downloading via yt-dlp to temp file (tier 3)...")
    tmp_path = _ytdlp_download_temp(ytdlp_search)
    proc     = _os_default_open(tmp_path)
    log.info("Online playback via yt-dlp download + OS default (tier 3): %s", tmp_path)
    return proc, "yt-dlp download → OS default player"


# ---------------------------------------------------------------------------
# Local file launcher
# ---------------------------------------------------------------------------

def _launch_local(file_path: str) -> Tuple[Optional[subprocess.Popen], str]:
    """Play a local file, return (Popen | None, method_used)."""
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if path.suffix.lower() not in SUPPORTED_LOCAL_EXTENSIONS:
        raise ValueError(
            f"Unsupported format '{path.suffix}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_LOCAL_EXTENSIONS))}"
        )

    player = _detect_cli_player()
    if player:
        proc = subprocess.Popen(
            _player_args(player, str(path)),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return proc, player

    # OS default fallback
    proc = _os_default_open(str(path))
    return proc, "OS default player"



# ---------------------------------------------------------------------------
# Persistent session store  (survives across separate process runs)
# ---------------------------------------------------------------------------
# Stored at:  <tempdir>/music_play_sessions.json
# Schema  :  { session_id: { "pid": int, "meta": {...} } }

_SESSION_FILE = Path(tempfile.gettempdir()) / "music_play_sessions.json"


def _load_sessions() -> Dict[str, Any]:
    try:
        if _SESSION_FILE.exists():
            return json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_sessions(data: Dict[str, Any]) -> None:
    try:
        _SESSION_FILE.write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8"
        )
    except Exception as e:
        log.warning("Could not save session file: %s", e)


def _pid_alive(pid: int) -> bool:
    """Return True if the PID is still running."""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, timeout=5
            )
            return str(pid) in result.stdout
        else:
            os.kill(pid, 0)
            return True
    except (ProcessLookupError, PermissionError):
        return False
    except Exception:
        return False


def _kill_pid(pid: int, force: bool = False) -> str:
    """Kill a PID and its entire process tree. Returns method string."""
    try:
        if sys.platform == "win32":
            # /F = force  /T = kill entire child tree (critical for ffplay spawning children)
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=5
            )
            return "taskkill /F /T"
        else:
            os.kill(pid, 9 if force else 15)
            return "SIGKILL" if force else "SIGTERM"
    except Exception as exc:
        return f"error: {exc}"


def _kill_player_orphans(player: str) -> None:
    """
    Kill every running instance of a player executable by image name.
    Called before each new session so orphan processes from previous
    crashed/untracked runs are cleared before new audio starts.
    """
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/IM", f"{player}.exe"],
                capture_output=True, timeout=5
            )
        else:
            subprocess.run(["pkill", "-9", player], capture_output=True, timeout=5)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Progress tracking via ffprobe
# ---------------------------------------------------------------------------

def _get_duration_seconds(file_path: str) -> Optional[float]:
    if not _has("ffprobe"):
        return None
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            capture_output=True, text=True, timeout=10
        )
        val = r.stdout.strip()
        return float(val) if val else None
    except Exception:
        return None


def _fmt(seconds: Optional[float]) -> str:
    if seconds is None:
        return "unknown"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _progress_bar(pct: float, width: int = 20) -> str:
    filled = int(width * pct / 100)
    return f"[{'█' * filled}{'░' * (width - filled)}] {pct:.0f}%"


def _build_progress(meta: Dict[str, Any]) -> Dict[str, Any]:
    started_at = meta.get("started_at")
    duration   = meta.get("duration_seconds")
    if not started_at:
        return {}
    try:
        elapsed_s = max(0.0, (datetime.now() - datetime.fromisoformat(started_at)).total_seconds())
        out: Dict[str, Any] = {
            "elapsed":         _fmt(elapsed_s),
            "elapsed_seconds": round(elapsed_s, 1),
        }
        if duration:
            remaining_s = max(0.0, duration - elapsed_s)
            pct         = min(100.0, elapsed_s / duration * 100)
            out.update({
                "duration":          _fmt(duration),
                "duration_seconds":  round(duration, 1),
                "remaining":         _fmt(remaining_s),
                "remaining_seconds": round(remaining_s, 1),
                "percent_complete":  round(pct, 1),
                "progress_bar":      _progress_bar(pct),
            })
        return out
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# System-level audio tracking
# ---------------------------------------------------------------------------

def _system_audio_streams() -> List[Dict[str, Any]]:
    if sys.platform == "linux":
        return _audio_linux()
    elif sys.platform == "darwin":
        return _audio_macos()
    elif sys.platform == "win32":
        return _audio_windows()
    return []


def _audio_linux() -> List[Dict[str, Any]]:
    streams: List[Dict[str, Any]] = []
    try:
        r = subprocess.run(["pactl", "list", "sink-inputs"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return streams
        current: Dict[str, Any] = {}
        for raw in r.stdout.splitlines():
            line = raw.strip()
            if line.startswith("Sink Input #"):
                if current:
                    streams.append(current)
                current = {"sink_input_id": line.split("#")[1]}
            elif line.startswith("application.name"):
                current["app_name"] = line.split("=", 1)[-1].strip().strip('"')
            elif line.startswith("application.process.id"):
                current["pid"] = line.split("=", 1)[-1].strip().strip('"')
            elif line.startswith("media.name"):
                current["media_name"] = line.split("=", 1)[-1].strip().strip('"')
            elif "Mute:" in line:
                current["muted"] = "yes" in line.lower()
            elif "Volume:" in line and "%" in line:
                try:
                    current["volume_percent"] = int(line.split("/")[1].strip().replace("%", ""))
                except (IndexError, ValueError):
                    pass
        if current:
            streams.append(current)
    except FileNotFoundError:
        pass
    return streams


def _audio_macos() -> List[Dict[str, Any]]:
    streams: List[Dict[str, Any]] = []
    try:
        r = subprocess.run(["lsof", "-c", "coreaudiod", "-F", "pcn"],
                           capture_output=True, text=True, timeout=8)
        seen: set = set()
        pid = cmd = None
        for line in r.stdout.splitlines():
            if line.startswith("p"):   pid = line[1:]
            elif line.startswith("c"): cmd = line[1:]
            elif line.startswith("n") and pid and pid not in seen:
                seen.add(pid)
                streams.append({"pid": pid, "app_name": cmd or "unknown", "source": "CoreAudio"})
    except FileNotFoundError:
        pass
    return streams


def _audio_windows() -> List[Dict[str, Any]]:
    # ── Try pycaw first (precise WASAPI) ──────────────────────────────
    try:
        from pycaw.pycaw import AudioUtilities  # type: ignore
        result = []
        for s in AudioUtilities.GetAllSessions():
            if s.Process and s.State == 1:
                result.append({
                    "pid":      s.Process.pid,
                    "app_name": s.Process.name(),
                    "state":    "Active",
                    "source":   "WASAPI/pycaw",
                })
        return result
    except ImportError:
        pass
    except Exception as e:
        log.warning("pycaw failed: %s", e)

    # ── Fallback: tasklist filter for known audio player processes ─────
    audio_procs = {"mpv.exe", "vlc.exe", "ffplay.exe", "wmplayer.exe",
                   "groove.exe", "spotify.exe", "itunes.exe", "musicbee.exe"}
    streams: List[Dict[str, Any]] = []
    try:
        r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, timeout=8)
        for line in r.stdout.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[0].lower() in audio_procs:
                streams.append({
                    "pid":      parts[1],
                    "app_name": parts[0],
                    "state":    "running",
                    "source":   "tasklist",
                })
    except Exception as e:
        log.warning("tasklist audio scan failed: %s", e)
    return streams


# ---------------------------------------------------------------------------
# Tool 1 — MusicPlayTool
# ---------------------------------------------------------------------------

class MusicPlayTool(BaseTool):
    """
    Play music directly — no browser, no manual interaction.

    Params
    ------
    title      : str  – song / track name                    (required)
    artist     : str  – artist / band                        (optional)
    album      : str  – album                                (optional)
    source     : str  – "youtube" | "soundcloud" | "local"   (default: "youtube")
    file_path  : str  – absolute path — only for source=local
    session_id : str  – caller ID for stop/status tracking   (default: "default")
    """

    def get_tool_name(self) -> str:
        return "music_play"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        title      = self.get_input(inputs, "title", "")
        artist     = self.get_input(inputs, "artist", "")
        album      = self.get_input(inputs, "album", "")
        source     = self.get_input(inputs, "source", "youtube")
        file_path  = self.get_input(inputs, "file_path", None)
        session_id = self.get_input(inputs, "session_id", "default")

        # Step 1 — Kill the tracked session (if any) by PID
        sessions = _load_sessions()
        if session_id in sessions:
            old_pid = sessions[session_id].get("pid")
            if old_pid and _pid_alive(old_pid):
                _kill_pid(old_pid, force=True)

        # Step 2 — Kill ALL orphan instances of every player (catches processes
        #           from previous crashed / untracked runs that survived step 1)
        for _p in ("ffplay", "mpv", "vlc"):
            _kill_player_orphans(_p)

        try:
            duration_seconds: Optional[float] = None

            if source == "local":
                if not file_path:
                    return ToolOutput(success=False, data={},
                                      error="'file_path' is required when source='local'.")
                proc, method = _launch_local(file_path)
                path             = Path(file_path)
                duration_seconds = _get_duration_seconds(str(path))
                meta = {
                    "source":           "local",
                    "player_method":    method,
                    "file_path":        str(path),
                    "file_name":        path.name,
                    "format":           path.suffix.lstrip(".").upper(),
                    "title":            title or path.stem,
                    "artist":           artist,
                    "duration_seconds": duration_seconds,
                    "started_at":       datetime.now().isoformat(),
                }
            else:
                if not title:
                    return ToolOutput(success=False, data={},
                                      error="'title' is required for online playback.")
                proc, method = _launch_online(title, artist, album, source)
                meta = {
                    "source":           source,
                    "player_method":    method,
                    "query":            " ".join(filter(None, [title, artist, album])),
                    "title":            title,
                    "artist":           artist,
                    "album":            album,
                    "duration_seconds": None,
                    "started_at":       datetime.now().isoformat(),
                }

            pid = proc.pid if proc else None
            sessions[session_id] = {"pid": pid, "meta": meta}
            _save_sessions(sessions)

            self.logger.info(
                "Playback started | session=%s pid=%s method=%s source=%s title=%s",
                session_id, pid, method, source, title or file_path
            )

            return ToolOutput(
                success=True,
                data={**meta, "session_id": session_id, "process_id": pid},
            )

        except Exception as exc:
            self.logger.error("music_play failed: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ---------------------------------------------------------------------------
# Tool 2 — MusicStopTool
# ---------------------------------------------------------------------------

class MusicStopTool(BaseTool):
    """
    Stop one or all active playback sessions.
    Works even if called from a different process than music_play.

    Params
    ------
    session_id : str  – session to stop             (default: "default")
    force      : bool – hard-kill the process        (default: False)
    stop_all   : bool – stop every active session   (default: False)
    """

    def get_tool_name(self) -> str:
        return "music_stop"

    def _kill_session(self, session_id: str, sessions: Dict, force: bool) -> Dict[str, Any]:
        entry = sessions.pop(session_id, None)
        if not entry:
            return {"session_id": session_id, "error": "session not found"}

        pid  = entry.get("pid")
        meta = entry.get("meta", {})

        if not pid:
            return {"session_id": session_id, "warning": "No PID recorded.", "was_playing": meta}

        if not _pid_alive(pid):
            return {
                "session_id":  session_id,
                "process_id":  pid,
                "method":      "already finished",
                "was_playing": meta,
                "stopped_at":  datetime.now().isoformat(),
            }

        method = _kill_pid(pid, force)
        return {
            "session_id":  session_id,
            "process_id":  pid,
            "method":      method,
            "was_playing": meta,
            "stopped_at":  datetime.now().isoformat(),
        }

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        session_id = self.get_input(inputs, "session_id", "default")
        force      = self.get_input(inputs, "force", False)
        stop_all   = self.get_input(inputs, "stop_all", False)

        try:
            sessions = _load_sessions()

            if stop_all:
                ids     = list(sessions.keys())
                results = [self._kill_session(sid, sessions, force) for sid in ids]
                _save_sessions(sessions)
                return ToolOutput(success=True, data={"stopped": results, "count": len(results)})

            if session_id not in sessions:
                return ToolOutput(
                    success=False, data={},
                    error=f"No session '{session_id}' found. "
                          f"Active: {list(sessions.keys())}"
                )

            result = self._kill_session(session_id, sessions, force)
            _save_sessions(sessions)

            # Also nuke any orphan player processes not tracked in session file
            for _p in ("ffplay", "mpv", "vlc"):
                _kill_player_orphans(_p)

            return ToolOutput(success=True, data=result)

        except Exception as exc:
            self.logger.error("music_stop failed: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ---------------------------------------------------------------------------
# Tool 3 — MusicStatusTool
# ---------------------------------------------------------------------------

class MusicStatusTool(BaseTool):
    """
    Two-layer audio status report — works across process restarts.

    Layer 1 – Our sessions  : loaded from disk, PID-checked, with progress info.
    Layer 2 – System audio  : every process emitting audio at OS level.

    Params
    ------
    session_id     : str  – show one session only       (optional)
    include_system : bool – run OS-level audio scan     (default: True)
    """

    def get_tool_name(self) -> str:
        return "music_status"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        session_id     = self.get_input(inputs, "session_id", None)
        include_system = self.get_input(inputs, "include_system", True)

        sessions = _load_sessions()
        stale: List[str] = []
        our_sessions: List[Dict[str, Any]] = []

        scope = (
            {session_id: sessions[session_id]}
            if session_id and session_id in sessions
            else dict(sessions)
        )

        for sid, entry in scope.items():
            pid   = entry.get("pid")
            meta  = entry.get("meta", {})
            alive = _pid_alive(pid) if pid else False

            if not alive:
                stale.append(sid)

            our_sessions.append({
                "session_id":    sid,
                "state":         "▶ playing" if alive else "■ finished",
                "process_id":    pid,
                "title":         meta.get("title", ""),
                "artist":        meta.get("artist", ""),
                "source":        meta.get("source", ""),
                "player_method": meta.get("player_method", ""),
                "file_name":     meta.get("file_name", ""),
                "started_at":    meta.get("started_at", ""),
                "progress":      _build_progress(meta) if alive else {},
            })

        for sid in stale:
            del sessions[sid]
        if stale:
            _save_sessions(sessions)

        system_streams: List[Dict[str, Any]] = []
        system_error:   Optional[str]        = None

        if include_system:
            try:
                system_streams = _system_audio_streams()
            except Exception as exc:
                system_error = str(exc)
                self.logger.warning("System audio scan failed: %s", exc)

        return ToolOutput(
            success=True,
            data={
                "our_sessions": {
                    "sessions": our_sessions,
                    "total":    len(our_sessions),
                },
                "system_audio": {
                    "streams": system_streams,
                    "total":   len(system_streams),
                    "error":   system_error,
                    "note":    "All processes currently emitting audio at OS level.",
                } if include_system else {"note": "System scan skipped."},
                "timestamp": datetime.now().isoformat(),
            },
        )


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = ["MusicPlayTool", "MusicStopTool", "MusicStatusTool"]