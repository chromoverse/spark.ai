"""
IconResolver — Cross-platform app icon extractor.
Returns icons as base64-encoded PNG strings, ready for use in any UI:

    <img src="data:image/png;base64,{icon_b64}" width="32" height="32" />

Supported sources
─────────────────
Windows
  • EXE / MSC / CPL  → PowerShell System.Drawing.Icon.ExtractAssociatedIcon()
  • LNK shortcuts     → resolves target, then extracts from that EXE
  • UWP / Store apps  → reads AppxManifest.xml, finds PNG in Assets folder
  • Protocol handlers → maps known protocols to their host EXE

macOS
  • .app bundles      → reads CFBundleIconFile from Info.plist, converts ICNS→PNG

Linux
  • .desktop files    → parses Icon= field, searches XDG icon theme directories

All results are cached in memory so repeated lookups are instant.
"""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ── Icon size we target (pixels). Smaller = faster PowerShell, smaller b64. ──
_TARGET_SIZE = 48

# ── Protocols → the exe that actually owns the icon ──────────────────────────
_PROTOCOL_EXE: Dict[str, str] = {
    "calculator:":              "calc.exe",
    "ms-settings:":             r"ImmersiveControlPanel\SystemSettings.exe",
    "microsoft.windows.camera:":"WindowsCamera.exe",
    "ms-windows-store:":        "WinStore.App.exe",
    "xbox:":                    "XboxApp.exe",
    "bingmaps:":                "Maps.exe",
    "outlookmail:":             "HxOutlook.exe",
    "feedback-hub:":            "PilotshubApp.exe",
    "ms-gamebar:":              "GameBar.exe",
    "ms-screensketch:":         "ScreenSketch.exe",
    "ms-your-phone:":           "YourPhone.exe",
}

# ── Generic fallback icon (16×16 grey square as PNG, valid base64) ────────────
# Keeps UI consistent when nothing else works.
_FALLBACK_ICON: str = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAACXBIWXMAAAsTAAALEwEAmpwY"
    "AAAAB3RJTUUH6AcNBw8T1gNOoAAAACZJREFUOMtj/P//PwMFgHHUAAYGBgYWIrWPGsCoAYwa"
    "MGoAAAAA//8DAFxZBRmMqkO2AAAAAElFTkSuQmCC"
)


class IconResolver:
    """
    Resolves an app result dict → base64 PNG icon string.

    Usage:
        resolver = IconResolver()
        b64 = resolver.get_icon(app_result)   # app_result from AppSearcher
        # → "iVBORw0KGgoAAAANS..." or None
    """

    def __init__(self, use_fallback: bool = True):
        """
        Args:
            use_fallback: If True, returns a small grey placeholder instead of
                          None when no icon can be found.  Good for UI
                          consistency; set False if you prefer to hide icons.
        """
        self._cache: Dict[str, Optional[str]] = {}
        self._os           = sys.platform
        self._use_fallback = use_fallback

    # ─────────────────────────────────────────────────────────────────────────
    #  Public
    # ─────────────────────────────────────────────────────────────────────────
    def get_icon(self, app_result: Dict) -> Optional[str]:
        """
        Extract the icon for an app result returned by AppSearcher.find_app().

        Args:
            app_result: dict with at least 'path', 'type', and 'name' keys.

        Returns:
            Base64-encoded PNG string, or None (or fallback placeholder).
        """
        path     = app_result.get("path", "")
        app_type = app_result.get("type", "")
        name     = app_result.get("name", "")

        # Website / URL — no icon to extract
        if app_type in ("website", "url"):
            return self._favicon(path)

        cache_key = f"{path}|{app_type}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        icon = None
        try:
            if self._os == "win32":
                icon = self._win_icon(path, app_type, name)
            elif self._os == "darwin":
                icon = self._mac_icon(path, app_type)
            else:
                icon = self._linux_icon(path, app_type)
        except Exception as e:
            logger.debug("[IconResolver] error for '%s': %s", path, e)

        if icon is None and self._use_fallback:
            icon = _FALLBACK_ICON

        self._cache[cache_key] = icon
        return icon

    def clear_cache(self):
        """Wipe the icon cache (e.g. after app updates)."""
        self._cache.clear()

    # ─────────────────────────────────────────────────────────────────────────
    #  Windows
    # ─────────────────────────────────────────────────────────────────────────
    def _win_icon(self, path: str, app_type: str, name: str) -> Optional[str]:
        if app_type == "uwp_shell":
            return self._win_uwp_icon(name, path)
        if app_type == "protocol":
            return self._win_protocol_icon(path)
        if app_type in ("exe", "msc", "cpl", "lnk", "bat", "cmd"):
            return self._win_extract_from_file(path)
        return None

    def _win_extract_from_file(self, path: str) -> Optional[str]:
        """
        Extract icon from a file using System.Drawing via PowerShell.
        For .lnk files it first resolves the shortcut target.
        """
        safe = path.replace("'", "''")  # escape single quotes for PS

        ps = f"""
$ErrorActionPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Drawing

$target = '{safe}'

# Resolve shortcut (.lnk) to its target exe
if ($target.ToLower().EndsWith('.lnk')) {{
    $shell = New-Object -ComObject WScript.Shell
    $lnkObj = $shell.CreateShortcut($target)
    if ($lnkObj.TargetPath -and (Test-Path $lnkObj.TargetPath)) {{
        $target = $lnkObj.TargetPath
    }}
}}

if (-not (Test-Path $target)) {{ exit 1 }}

try {{
    $icon = [System.Drawing.Icon]::ExtractAssociatedIcon($target)
    if ($null -eq $icon) {{ exit 1 }}
    # Resize to {_TARGET_SIZE}x{_TARGET_SIZE}
    $bmp = New-Object System.Drawing.Bitmap({_TARGET_SIZE}, {_TARGET_SIZE})
    $g   = [System.Drawing.Graphics]::FromImage($bmp)
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.DrawImage($icon.ToBitmap(), 0, 0, {_TARGET_SIZE}, {_TARGET_SIZE})
    $g.Dispose()
    $ms  = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    [Convert]::ToBase64String($ms.ToArray())
    $ms.Dispose(); $bmp.Dispose(); $icon.Dispose()
}} catch {{ exit 1 }}
"""
        return self._run_ps(ps)

    def _win_uwp_icon(self, name: str, shell_path: str) -> Optional[str]:
        """
        For UWP apps, find the install location via Get-AppxPackage,
        then grab the best PNG from the Assets folder.

        Strategy:
          1. Parse PackageFamilyName from the shell:AppsFolder path
          2. Get-AppxPackage -PackageFamilyName to get InstallLocation
          3. Find the largest suitable PNG in Assets/ (exclude dark/contrast)
        """
        # Extract family name from "shell:AppsFolder\FamilyName!App"
        family_name = ""
        if "AppsFolder\\" in shell_path:
            try:
                family_name = shell_path.split("AppsFolder\\")[1].split("!")[0]
            except IndexError:
                pass

        # Build PowerShell query
        if family_name:
            pkg_query = f"Get-AppxPackage -PackageFamilyName '{family_name}'"
        else:
            safe_name = name.replace("'", "''")
            pkg_query = f"Get-AppxPackage | Where-Object {{ $_.Name -like '*{safe_name}*' }} | Select-Object -First 1"

        ps = f"""
$ErrorActionPreference = 'SilentlyContinue'
$pkg = {pkg_query}
if ($null -eq $pkg) {{ exit 1 }}

$loc = $pkg.InstallLocation
if (-not (Test-Path $loc)) {{ exit 1 }}

# Try AppxManifest.xml for the exact logo path first
$manifestPath = Join-Path $loc 'AppxManifest.xml'
$logoRel = $null
if (Test-Path $manifestPath) {{
    [xml]$xml = Get-Content $manifestPath -Raw
    # Namespace-agnostic search
    $logoNode = $xml.SelectSingleNode("//*[local-name()='Logo']")
    if ($logoNode) {{ $logoRel = $logoNode.InnerText.Trim() }}
}}

$iconPath = $null
if ($logoRel) {{
    $exactPath = Join-Path $loc $logoRel
    if (Test-Path $exactPath) {{
        $iconPath = $exactPath
    }} else {{
        # Logo may reference a scale-100 variant: try the Assets dir
        $dir  = [System.IO.Path]::GetDirectoryName($exactPath)
        $stem = [System.IO.Path]::GetFileNameWithoutExtension($exactPath)
        $iconPath = Get-ChildItem -Path $dir -Filter "$stem*.png" -ErrorAction SilentlyContinue |
                    Where-Object {{ $_.Name -notmatch '(?i)(contrast|dark|light|unplated)' }} |
                    Sort-Object Length -Descending |
                    Select-Object -ExpandProperty FullName -First 1
    }}
}}

# Fallback: search Assets folder broadly
if (-not $iconPath) {{
    $assetsDir = Join-Path $loc 'Assets'
    if (-not (Test-Path $assetsDir)) {{ $assetsDir = $loc }}
    $iconPath = Get-ChildItem -Path $assetsDir -Filter '*.png' -Recurse -ErrorAction SilentlyContinue |
                Where-Object {{ $_.Name -notmatch '(?i)(contrast|splash|lock|badge)' }} |
                Sort-Object Length -Descending |
                Select-Object -ExpandProperty FullName -First 1
}}

if (-not $iconPath -or -not (Test-Path $iconPath)) {{ exit 1 }}

# Resize via System.Drawing
Add-Type -AssemblyName System.Drawing
$srcBmp = [System.Drawing.Bitmap]::FromFile($iconPath)
$dstBmp = New-Object System.Drawing.Bitmap({_TARGET_SIZE}, {_TARGET_SIZE})
$g      = [System.Drawing.Graphics]::FromImage($dstBmp)
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g.DrawImage($srcBmp, 0, 0, {_TARGET_SIZE}, {_TARGET_SIZE})
$g.Dispose(); $srcBmp.Dispose()
$ms = New-Object System.IO.MemoryStream
$dstBmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
[Convert]::ToBase64String($ms.ToArray())
$ms.Dispose(); $dstBmp.Dispose()
"""
        return self._run_ps(ps)

    def _win_protocol_icon(self, protocol: str) -> Optional[str]:
        """Map protocol strings to their host executable and extract icon."""
        sysroot  = os.environ.get("SYSTEMROOT", r"C:\Windows")
        sys32    = os.path.join(sysroot, "System32")
        sysapps  = os.path.join(sysroot, "SystemApps")

        for prefix, rel_exe in _PROTOCOL_EXE.items():
            if protocol.startswith(prefix):
                # Try System32 first, then WindowsApps / SystemApps
                candidates = [
                    os.path.join(sys32, rel_exe),
                    os.path.join(sys32, os.path.basename(rel_exe)),
                ]
                # Also search WindowsApps for UWP hosts
                win_apps = r"C:\Program Files\WindowsApps"
                if os.path.isdir(win_apps):
                    for folder in os.listdir(win_apps):
                        exe_path = os.path.join(win_apps, folder,
                                                 os.path.basename(rel_exe))
                        candidates.append(exe_path)

                for c in candidates:
                    if os.path.isfile(c):
                        icon = self._win_extract_from_file(c)
                        if icon:
                            return icon
        return None

    # ─────────────────────────────────────────────────────────────────────────
    #  macOS
    # ─────────────────────────────────────────────────────────────────────────
    def _mac_icon(self, path: str, app_type: str) -> Optional[str]:
        if not path.endswith(".app") or not os.path.isdir(path):
            return None

        resources = os.path.join(path, "Contents", "Resources")
        plist     = os.path.join(path, "Contents", "Info.plist")

        # Try to read CFBundleIconFile from Info.plist
        icns_name: Optional[str] = None
        try:
            r = subprocess.run(
                ["defaults", "read", plist, "CFBundleIconFile"],
                capture_output=True, text=True, timeout=3,
            )
            icns_name = r.stdout.strip()
            if icns_name and not icns_name.endswith(".icns"):
                icns_name += ".icns"
        except Exception:
            pass

        icns_path: Optional[str] = None
        if icns_name:
            candidate = os.path.join(resources, icns_name)
            if os.path.isfile(candidate):
                icns_path = candidate

        if not icns_path:
            # Fallback: find any .icns in Resources
            try:
                files = [f for f in os.listdir(resources) if f.endswith(".icns")]
                if files:
                    # Prefer the one matching the app name
                    app_name = os.path.basename(path).removesuffix(".app")
                    best = next((f for f in files
                                 if app_name.lower() in f.lower()), files[0])
                    icns_path = os.path.join(resources, best)
            except Exception:
                pass

        if not icns_path:
            return None

        # Convert ICNS → PNG via sips (built into macOS)
        tmp = "/tmp/_searcher_icon_tmp.png"
        try:
            r = subprocess.run(
                ["sips", "-s", "format", "png", icns_path,
                 "--out", tmp,
                 "--resampleWidth", str(_TARGET_SIZE)],
                capture_output=True, timeout=5,
            )
            if os.path.isfile(tmp):
                with open(tmp, "rb") as f:
                    data = f.read()
                os.remove(tmp)
                return base64.b64encode(data).decode()
        except Exception:
            pass
        return None

    # ─────────────────────────────────────────────────────────────────────────
    #  Linux
    # ─────────────────────────────────────────────────────────────────────────
    def _linux_icon(self, path: str, app_type: str) -> Optional[str]:
        if app_type == "desktop" or path.endswith(".desktop"):
            return self._linux_desktop_icon(path)
        # Raw executables — try to find a matching .desktop file
        exe_name = os.path.basename(path)
        desktop_dirs = [
            "/usr/share/applications",
            "/usr/local/share/applications",
            str(Path.home() / ".local/share/applications"),
        ]
        for d in desktop_dirs:
            candidate = os.path.join(d, exe_name + ".desktop")
            if os.path.isfile(candidate):
                icon = self._linux_desktop_icon(candidate)
                if icon:
                    return icon
        return None

    def _linux_desktop_icon(self, desktop_path: str) -> Optional[str]:
        """Parse Icon= from a .desktop file and search XDG icon dirs."""
        icon_name: Optional[str] = None
        try:
            with open(desktop_path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("Icon="):
                        icon_name = line.split("=", 1)[1].strip()
                        break
        except Exception:
            return None

        if not icon_name:
            return None

        # Absolute path given directly
        if os.path.isabs(icon_name) and os.path.isfile(icon_name):
            return self._read_b64(icon_name)

        # Search XDG icon directories (prefer larger sizes for quality)
        size_dirs = [
            "scalable/apps", "256x256/apps", "128x128/apps",
            "64x64/apps",    "48x48/apps",   "32x32/apps",
        ]
        icon_bases = [
            "/usr/share/icons/hicolor",
            "/usr/share/icons/Adwaita",
            "/usr/share/icons/gnome",
            "/usr/share/icons/breeze",
            "/usr/share/icons/Papirus",
            "/usr/share/icons/oxygen",
        ]
        extensions = [".png", ".svg", ".xpm", ""]

        for base in icon_bases:
            for sz in size_dirs:
                for ext in extensions:
                    p = os.path.join(base, sz, icon_name + ext)
                    if os.path.isfile(p):
                        # SVG → convert via rsvg-convert or Inkscape if available
                        if p.endswith(".svg"):
                            b64 = self._svg_to_b64(p)
                            if b64:
                                return b64
                        elif p.endswith(".png"):
                            return self._read_b64(p)

        # Fallback: /usr/share/pixmaps
        for ext in (".png", ".svg", ".xpm", ""):
            p = os.path.join("/usr/share/pixmaps", icon_name + ext)
            if os.path.isfile(p):
                if p.endswith(".png"):
                    return self._read_b64(p)
                if p.endswith(".svg"):
                    return self._svg_to_b64(p)

        return None

    @staticmethod
    def _svg_to_b64(svg_path: str) -> Optional[str]:
        """Convert SVG → PNG base64 via rsvg-convert (if available)."""
        out = f"/tmp/_searcher_svg_{os.getpid()}.png"
        try:
            for tool, args in [
                ("rsvg-convert", ["-w", str(_TARGET_SIZE), "-h", str(_TARGET_SIZE),
                                  "-o", out, svg_path]),
                ("inkscape",     [f"--export-png={out}",
                                  f"--export-width={_TARGET_SIZE}",
                                  f"--export-height={_TARGET_SIZE}", svg_path]),
            ]:
                if subprocess.run(["which", tool],
                                  capture_output=True).returncode == 0:
                    subprocess.run([tool] + args, capture_output=True, timeout=5)
                    if os.path.isfile(out):
                        with open(out, "rb") as f:
                            data = f.read()
                        os.remove(out)
                        return base64.b64encode(data).decode()
        except Exception:
            pass
        return None

    # ─────────────────────────────────────────────────────────────────────────
    #  Website favicons
    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _favicon(url: str) -> Optional[str]:
        """
        Return a Google Favicon API URL for web results.
        Not base64 — just a URL string — but works as <img src="..."> too.

        We return a special dict key 'icon_url' for these instead of 'icon_b64'
        so callers can distinguish.  Here we just return the URL as a string
        prefixed with 'url:' so the caller can detect it.
        """
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url if url.startswith("http") else f"https://{url}")
            domain = parsed.netloc or parsed.path
            if domain:
                return f"url:https://www.google.com/s2/favicons?domain={domain}&sz={_TARGET_SIZE}"
        except Exception:
            pass
        return None

    # ─────────────────────────────────────────────────────────────────────────
    #  Utilities
    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _read_b64(path: str) -> Optional[str]:
        try:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode()
        except Exception:
            return None

    @staticmethod
    def _run_ps(script: str, timeout: int = 10) -> Optional[str]:
        """Run a PowerShell script and return its stdout as base64 or None."""
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=timeout,
            )
            b64 = r.stdout.strip()
            # Sanity check: real base64 PNG is at least a few hundred chars
            if b64 and len(b64) > 200 and not b64.startswith("Error"):
                # Validate it decodes to something PNG-like
                try:
                    raw = base64.b64decode(b64[:8])
                    if raw[:4] == b"\x89PNG":
                        return b64
                except Exception:
                    pass
        except subprocess.TimeoutExpired:
            logger.debug("[IconResolver] PowerShell timed out")
        except Exception as e:
            logger.debug("[IconResolver] PowerShell error: %s", e)
        return None