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


def _fetch_track_info(ytdlp_search: str) -> Dict[str, Any]:
    """
    Ask yt-dlp for track metadata (title, uploader, duration, thumbnail URL)
    WITHOUT downloading any media. Runs quickly (~1-2 s) in parallel intent.

    Returns a dict with whatever fields yt-dlp could resolve.
    Never raises — returns {} on any failure.
    """
    try:
        r = subprocess.run(
            [
                "yt-dlp",
                "--print", "%(title)s\t%(uploader)s\t%(duration)s\t%(thumbnail)s\t%(webpage_url)s",
                "--no-playlist",
                "--no-download",
                "-q",
                ytdlp_search,
            ],
            capture_output=True, text=True, timeout=15
        )
        line = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
        if not line:
            return {}
        parts = line.split("\t")
        info: Dict[str, Any] = {}
        labels = ["yt_title", "yt_uploader", "yt_duration_seconds", "thumbnail_url", "webpage_url"]
        for i, label in enumerate(labels):
            if i < len(parts) and parts[i] not in ("", "NA", "None"):
                info[label] = parts[i]
        if "yt_duration_seconds" in info:
            try:
                info["yt_duration_seconds"] = float(info["yt_duration_seconds"])
            except ValueError:
                del info["yt_duration_seconds"]
        return info
    except Exception:
        return {}


SOURCE_ICONS: Dict[str, str] = {
    "youtube":     "▶ YouTube",
    "soundcloud":  "☁ SoundCloud",
    "local":       "💾 Local File",
}


def _source_icon(source: str) -> str:
    return SOURCE_ICONS.get(source, f"♪ {source}")


def _launch_online(
    title: str, artist: str, album: str, source: str
) -> Tuple[Optional[subprocess.Popen], str, Optional[int]]:
    """
    Launch online playback. Returns (player_proc, method_str, aux_pid).

    aux_pid is the yt-dlp PID when piping — must also be killed on stop.

    Tier 1 – mpv  native yt-dlp           (single process, no URL expiry)
    Tier 2 – yt-dlp pipe → ffplay/vlc     (continuous feed, no URL expiry, no cuts)
    Tier 3 – yt-dlp download to temp      (guaranteed complete, slight delay)
    """
    _require_ytdlp()

    query        = " ".join(filter(None, [title, artist, album]))
    query_uri    = f"scsearch1:{query}" if source == "soundcloud" else f"ytdl://ytsearch1:{query}"
    ytdlp_search = f"scsearch1:{query}" if source == "soundcloud" else f"ytsearch1:{query}"
    player       = _detect_cli_player()

    # ── Tier 1: mpv handles yt-dlp natively — single process, best option ──
    if player == "mpv":
        proc = subprocess.Popen(
            _player_args("mpv", query_uri),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.info("Online playback via mpv native yt-dlp (tier 1)")
        return proc, "mpv (native yt-dlp)", None

    # ── Tier 2: pipe yt-dlp stdout → ffplay/vlc stdin ──────────────────
    #
    # WHY PIPE instead of URL extraction:
    #   - Direct CDN URLs expire mid-stream → audio cuts off before song ends
    #   - yt-dlp continuously downloads and feeds the player in real-time
    #   - ffplay reads from stdin pipe: playback is 100% complete every time
    #
    if player in ("ffplay", "vlc"):
        try:
            # yt-dlp writes raw best-audio bytes to stdout
            ytdlp_proc = subprocess.Popen(
                [
                    "yt-dlp",
                    "--format", "bestaudio/best",
                    "--no-playlist",
                    "-o", "-",          # output to stdout
                    "-q",               # quiet
                    ytdlp_search,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )

            if player == "ffplay":
                # ffplay reads from stdin pipe; -autoexit closes when stream ends
                player_proc = subprocess.Popen(
                    ["ffplay", "-nodisp", "-loglevel", "quiet",
                     "-autoexit", "-i", "pipe:0"],
                    stdin=ytdlp_proc.stdout,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:  # vlc
                player_proc = subprocess.Popen(
                    ["vlc", "--intf", "dummy", "--no-video",
                     "--play-and-exit", "-"],
                    stdin=ytdlp_proc.stdout,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            # Close our copy of stdout so player gets EOF when yt-dlp exits
            ytdlp_proc.stdout.close()  # type: ignore[union-attr]

            log.info("Online playback via yt-dlp pipe → %s (tier 2)", player)
            return player_proc, f"yt-dlp pipe → {player}", ytdlp_proc.pid

        except Exception as e:
            log.warning("Tier 2 pipe failed: %s — falling to tier 3", e)

    # ── Tier 3: download to temp file then play with OS default ────────
    log.info("Downloading via yt-dlp to temp file (tier 3)…")
    tmp_path = _ytdlp_download_temp(ytdlp_search)
    proc     = _os_default_open(tmp_path)
    log.info("Playback via yt-dlp download + OS default (tier 3): %s", tmp_path)
    return proc, "yt-dlp download → OS default player", None


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
# Process suspend / resume  (pause / unpause without killing)
# ---------------------------------------------------------------------------

def _get_process_tree(root_pid: int) -> List[int]:
    """
    Return root_pid + every descendant PID.
    ffplay (and mpv/vlc) spawn child processes for audio output — we must
    suspend/resume the entire tree or the children keep playing.
    """
    pids = [root_pid]
    try:
        import psutil  # preferred: pip install psutil
        for child in psutil.Process(root_pid).children(recursive=True):
            pids.append(child.pid)
        return pids
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback: wmic (available on all Windows versions)
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ["wmic", "process", "where",
                 f"(ParentProcessId={root_pid})", "get", "ProcessId", "/format:csv"],
                capture_output=True, text=True, timeout=5
            )
            for line in r.stdout.splitlines():
                parts = line.strip().split(",")
                if parts and parts[-1].strip().isdigit():
                    child_pid = int(parts[-1].strip())
                    if child_pid != root_pid:
                        pids.append(child_pid)
        except Exception:
            pass
    return pids


def _nt_suspend_one(pid: int) -> bool:
    """Suspend a single PID via NtSuspendProcess. Returns True on success."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        ntdll    = ctypes.windll.ntdll
        handle   = kernel32.OpenProcess(0x0800, False, pid)   # PROCESS_SUSPEND_RESUME
        if not handle:
            return False
        ret = ntdll.NtSuspendProcess(handle)
        kernel32.CloseHandle(handle)
        return ret == 0
    except Exception:
        return False


def _nt_resume_one(pid: int) -> bool:
    """Resume a single PID via NtResumeProcess. Returns True on success."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        ntdll    = ctypes.windll.ntdll
        handle   = kernel32.OpenProcess(0x0800, False, pid)
        if not handle:
            return False
        ret = ntdll.NtResumeProcess(handle)
        kernel32.CloseHandle(handle)
        return ret == 0
    except Exception:
        return False


def _suspend_pid(pid: int) -> str:
    """
    Suspend the entire process tree rooted at pid.
    Suspending only the parent leaves audio-output child processes running.
    """
    tree = _get_process_tree(pid)
    log.debug("Suspending process tree for pid=%s: %s", pid, tree)

    if sys.platform == "win32":
        ok  = [p for p in tree if _nt_suspend_one(p)]
        failed = [p for p in tree if p not in ok]
        if failed:
            log.warning("Could not suspend child PIDs: %s", failed)
        return f"NtSuspendProcess (tree: {ok})" if ok else f"error: all suspends failed {tree}"
    else:
        import signal
        for p in tree:
            try:
                os.kill(p, signal.SIGSTOP)
            except Exception:
                pass
        return f"SIGSTOP (tree: {tree})"


def _resume_pid(pid: int) -> str:
    """
    Resume the entire process tree rooted at pid.
    Children must be resumed in reverse order (leaves first) to avoid deadlocks.
    """
    tree = list(reversed(_get_process_tree(pid)))   # leaves first
    log.debug("Resuming process tree for pid=%s: %s", pid, tree)

    if sys.platform == "win32":
        ok = [p for p in tree if _nt_resume_one(p)]
        return f"NtResumeProcess (tree: {ok})"
    else:
        import signal
        for p in tree:
            try:
                os.kill(p, signal.SIGCONT)
            except Exception:
                pass
        return f"SIGCONT (tree: {tree})"


# ---------------------------------------------------------------------------
# Progress tracking via ffprobe
# ---------------------------------------------------------------------------

def _extract_embedded_art(file_path: str) -> Optional[str]:
    """
    Extract the first embedded image (cover art) from an audio file to a temp PNG.
    Returns the temp file path, or None if unavailable / ffmpeg not installed.
    """
    if not _has("ffmpeg"):
        return None
    try:
        out_path = str(Path(tempfile.gettempdir()) / f"music_art_{Path(file_path).stem}.png")
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", file_path,
             "-an", "-vcodec", "png", "-vframes", "1", out_path],
            capture_output=True, timeout=8
        )
        return out_path if Path(out_path).exists() and Path(out_path).stat().st_size > 0 else None
    except Exception:
        return None


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
    started_at          = meta.get("started_at")
    duration            = meta.get("duration_seconds")
    paused_at           = meta.get("paused_at")           # ISO str if currently paused
    total_paused_secs   = meta.get("total_paused_seconds", 0.0)
    is_paused           = meta.get("playback_state") == "paused"

    if not started_at:
        return {}
    try:
        wall_elapsed = max(0.0, (datetime.now() - datetime.fromisoformat(started_at)).total_seconds())

        # Subtract all accumulated pause time so elapsed reflects actual audio position
        paused_contribution = total_paused_secs
        if is_paused and paused_at:
            # Currently paused: add time since paused_at to contribution
            paused_contribution += max(0.0, (
                datetime.now() - datetime.fromisoformat(paused_at)
            ).total_seconds())

        elapsed_s = max(0.0, wall_elapsed - paused_contribution)

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

    Inputs:
    - title (string, required): Song or track name
    - artist (string, optional): Artist or band — improves search match
    - album (string, optional): Album name — narrows ambiguous titles
    - source (string, optional): 'youtube' | 'soundcloud' | 'local'
    - file_path (string, optional): Absolute path to local audio file — required only when source='local'
    - session_id (string, optional): ID to track this session for stop/status control

    Outputs:
    - source (string)
    - title (string)
    - artist (string)
    - album (string)
    - query (string): Search query used — online only
    - file_path (string): Local only
    - file_name (string): Local only
    - format (string): Audio format — local only
    - session_id (string)
    - process_id (integer)
    - started_at (string)
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
                aux_pid = None
                path             = Path(file_path)
                duration_seconds = _get_duration_seconds(str(path))
                # Try to extract embedded album art as a temp PNG for thumbnail
                thumb_path = _extract_embedded_art(str(path))
                meta = {
                    "source":           "local",
                    "source_icon":      _source_icon("local"),
                    "player_method":    method,
                    "file_path":        str(path),
                    "file_name":        path.name,
                    "format":           path.suffix.lstrip(".").upper(),
                    "title":            title or path.stem,
                    "artist":           artist,
                    "album":            album,
                    "thumbnail_url":    None,
                    "thumbnail_local":  thumb_path,
                    "webpage_url":      None,
                    "duration_seconds": duration_seconds,
                    "started_at":       datetime.now().isoformat(),
                }
            else:
                if not title:
                    return ToolOutput(success=False, data={},
                                      error="'title' is required for online playback.")
                ytdlp_search_q = f"scsearch1:{' '.join(filter(None,[title,artist,album]))}" if source == "soundcloud" else f"ytsearch1:{' '.join(filter(None,[title,artist,album]))}"
                # Fetch rich metadata (thumbnail, resolved title, duration) before launching
                track_info = _fetch_track_info(ytdlp_search_q)
                proc, method, aux_pid = _launch_online(title, artist, album, source)
                resolved_title  = track_info.get("yt_title",    title)
                resolved_artist = track_info.get("yt_uploader", artist)
                meta = {
                    "source":           source,
                    "source_icon":      _source_icon(source),
                    "player_method":    method,
                    "query":            " ".join(filter(None, [title, artist, album])),
                    "title":            resolved_title,
                    "artist":           resolved_artist,
                    "album":            album,
                    "thumbnail_url":    track_info.get("thumbnail_url"),
                    "webpage_url":      track_info.get("webpage_url"),
                    "duration_seconds": track_info.get("yt_duration_seconds"),
                    "started_at":       datetime.now().isoformat(),
                }

            pid = proc.pid if proc else None
            sessions[session_id] = {
                "pid":     pid,
                "aux_pid": aux_pid if source != "local" else None,
                "meta":    meta,
            }
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

    Inputs:
    - session_id (string, optional): Session to stop
    - force (boolean, optional): Force-kill (SIGKILL) instead of graceful terminate (SIGTERM)
    - stop_all (boolean, optional): Stop every active session at once

    Outputs:
    - session_id (string)
    - process_id (integer)
    - method (string)
    - was_playing (object)
    - stopped_at (string)
    - stopped (array): Present when stop_all=true
    - count (integer): Present when stop_all=true
    """

    def get_tool_name(self) -> str:
        return "music_stop"

    def _kill_session(self, session_id: str, sessions: Dict, force: bool) -> Dict[str, Any]:
        entry = sessions.pop(session_id, None)
        if not entry:
            return {"session_id": session_id, "error": "session not found"}

        pid     = entry.get("pid")
        aux_pid = entry.get("aux_pid")   # yt-dlp PID when using pipe mode
        meta    = entry.get("meta", {})

        if not pid:
            return {"session_id": session_id, "warning": "No PID recorded.", "was_playing": meta}

        method = "already finished"
        if _pid_alive(pid):
            method = _kill_pid(pid, force)

        # Also kill the yt-dlp feeder process so it doesn't linger
        if aux_pid and _pid_alive(aux_pid):
            _kill_pid(aux_pid, force=True)

        return {
            "session_id":  session_id,
            "process_id":  pid,
            "aux_pid":     aux_pid,
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

    Inputs:
    - session_id (string, optional): Filter our sessions to one ID. Omit to list all.
    - include_system (boolean, optional): Run OS-level audio scan (pactl / CoreAudio / WASAPI)

    Outputs:
    - our_sessions (object): sessions[] array + total count
    - system_audio (object): streams[] array + total + optional error note
    - timestamp (string)
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

            playback_state = meta.get("playback_state", "playing") if alive else "finished"
            state_icon = {"playing": "▶", "paused": "⏸", "finished": "■"}.get(playback_state, "▶")

            our_sessions.append({
                "session_id":      sid,
                "state":           f"{state_icon} {playback_state}",
                "process_id":      pid,
                # ── identity ──────────────────────────────────────────────
                "title":           meta.get("title", ""),
                "artist":          meta.get("artist", ""),
                "album":           meta.get("album", ""),
                "source":          meta.get("source", ""),
                "source_icon":     meta.get("source_icon", _source_icon(meta.get("source", ""))),
                # ── artwork ───────────────────────────────────────────────
                "thumbnail_url":   meta.get("thumbnail_url"),    # remote URL (online tracks)
                "thumbnail_local": meta.get("thumbnail_local"),  # local path  (local files)
                # ── links & file ──────────────────────────────────────────
                "webpage_url":     meta.get("webpage_url"),
                "file_name":       meta.get("file_name", ""),
                "format":          meta.get("format", ""),
                # ── playback ──────────────────────────────────────────────
                "player_method":   meta.get("player_method", ""),
                "started_at":      meta.get("started_at", ""),
                "progress":        _build_progress(meta) if alive else {},
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
# Tool 4 — MusicPauseTool
# ---------------------------------------------------------------------------

class MusicPauseTool(BaseTool):
    """
    Pause an active playback session by suspending the player process.
    Audio stops immediately; the stream / file position is preserved.
    Resume with music_resume.

    Params
    ------
    session_id : str  – session to pause  (default: "default")

    Inputs:
    - session_id (string, optional): Session to pause

    Outputs:
    - session_id (string)
    - process_id (integer)
    - method (string): NtSuspendProcess (Win) or SIGSTOP (Unix)
    - title (string)
    - artist (string)
    - progress (object): elapsed / remaining at moment of pause
    - paused_at (string)
    """

    def get_tool_name(self) -> str:
        return "music_pause"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        session_id = self.get_input(inputs, "session_id", "default")

        try:
            sessions = _load_sessions()
            if session_id not in sessions:
                return ToolOutput(
                    success=False, data={},
                    error=f"No session '{session_id}'. Active: {list(sessions.keys())}"
                )

            entry = sessions[session_id]
            pid   = entry.get("pid")
            meta  = entry.get("meta", {})

            if meta.get("playback_state") == "paused":
                return ToolOutput(
                    success=False, data={},
                    error=f"Session '{session_id}' is already paused."
                )

            if not pid or not _pid_alive(pid):
                return ToolOutput(success=False, data={}, error="Process is not running.")

            method = _suspend_pid(pid)
            if method.startswith("error"):
                return ToolOutput(success=False, data={}, error=method)

            # Record pause timestamp in meta for accurate progress tracking
            now_iso = datetime.now().isoformat()
            meta["playback_state"]  = "paused"
            meta["paused_at"]       = now_iso
            sessions[session_id]["meta"] = meta
            _save_sessions(sessions)

            self.logger.info("Paused | session=%s pid=%s method=%s", session_id, pid, method)

            return ToolOutput(
                success=True,
                data={
                    "session_id": session_id,
                    "process_id": pid,
                    "method":     method,
                    "title":      meta.get("title", ""),
                    "artist":     meta.get("artist", ""),
                    "progress":   _build_progress(meta),
                    "paused_at":  now_iso,
                },
            )

        except Exception as exc:
            self.logger.error("music_pause failed: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ---------------------------------------------------------------------------
# Tool 5 — MusicResumeTool
# ---------------------------------------------------------------------------

class MusicResumeTool(BaseTool):
    """
    Resume a paused playback session.

    Params
    ------
    session_id : str  – session to resume  (default: "default")

    Inputs:
    - session_id (string, optional): Session to resume

    Outputs:
    - session_id (string)
    - process_id (integer)
    - method (string): NtResumeProcess (Win) or SIGCONT (Unix)
    - title (string)
    - artist (string)
    - progress (object): elapsed / remaining after resume
    - resumed_at (string)
    """

    def get_tool_name(self) -> str:
        return "music_resume"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        session_id = self.get_input(inputs, "session_id", "default")

        try:
            sessions = _load_sessions()
            if session_id not in sessions:
                return ToolOutput(
                    success=False, data={},
                    error=f"No session '{session_id}'. Active: {list(sessions.keys())}"
                )

            entry = sessions[session_id]
            pid   = entry.get("pid")
            meta  = entry.get("meta", {})

            if meta.get("playback_state") != "paused":
                return ToolOutput(
                    success=False, data={},
                    error=f"Session '{session_id}' is not paused (state: {meta.get('playback_state', 'playing')})."
                )

            if not pid or not _pid_alive(pid):
                return ToolOutput(success=False, data={}, error="Process is not running.")

            method = _resume_pid(pid)
            if method.startswith("error"):
                return ToolOutput(success=False, data={}, error=method)

            # Accumulate how long we were paused so _build_progress stays accurate
            paused_at = meta.get("paused_at")
            if paused_at:
                pause_duration = max(0.0, (
                    datetime.now() - datetime.fromisoformat(paused_at)
                ).total_seconds())
                meta["total_paused_seconds"] = meta.get("total_paused_seconds", 0.0) + pause_duration

            meta["playback_state"] = "playing"
            meta["paused_at"]      = None
            sessions[session_id]["meta"] = meta
            _save_sessions(sessions)

            now_iso = datetime.now().isoformat()
            self.logger.info("Resumed | session=%s pid=%s method=%s", session_id, pid, method)

            return ToolOutput(
                success=True,
                data={
                    "session_id": session_id,
                    "process_id": pid,
                    "method":     method,
                    "title":      meta.get("title", ""),
                    "artist":     meta.get("artist", ""),
                    "progress":   _build_progress(meta),
                    "resumed_at": now_iso,
                },
            )

        except Exception as exc:
            self.logger.error("music_resume failed: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "MusicPlayTool",
    "MusicPauseTool",
    "MusicResumeTool",
    "MusicStopTool",
    "MusicStatusTool",
]