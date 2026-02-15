"""
AppSearcher — Deep system-wide application discovery.
Covers: protocol handlers, natural-language commands, registry, UWP/Store,
        Start-Menu, PATH, file-system scan, AND web fallback (via built-in resolver).

Usage:
    searcher = AppSearcher()
    result   = searcher.find_app("event viewer")
    # → {"name": "Event Viewer", "path": "eventvwr.msc", "type": "msc", ...}
"""

from __future__ import annotations

import os
import re
import sys
import time
import shutil
import logging
import subprocess
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from .icon_resolver import IconResolver

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  KNOWN WEBSITES — browser fallback dictionary (non-system / web apps)
# ══════════════════════════════════════════════════════════════════════════════
KNOWN_WEBSITES: Dict[str, str] = {
    # Social
    "youtube": "https://youtube.com",
    "twitter": "https://twitter.com",
    "x": "https://x.com",
    "facebook": "https://facebook.com",
    "instagram": "https://instagram.com",
    "linkedin": "https://linkedin.com",
    "reddit": "https://reddit.com",
    "tiktok": "https://tiktok.com",
    "discord": "https://discord.com",
    "telegram": "https://web.telegram.org",
    "whatsapp": "https://web.whatsapp.com",
    "snapchat": "https://web.snapchat.com",
    "pinterest": "https://pinterest.com",
    "tumblr": "https://tumblr.com",
    "mastodon": "https://mastodon.social",
    "threads": "https://threads.net",
    "bluesky": "https://bsky.app",
    # Streaming
    "netflix": "https://netflix.com",
    "disney": "https://disneyplus.com",
    "hulu": "https://hulu.com",
    "prime": "https://primevideo.com",
    "prime video": "https://primevideo.com",
    "spotify": "https://spotify.com",
    "twitch": "https://twitch.tv",
    "youtube music": "https://music.youtube.com",
    "apple music": "https://music.apple.com",
    "soundcloud": "https://soundcloud.com",
    "deezer": "https://deezer.com",
    "tidal": "https://tidal.com",
    "pandora": "https://pandora.com",
    "crunchyroll": "https://crunchyroll.com",
    "funimation": "https://funimation.com",
    "peacock": "https://peacocktv.com",
    "hbo": "https://max.com",
    "max": "https://max.com",
    "paramount": "https://paramountplus.com",
    "apple tv": "https://tv.apple.com",
    "plex": "https://app.plex.tv",
    # Productivity
    "github": "https://github.com",
    "gitlab": "https://gitlab.com",
    "bitbucket": "https://bitbucket.org",
    "notion": "https://notion.so",
    "figma": "https://figma.com",
    "gmail": "https://gmail.com",
    "outlook": "https://outlook.com",
    "drive": "https://drive.google.com",
    "google drive": "https://drive.google.com",
    "docs": "https://docs.google.com",
    "google docs": "https://docs.google.com",
    "sheets": "https://sheets.google.com",
    "google sheets": "https://sheets.google.com",
    "slides": "https://slides.google.com",
    "calendar": "https://calendar.google.com",
    "meet": "https://meet.google.com",
    "zoom": "https://zoom.us",
    "teams": "https://teams.microsoft.com",
    "slack": "https://slack.com",
    "jira": "https://atlassian.net",
    "confluence": "https://atlassian.net",
    "trello": "https://trello.com",
    "asana": "https://asana.com",
    "monday": "https://monday.com",
    "clickup": "https://clickup.com",
    "airtable": "https://airtable.com",
    "basecamp": "https://basecamp.com",
    "linear": "https://linear.app",
    "craft": "https://craft.do",
    "obsidian": "https://obsidian.md",
    "roam": "https://roamresearch.com",
    "coda": "https://coda.io",
    "evernote": "https://evernote.com",
    "onenote": "https://onenote.com",
    "dropbox": "https://dropbox.com",
    "box": "https://box.com",
    "onedrive": "https://onedrive.live.com",
    # Shopping
    "amazon": "https://amazon.com",
    "ebay": "https://ebay.com",
    "etsy": "https://etsy.com",
    "aliexpress": "https://aliexpress.com",
    "shopify": "https://shopify.com",
    "walmart": "https://walmart.com",
    "target": "https://target.com",
    # Reference
    "wikipedia": "https://wikipedia.org",
    "stackoverflow": "https://stackoverflow.com",
    "mdn": "https://developer.mozilla.org",
    "w3schools": "https://w3schools.com",
    "devdocs": "https://devdocs.io",
    "caniuse": "https://caniuse.com",
    # AI
    "claude": "https://claude.ai",
    "chatgpt": "https://chat.openai.com",
    "openai": "https://chat.openai.com",
    "gemini": "https://gemini.google.com",
    "copilot": "https://copilot.microsoft.com",
    "perplexity": "https://perplexity.ai",
    "midjourney": "https://midjourney.com",
    "stability": "https://stability.ai",
    "huggingface": "https://huggingface.co",
    "replicate": "https://replicate.com",
    "anthropic": "https://anthropic.com",
    # Dev / Cloud
    "vercel": "https://vercel.com",
    "netlify": "https://netlify.com",
    "heroku": "https://heroku.com",
    "railway": "https://railway.app",
    "render": "https://render.com",
    "supabase": "https://supabase.com",
    "firebase": "https://firebase.google.com",
    "aws": "https://aws.amazon.com",
    "azure": "https://portal.azure.com",
    "gcp": "https://console.cloud.google.com",
    "docker": "https://hub.docker.com",
    "npm": "https://npmjs.com",
    "pypi": "https://pypi.org",
    "codepen": "https://codepen.io",
    "codesandbox": "https://codesandbox.io",
    "replit": "https://replit.com",
    "stackblitz": "https://stackblitz.com",
    # News / Community
    "hackernews": "https://news.ycombinator.com",
    "hn": "https://news.ycombinator.com",
    "producthunt": "https://producthunt.com",
    "devto": "https://dev.to",
    "medium": "https://medium.com",
    "substack": "https://substack.com",
    # Finance
    "paypal": "https://paypal.com",
    "stripe": "https://stripe.com",
    "coinbase": "https://coinbase.com",
    "binance": "https://binance.com",
    "robinhood": "https://robinhood.com",
    # Entertainment
    "netmirror": "https://net20.cc/home",
    "cineby": "https://www.cineby.gd",
    "imdb": "https://imdb.com",
    "letterboxd": "https://letterboxd.com",
    "rottentomatoes": "https://rottentomatoes.com",
    "goodreads": "https://goodreads.com",
    "anilist": "https://anilist.co",
    "myanimelist": "https://myanimelist.net",
    "mal": "https://myanimelist.net",
    "chess": "https://chess.com",
    "lichess": "https://lichess.org",
    # Search
    "google": "https://google.com",
    "bing": "https://bing.com",
    "duckduckgo": "https://duckduckgo.com",
    "ddg": "https://duckduckgo.com",
    "brave search": "https://search.brave.com",
}

# ══════════════════════════════════════════════════════════════════════════════
#  PROTOCOL HANDLERS — Windows UWP / ms-settings / shell:
# ══════════════════════════════════════════════════════════════════════════════
PROTOCOL_HANDLERS: Dict[str, str] = {
    # Core UWP
    "camera":            "microsoft.windows.camera:",
    "calculator":        "calculator:",
    "settings":          "ms-settings:",
    "store":             "ms-windows-store:",
    "xbox":              "xbox:",
    "maps":              "bingmaps:",
    "mail":              "outlookmail:",
    "news":              "bingnews:",
    "weather":           "bingweather:",
    "phone link":        "ms-your-phone:",
    "your phone":        "ms-your-phone:",
    "feedback hub":      "feedback-hub:",
    "get started":       "ms-get-started:",
    # ms-settings (direct protocol strings pass through)
    "ms-settings:network":             "ms-settings:network",
    "ms-settings:privacy-microphone":  "ms-settings:privacy-microphone",
    "ms-settings:windowsupdate":       "ms-settings:windowsupdate",
    "ms-settings:display":             "ms-settings:display",
    "ms-settings:personalization":     "ms-settings:personalization",
    "ms-settings:accounts":            "ms-settings:accounts",
    "ms-settings:bluetooth":           "ms-settings:bluetooth",
    "ms-settings:printers":            "ms-settings:printers",
    "ms-settings:apps":                "ms-settings:apps",
    "ms-settings:gaming":              "ms-settings:gaming",
    "ms-settings:accessibility":       "ms-settings:accessibility",
    "ms-settings:privacy":             "ms-settings:privacy",
    "ms-settings:dateandtime":         "ms-settings:dateandtime",
    "ms-settings:speech":              "ms-settings:speech",
    "ms-settings:startupapps":         "ms-settings:startupapps",
    "ms-settings:clipboard":           "ms-settings:clipboard",
    "ms-settings:storagepolicies":     "ms-settings:storagepolicies",
    "ms-settings:deviceencryption":    "ms-settings:deviceencryption",
    "ms-settings:network-status":      "ms-settings:network-status",
    "ms-settings:network-ethernet":    "ms-settings:network-ethernet",
    "ms-settings:network-wifi":        "ms-settings:network-wifi",
    "ms-settings:network-vpn":         "ms-settings:network-vpn",
    "ms-settings:network-proxy":       "ms-settings:network-proxy",
    "ms-settings:devices":             "ms-settings:devices",
    "ms-settings:system":              "ms-settings:system",
    "ms-settings:easeofaccess":        "ms-settings:easeofaccess",
    # shell: folders
    "shell:startup":      "shell:startup",
    "shell:downloads":    "shell:downloads",
    "shell:appsfolder":   "shell:appsfolder",
    "shell:desktop":      "shell:desktop",
    "shell:documents":    "shell:documents",
    "shell:pictures":     "shell:pictures",
    "shell:music":        "shell:music",
    "shell:videos":       "shell:videos",
    "shell:recent":       "shell:recent",
    "shell:sendto":       "shell:sendto",
    "shell:favorites":    "shell:favorites",
    "shell:programfiles": "shell:programfiles",
    "shell:appdata":      "shell:appdata",
    "shell:localappdata": "shell:localappdata",
    "shell:common startup": "shell:common startup",
    "shell:commonprograms": "shell:commonprograms",
}

# ══════════════════════════════════════════════════════════════════════════════
#  NATURAL LANGUAGE MAP — human phrases → Windows commands
# ══════════════════════════════════════════════════════════════════════════════
_NL = Dict[str, Any]
NATURAL_LANGUAGE_MAP: Dict[str, _NL] = {
    # ── MMC snap-ins ──────────────────────────────────────────────────────────
    "services":                    {"cmd": "services.msc",         "type": "msc",      "name": "Services"},
    "services.msc":                {"cmd": "services.msc",         "type": "msc",      "name": "Services"},
    "event viewer":                {"cmd": "eventvwr.msc",         "type": "msc",      "name": "Event Viewer"},
    "event log":                   {"cmd": "eventvwr.msc",         "type": "msc",      "name": "Event Viewer"},
    "eventvwr":                    {"cmd": "eventvwr.msc",         "type": "msc",      "name": "Event Viewer"},
    "task scheduler":              {"cmd": "taskschd.msc",         "type": "msc",      "name": "Task Scheduler"},
    "scheduled tasks":             {"cmd": "taskschd.msc",         "type": "msc",      "name": "Task Scheduler"},
    "disk management":             {"cmd": "diskmgmt.msc",         "type": "msc",      "name": "Disk Management"},
    "local group policy editor":   {"cmd": "gpedit.msc",           "type": "msc",      "name": "Group Policy Editor"},
    "group policy":                {"cmd": "gpedit.msc",           "type": "msc",      "name": "Group Policy Editor"},
    "gpedit":                      {"cmd": "gpedit.msc",           "type": "msc",      "name": "Group Policy Editor"},
    "gpedit.msc":                  {"cmd": "gpedit.msc",           "type": "msc",      "name": "Group Policy Editor"},
    "performance monitor":         {"cmd": "perfmon.msc",          "type": "msc",      "name": "Performance Monitor"},
    "perfmon":                     {"cmd": "perfmon.msc",          "type": "msc",      "name": "Performance Monitor"},
    "reliability monitor":         {"cmd": "perfmon /rel",         "type": "cmd_args", "name": "Reliability Monitor"},
    "device manager":              {"cmd": "devmgmt.msc",          "type": "msc",      "name": "Device Manager"},
    "certificate manager":         {"cmd": "certmgr.msc",          "type": "msc",      "name": "Certificate Manager"},
    "certmgr":                     {"cmd": "certmgr.msc",          "type": "msc",      "name": "Certificate Manager"},
    "local users and groups":      {"cmd": "lusrmgr.msc",          "type": "msc",      "name": "Local Users & Groups"},
    "lusrmgr":                     {"cmd": "lusrmgr.msc",          "type": "msc",      "name": "Local Users & Groups"},
    "shared folders":              {"cmd": "fsmgmt.msc",           "type": "msc",      "name": "Shared Folders"},
    "wmi control":                 {"cmd": "wmimgmt.msc",          "type": "msc",      "name": "WMI Control"},
    "hyper-v manager":             {"cmd": "virtmgmt.msc",         "type": "msc",      "name": "Hyper-V Manager"},
    "hyperv manager":              {"cmd": "virtmgmt.msc",         "type": "msc",      "name": "Hyper-V Manager"},
    "hyper v":                     {"cmd": "virtmgmt.msc",         "type": "msc",      "name": "Hyper-V Manager"},
    "ip security policy":          {"cmd": "secpol.msc",           "type": "msc",      "name": "Security Policy"},
    "security policy":             {"cmd": "secpol.msc",           "type": "msc",      "name": "Security Policy"},
    "windows firewall advanced":   {"cmd": "wf.msc",               "type": "msc",      "name": "Firewall Advanced Security"},
    "firewall advanced":           {"cmd": "wf.msc",               "type": "msc",      "name": "Firewall Advanced Security"},
    "print management":            {"cmd": "printmanagement.msc",  "type": "msc",      "name": "Print Management"},
    "computer management":         {"cmd": "compmgmt.msc",         "type": "msc",      "name": "Computer Management"},
    "component services":          {"cmd": "dcomcnfg.exe",         "type": "exe",      "name": "Component Services"},
    "dcomcnfg":                    {"cmd": "dcomcnfg.exe",         "type": "exe",      "name": "Component Services"},

    # ── System utilities ─────────────────────────────────────────────────────
    "registry editor":              {"cmd": "regedit.exe",                          "type": "exe",      "name": "Registry Editor"},
    "regedit":                      {"cmd": "regedit.exe",                          "type": "exe",      "name": "Registry Editor"},
    "system configuration":         {"cmd": "msconfig.exe",                         "type": "exe",      "name": "System Configuration"},
    "msconfig":                     {"cmd": "msconfig.exe",                         "type": "exe",      "name": "System Configuration"},
    "advanced system settings":     {"cmd": "systempropertiesadvanced.exe",         "type": "exe",      "name": "Advanced System Settings"},
    "system properties":            {"cmd": "systempropertiesadvanced.exe",         "type": "exe",      "name": "System Properties"},
    "environment variables":        {"cmd": "rundll32 sysdm.cpl,EditEnvironmentVariables", "type": "rundll32", "name": "Environment Variables"},
    "env vars":                     {"cmd": "rundll32 sysdm.cpl,EditEnvironmentVariables", "type": "rundll32", "name": "Environment Variables"},
    "resource monitor":             {"cmd": "resmon.exe",                           "type": "exe",      "name": "Resource Monitor"},
    "resmon":                       {"cmd": "resmon.exe",                           "type": "exe",      "name": "Resource Monitor"},
    "dxdiag":                       {"cmd": "dxdiag.exe",                           "type": "exe",      "name": "DirectX Diagnostic Tool"},
    "directx diagnostic":           {"cmd": "dxdiag.exe",                           "type": "exe",      "name": "DirectX Diagnostic Tool"},
    "windows memory diagnostic":    {"cmd": "mdsched.exe",                          "type": "exe",      "name": "Windows Memory Diagnostic"},
    "memory diagnostic":            {"cmd": "mdsched.exe",                          "type": "exe",      "name": "Windows Memory Diagnostic"},
    "mdsched":                      {"cmd": "mdsched.exe",                          "type": "exe",      "name": "Windows Memory Diagnostic"},
    "steps recorder":               {"cmd": "psr.exe",                              "type": "exe",      "name": "Steps Recorder"},
    "problem steps recorder":       {"cmd": "psr.exe",                              "type": "exe",      "name": "Steps Recorder"},
    "psr":                          {"cmd": "psr.exe",                              "type": "exe",      "name": "Steps Recorder"},
    "character map":                {"cmd": "charmap.exe",                          "type": "exe",      "name": "Character Map"},
    "charmap":                      {"cmd": "charmap.exe",                          "type": "exe",      "name": "Character Map"},
    "snipping tool":                {"cmd": "SnippingTool.exe",                     "type": "exe",      "name": "Snipping Tool"},
    "snipping tool delay mode":     {"cmd": "SnippingTool.exe",                     "type": "exe",      "name": "Snipping Tool"},
    "snippingtool":                 {"cmd": "SnippingTool.exe",                     "type": "exe",      "name": "Snipping Tool"},
    "snip and sketch":              {"cmd": "ms-screensketch:",                     "type": "protocol", "name": "Snip & Sketch"},
    "wsl":                          {"cmd": "wsl.exe",                              "type": "exe",      "name": "Windows Subsystem for Linux"},
    "windows subsystem for linux":  {"cmd": "wsl.exe",                              "type": "exe",      "name": "WSL"},
    "optionalfeatures":             {"cmd": "optionalfeatures.exe",                 "type": "exe",      "name": "Windows Features"},
    "optional features":            {"cmd": "optionalfeatures.exe",                 "type": "exe",      "name": "Windows Features"},
    "windows features":             {"cmd": "optionalfeatures.exe",                 "type": "exe",      "name": "Windows Features"},
    "turn windows features on off": {"cmd": "optionalfeatures.exe",                 "type": "exe",      "name": "Windows Features"},
    "turn windows features on or off": {"cmd": "optionalfeatures.exe",              "type": "exe",      "name": "Windows Features"},
    "credential manager":           {"cmd": "control.exe /name Microsoft.CredentialManager", "type": "control", "name": "Credential Manager"},
    "odbc data sources":            {"cmd": "odbcad32.exe",                         "type": "exe",      "name": "ODBC Data Sources"},
    "odbc":                         {"cmd": "odbcad32.exe",                         "type": "exe",      "name": "ODBC Data Sources"},
    "odbcad32":                     {"cmd": "odbcad32.exe",                         "type": "exe",      "name": "ODBC Data Sources"},
    "remote desktop":               {"cmd": "mstsc.exe",                            "type": "exe",      "name": "Remote Desktop"},
    "mstsc":                        {"cmd": "mstsc.exe",                            "type": "exe",      "name": "Remote Desktop"},
    "windows sandbox":              {"cmd": "WindowsSandbox.exe",                   "type": "exe",      "name": "Windows Sandbox"},

    # ── Control Panel (.cpl) ─────────────────────────────────────────────────
    "programs and features":  {"cmd": "appwiz.cpl",          "type": "cpl", "name": "Programs and Features"},
    "add remove programs":    {"cmd": "appwiz.cpl",          "type": "cpl", "name": "Programs and Features"},
    "appwiz.cpl":             {"cmd": "appwiz.cpl",          "type": "cpl", "name": "Programs and Features"},
    "network connections":    {"cmd": "ncpa.cpl",            "type": "cpl", "name": "Network Connections"},
    "network adapters":       {"cmd": "ncpa.cpl",            "type": "cpl", "name": "Network Connections"},
    "ncpa.cpl":               {"cmd": "ncpa.cpl",            "type": "cpl", "name": "Network Connections"},
    "power options":          {"cmd": "powercfg.cpl",        "type": "cpl", "name": "Power Options"},
    "power plan":             {"cmd": "powercfg.cpl",        "type": "cpl", "name": "Power Options"},
    "power plan advanced settings": {"cmd": "powercfg.cpl", "type": "cpl", "name": "Power Options"},
    "powercfg.cpl":           {"cmd": "powercfg.cpl",        "type": "cpl", "name": "Power Options"},
    "internet options":       {"cmd": "inetcpl.cpl",         "type": "cpl", "name": "Internet Properties"},
    "inetcpl.cpl":            {"cmd": "inetcpl.cpl",         "type": "cpl", "name": "Internet Properties"},
    "windows firewall":       {"cmd": "firewall.cpl",        "type": "cpl", "name": "Windows Firewall"},
    "firewall.cpl":           {"cmd": "firewall.cpl",        "type": "cpl", "name": "Windows Firewall"},
    "sounds":                 {"cmd": "mmsys.cpl sounds",    "type": "cpl", "name": "Sound Settings"},
    "sound settings":         {"cmd": "mmsys.cpl sounds",    "type": "cpl", "name": "Sound Settings"},
    "mmsys.cpl":              {"cmd": "mmsys.cpl",           "type": "cpl", "name": "Sound"},
    "date time":              {"cmd": "timedate.cpl",        "type": "cpl", "name": "Date and Time"},
    "date and time":          {"cmd": "timedate.cpl",        "type": "cpl", "name": "Date and Time"},
    "timedate.cpl":           {"cmd": "timedate.cpl",        "type": "cpl", "name": "Date and Time"},
    "mouse settings":         {"cmd": "main.cpl",            "type": "cpl", "name": "Mouse Properties"},
    "mouse properties":       {"cmd": "main.cpl",            "type": "cpl", "name": "Mouse Properties"},
    "sysdm.cpl":              {"cmd": "sysdm.cpl",           "type": "cpl", "name": "System Properties"},
    "display settings":       {"cmd": "ms-settings:display", "type": "protocol", "name": "Display Settings"},
    "screen resolution":      {"cmd": "ms-settings:display", "type": "protocol", "name": "Display Settings"},

    # ── Troubleshooting / admin ──────────────────────────────────────────────
    "task manager":                 {"cmd": "taskmgr.exe",                    "type": "exe",      "name": "Task Manager"},
    "taskmgr":                      {"cmd": "taskmgr.exe",                    "type": "exe",      "name": "Task Manager"},
    "create restore point":         {"cmd": "systempropertiesprotection.exe", "type": "exe",      "name": "System Protection"},
    "restore point":                {"cmd": "systempropertiesprotection.exe", "type": "exe",      "name": "System Protection"},
    "system restore":               {"cmd": "rstrui.exe",                     "type": "exe",      "name": "System Restore"},
    "rstrui":                       {"cmd": "rstrui.exe",                     "type": "exe",      "name": "System Restore"},
    "system image backup":          {"cmd": "sdclt.exe",                      "type": "exe",      "name": "Backup and Restore"},
    "backup":                       {"cmd": "sdclt.exe",                      "type": "exe",      "name": "Backup and Restore"},
    "sdclt":                        {"cmd": "sdclt.exe",                      "type": "exe",      "name": "Backup and Restore"},
    "change uac level":             {"cmd": "useraccountcontrolsettings.exe", "type": "exe",      "name": "UAC Settings"},
    "uac settings":                 {"cmd": "useraccountcontrolsettings.exe", "type": "exe",      "name": "UAC Settings"},
    "user account control":         {"cmd": "useraccountcontrolsettings.exe", "type": "exe",      "name": "UAC Settings"},
    "device installation settings": {"cmd": "ms-settings:devices",            "type": "protocol", "name": "Device Settings"},
    "startup apps advanced":        {"cmd": "ms-settings:startupapps",        "type": "protocol", "name": "Startup Apps"},
    "startup applications":         {"cmd": "ms-settings:startupapps",        "type": "protocol", "name": "Startup Apps"},
    "network reset":                {"cmd": "ms-settings:network-status",     "type": "protocol", "name": "Network Status"},
    "bitlocker management":         {"cmd": "ms-settings:deviceencryption",   "type": "protocol", "name": "BitLocker"},
    "bitlocker":                    {"cmd": "ms-settings:deviceencryption",   "type": "protocol", "name": "BitLocker"},
    "storage sense":                {"cmd": "ms-settings:storagepolicies",    "type": "protocol", "name": "Storage Sense"},
    "clipboard history":            {"cmd": "ms-settings:clipboard",          "type": "protocol", "name": "Clipboard"},
    "voice typing":                 {"cmd": "ms-settings:speech",             "type": "protocol", "name": "Voice Typing / Speech"},
    "emoji panel":                  {"cmd": "ms-settings:easeofaccess-speechrecognition", "type": "protocol", "name": "Emoji Panel (Win+.)"},
    "windows update":               {"cmd": "ms-settings:windowsupdate",      "type": "protocol", "name": "Windows Update"},

    # ── Network / DNS ────────────────────────────────────────────────────────
    "flush dns":       {"cmd": "ipconfig /flushdns",  "type": "netsh_cmd", "name": "Flush DNS Cache",   "run_as_admin": True},
    "clear dns cache": {"cmd": "ipconfig /flushdns",  "type": "netsh_cmd", "name": "Clear DNS Cache",   "run_as_admin": True},
    "dns cache":       {"cmd": "ipconfig /flushdns",  "type": "netsh_cmd", "name": "DNS Cache",         "run_as_admin": True},
    "edit hosts file": {"cmd": r"notepad C:\Windows\System32\drivers\etc\hosts", "type": "open_file", "name": "Hosts File"},
    "hosts file":      {"cmd": r"notepad C:\Windows\System32\drivers\etc\hosts", "type": "open_file", "name": "Hosts File"},
    "change mac address": {"cmd": "ncpa.cpl",         "type": "cpl",       "name": "Network Connections"},
    "ipconfig":        {"cmd": "cmd /k ipconfig",     "type": "cmd_args",  "name": "ipconfig"},

    # ── Special folders / GUIDs ──────────────────────────────────────────────
    "god mode":  {"cmd": r"explorer.exe shell:::{ED7BA470-8E54-465E-825C-99712043E01C}", "type": "shell_guid", "name": "God Mode"},
    "godmode":   {"cmd": r"explorer.exe shell:::{ED7BA470-8E54-465E-825C-99712043E01C}", "type": "shell_guid", "name": "God Mode"},
    "all tasks": {"cmd": r"explorer.exe shell:::{ED7BA470-8E54-465E-825C-99712043E01C}", "type": "shell_guid", "name": "God Mode"},

    # ── Common built-ins ─────────────────────────────────────────────────────
    "notepad":          {"cmd": "notepad.exe",    "type": "exe", "name": "Notepad"},
    "paint":            {"cmd": "mspaint.exe",    "type": "exe", "name": "Paint"},
    "wordpad":          {"cmd": "wordpad.exe",    "type": "exe", "name": "WordPad"},
    "cmd":              {"cmd": "cmd.exe",        "type": "exe", "name": "Command Prompt"},
    "command prompt":   {"cmd": "cmd.exe",        "type": "exe", "name": "Command Prompt"},
    "powershell":       {"cmd": "powershell.exe", "type": "exe", "name": "PowerShell"},
    "windows terminal": {"cmd": "wt.exe",         "type": "exe", "name": "Windows Terminal"},
    "terminal":         {"cmd": "wt.exe",         "type": "exe", "name": "Windows Terminal"},
    "file explorer":    {"cmd": "explorer.exe",   "type": "exe", "name": "File Explorer"},
    "explorer":         {"cmd": "explorer.exe",   "type": "exe", "name": "File Explorer"},
    "control panel":    {"cmd": "control.exe",    "type": "exe", "name": "Control Panel"},
    "magnifier":        {"cmd": "magnify.exe",    "type": "exe", "name": "Magnifier"},
    "on screen keyboard": {"cmd": "osk.exe",      "type": "exe", "name": "On-Screen Keyboard"},
    "osk":              {"cmd": "osk.exe",        "type": "exe", "name": "On-Screen Keyboard"},
    "narrator":         {"cmd": "narrator.exe",   "type": "exe", "name": "Narrator"},
    "sticky notes":     {"cmd": "stikynot.exe",   "type": "exe", "name": "Sticky Notes"},
    "xbox game bar":    {"cmd": "ms-gamebar:",    "type": "protocol", "name": "Xbox Game Bar"},
    "paint 3d":         {"cmd": "ms-paint:",      "type": "protocol", "name": "Paint 3D"},
}

# System exe names that should NEVER fall back to the web
_SYSTEM_APP_INDICATORS = {
    ".msc", ".cpl", "ms-settings:", "shell:", "microsoft.windows.",
    "regedit", "taskmgr", "explorer", "powershell", "cmd.exe",
    "control.exe", "rundll32", "mmc.exe", "wsl",
}

# Minimum score a cache hit must reach to be returned.
# Prevents fuzzy-char false positives (e.g. "aws" → "Tailwind-CSS").
_MIN_CACHE_SCORE = 60.0  # requires at least word-boundary or substring match

# Windows Recent folder path fragment — .lnk files here have garbage names
_WIN_RECENT_PATH_FRAGMENT = os.path.join("Windows", "Recent")


# ══════════════════════════════════════════════════════════════════════════════
#  AppSearcher
# ══════════════════════════════════════════════════════════════════════════════
class AppSearcher:
    """
    Deep, cross-platform application searcher with built-in web fallback.

    Resolution order
    ────────────────
    1. ms-settings / shell: protocol pass-through
    2. Natural-language command map (Windows power tools)
    3. System-installed app cache (UWP, registry, Start-Menu, PATH, deep scan)
    4. Web fallback via KNOWN_WEBSITES → only for non-system queries
    """

    # Executables that are containers/hosts, not real apps
    _EXE_BLACKLIST = {
        "camerasettingsuihost.exe", "systemsettings.exe",
        "applicationframehost.exe", "runtimebroker.exe",
        "searchui.exe", "shellexperiencehost.exe",
        "startmenuexperiencehost.exe", "sihost.exe",
        "ctfmon.exe", "conhost.exe", "dllhost.exe",
    }

    def __init__(self):
        self._os           = sys.platform
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._stamp        = 0.0
        self._ttl          = 300  # 5 min cache
        self._icon_resolver = IconResolver(use_fallback=False)

    # ─────────────────────────────────────────────────────────────────────────
    #  Public API
    # ─────────────────────────────────────────────────────────────────────────
    def find_app(self, query: str, include_icon: bool = True) -> Optional[Dict[str, Any]]:
        """
        Search for *any* app — system, UWP, or web.

        Returns a dict:
            {
                "name":          str,
                "path":          str,   ← cmd / protocol / URL / file path
                "type":          str,   ← msc | exe | cpl | protocol | uwp |
                                           uwp_shell | rundll32 | cmd_args |
                                           netsh_cmd | open_file | shell_guid |
                                           website | url
                "launch_method": str,   ← run | shell | browser | cmd
                "source":        str,   ← protocol | nlmap | cache | web
                "icon_b64":      str | None  ← base64 PNG  (system apps)
                "icon_url":      str | None  ← favicon URL (websites)
            }
        """
        q = query.strip()
        ql = q.lower()

        logger.info("[AppSearcher] query='%s' os=%s", q, self._os)

        # ── Step 1: Protocol pass-through ────────────────────────────────────
        _is_explicit_protocol = (
            ql.startswith("ms-settings:")
            or ql.startswith("shell:")
            or ql.startswith("microsoft.windows.")
            or ql.endswith(":")
        )
        if ql in PROTOCOL_HANDLERS:
            p = PROTOCOL_HANDLERS[ql]
            r = self._make_result(name=q, path=p, rtype="protocol",
                                  launch="shell", source="protocol")
            return self._attach_icon(r, include_icon)
        if _is_explicit_protocol:
            r = self._make_result(name=q, path=ql, rtype="protocol",
                                  launch="shell", source="protocol")
            return self._attach_icon(r, include_icon)
        if self._os == "win32" and ql in PROTOCOL_HANDLERS:
            p = PROTOCOL_HANDLERS[ql]
            r = self._make_result(name=q, path=p, rtype="protocol",
                                  launch="shell", source="protocol")
            return self._attach_icon(r, include_icon)

        # ── Step 2: Natural-language map ─────────────────────────────────────
        _is_win_command = any(ql.endswith(s) for s in (".msc", ".exe", ".cpl", ".bat"))
        if self._os == "win32" or _is_win_command:
            hit = NATURAL_LANGUAGE_MAP.get(ql)
            if hit:
                r = self._make_result(
                    name=hit.get("name", q),
                    path=hit["cmd"],
                    rtype=hit["type"],
                    launch=self._infer_launch(hit["type"]),
                    source="nlmap",
                    extra={k: v for k, v in hit.items()
                           if k not in ("cmd", "type", "name")},
                )
                return self._attach_icon(r, include_icon)
        if self._os == "win32":
            hit = NATURAL_LANGUAGE_MAP.get(ql)
            if hit:
                r = self._make_result(
                    name=hit.get("name", q),
                    path=hit["cmd"],
                    rtype=hit["type"],
                    launch=self._infer_launch(hit["type"]),
                    source="nlmap",
                    extra={k: v for k, v in hit.items()
                           if k not in ("cmd", "type", "name")},
                )
                return self._attach_icon(r, include_icon)

        # ── Step 3: KNOWN_WEBSITES exact match — BEFORE cache ────────────────
        if ql in KNOWN_WEBSITES:
            r = self._make_result(
                name=q, path=KNOWN_WEBSITES[ql],
                rtype="website", launch="browser", source="web",
            )
            return self._attach_icon(r, include_icon)

        # ── Step 3.5: Fuzzy search over the maps themselves ───────────────────
        # Handles: "bluetooth" → ms-settings:bluetooth
        #          "wifi"      → ms-settings:network-wifi
        #          "privacy mic" → ms-settings:privacy-microphone
        #          "event log"   → eventvwr.msc   (synonym not in exact map)
        # This is PURELY dynamic — no hardcoding — just scoring every key
        # in PROTOCOL_HANDLERS and NATURAL_LANGUAGE_MAP against the query.
        map_hit = self._fuzzy_search_maps(ql)
        if map_hit:
            return self._attach_icon(map_hit, include_icon)

        # ── Step 4: Cached / scanned apps ────────────────────────────────────
        self._ensure_cache()
        matches = self._fuzzy_search(ql)

        if matches:
            best_path, score, info = max(matches, key=lambda x: x[1])
            # Hard minimum: never return a weak fuzzy match
            if score >= _MIN_CACHE_SCORE:
                logger.info("[AppSearcher] cache hit: %s (score=%.1f)", best_path, score)
                result = self._make_result(
                    name=info.get("name", ql),
                    path=best_path,
                    rtype=info.get("type", "app"),
                    launch=self._infer_launch(info.get("type", "app")),
                    source="cache",
                )
                return self._attach_icon(result, include_icon)

        # ── Step 5: Web fallback (only for clearly non-system queries) ────────
        if not self._looks_like_system_query(ql):
            result = self._web_resolve(q, ql)
            if result:
                return self._attach_icon(result, include_icon)

        logger.info("[AppSearcher] no result for '%s'", q)
        return None

    # ─────────────────────────────────────────────────────────────────────────
    #  Cache management
    # ─────────────────────────────────────────────────────────────────────────
    def _ensure_cache(self):
        if time.time() - self._stamp < self._ttl:
            return
        logger.info("[AppSearcher] refreshing cache …")
        self._cache.clear()
        if self._os == "win32":
            self._scan_windows()
        elif self._os == "darwin":
            self._scan_macos()
        else:
            self._scan_linux()
        self._stamp = time.time()
        logger.info("[AppSearcher] cache ready: %d apps", len(self._cache))

    # ── Windows ──────────────────────────────────────────────────────────────
    def _scan_windows(self):
        # NOTE: AppData\Roaming\Microsoft\Windows\Recent is intentionally
        # excluded — it contains .lnk shortcuts to every file ever opened,
        # with full garbage filenames (URLs, video titles, etc.) that pollute
        # the search cache and cause wrong matches.
        with ThreadPoolExecutor(max_workers=6) as ex:
            futures = [
                ex.submit(self._win_store_apps),
                ex.submit(self._win_registry_apps),
                ex.submit(self._win_path_executables),
                # Start Menu shortcuts — CLEAN .lnk names only
                ex.submit(self._scan_dir,
                          os.path.join(os.environ.get("PROGRAMDATA", ""),
                                       "Microsoft", "Windows", "Start Menu", "Programs"),
                          [".lnk"], 4),
                ex.submit(self._scan_dir,
                          os.path.join(Path.home(), "AppData", "Roaming", "Microsoft",
                                       "Windows", "Start Menu", "Programs"),
                          [".lnk"], 4),
                ex.submit(self._scan_dir,
                          os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                          [".exe"], 4),
                ex.submit(self._scan_dir,
                          os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                          [".exe"], 4),
                # Local\Programs — only .exe (no .lnk to avoid pollution)
                ex.submit(self._scan_dir,
                          os.path.join(Path.home(), "AppData", "Local", "Programs"),
                          [".exe"], 4),
                ex.submit(self._scan_dir,
                          os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32"),
                          [".exe", ".msc", ".cpl"], 2),
                ex.submit(self._scan_dir,
                          os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "SysWOW64"),
                          [".exe", ".msc", ".cpl"], 2),
                # AppData subdirs — only .exe, never .lnk (avoids Recent pollution)
                ex.submit(self._scan_dir,
                          os.path.join(Path.home(), "AppData", "Local"),
                          [".exe"], 3),
                ex.submit(self._scan_dir,
                          os.path.join(Path.home(), "AppData", "Roaming"),
                          [".exe"], 3),
            ]
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    logger.debug("[AppSearcher] scan error: %s", e)

    def _win_store_apps(self):
        """Query UWP / MSIX packages via PowerShell."""
        try:
            ps = (
                "Get-AppxPackage | ForEach-Object {"
                "  $_.Name + '|' + $_.PackageFamilyName"
                "}"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode != 0:
                return
            for line in r.stdout.splitlines():
                if "|" not in line:
                    continue
                name, fam = line.strip().split("|", 1)
                clean = name.split(".")[-1]
                app_id = rf"shell:AppsFolder\{fam}!App"
                self._add_to_cache(clean, app_id, "uwp_shell", clean)
        except Exception as e:
            logger.debug("[AppSearcher] store scan: %s", e)

    def _win_registry_apps(self):
        """Read installed apps from Uninstall registry keys."""
        import winreg  # only importable on Windows

        keys = [
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for hive, subkey in keys:
            try:
                key = winreg.OpenKey(hive, subkey)
                i = 0
                while True:
                    try:
                        sub_name = winreg.EnumKey(key, i)
                        sub_key  = winreg.OpenKey(key, sub_name)
                        try:
                            name = winreg.QueryValueEx(sub_key, "DisplayName")[0]
                            exe  = winreg.QueryValueEx(sub_key, "InstallLocation")[0]
                            if name and exe and os.path.isdir(exe):
                                # Try to find main exe in install dir
                                for f in os.listdir(exe):
                                    if f.lower().endswith(".exe") and f.lower() not in self._EXE_BLACKLIST:
                                        fp = os.path.join(exe, f)
                                        self._add_to_cache(name, fp, "exe", name)
                                        break
                        except FileNotFoundError:
                            pass
                        finally:
                            winreg.CloseKey(sub_key)
                        i += 1
                    except OSError:
                        break
                winreg.CloseKey(key)
            except Exception:
                pass

    def _win_path_executables(self):
        """Scan every directory in PATH for executables."""
        for p in os.environ.get("PATH", "").split(os.pathsep):
            if p and os.path.isdir(p):
                self._scan_dir(p, [".exe", ".msc", ".cpl", ".bat", ".cmd"], max_depth=1)

    # ── macOS ────────────────────────────────────────────────────────────────
    def _scan_macos(self):
        try:
            r = subprocess.run(
                ["mdfind", "kMDItemContentTypeTree=com.apple.application-bundle"],
                capture_output=True, text=True, timeout=8,
            )
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    if line.endswith(".app"):
                        n = os.path.basename(line).removesuffix(".app")
                        self._add_to_cache(n, line, "app", n)
                return
        except Exception:
            pass
        # Fallback: manual
        for base in ["/Applications", "/System/Applications",
                     str(Path.home() / "Applications"),
                     "/System/Library/CoreServices"]:
            self._scan_dir(base, [".app"], max_depth=3)

    # ── Linux ────────────────────────────────────────────────────────────────
    def _scan_linux(self):
        desktop_dirs = [
            "/usr/share/applications",
            "/usr/local/share/applications",
            str(Path.home() / ".local/share/applications"),
            "/var/lib/flatpak/exports/share/applications",
            str(Path.home() / ".local/share/flatpak/exports/share/applications"),
            "/var/lib/snapd/desktop/applications",
        ]
        bin_dirs = ["/usr/bin", "/usr/local/bin", "/bin", "/usr/sbin",
                    str(Path.home() / ".local/bin")]
        for d in desktop_dirs:
            self._scan_dir(d, [".desktop"], max_depth=2)
        for d in bin_dirs:
            self._scan_dir(d, [], max_depth=1)  # empty = executables

    # ── Generic directory scanner ────────────────────────────────────────────
    def _scan_dir(self, path: str, extensions: List[str], max_depth: int = 2):
        if not os.path.exists(path):
            return
        # Never index the Windows Recent folder — .lnk names there are garbage
        # (full URLs, video titles, ms-actioncenter strings, etc.)
        _recent_marker = os.path.join("Microsoft", "Windows", "Recent")
        if _recent_marker in path:
            return
        try:
            for root, dirs, files in os.walk(path, followlinks=False):
                depth = root[len(path):].count(os.sep)
                if depth >= max_depth:
                    dirs[:] = []
                    continue
                # Prune any "Recent" sub-directory encountered mid-walk
                dirs[:] = [
                    d for d in dirs
                    if not (d.lower() == "recent" and "microsoft" in root.lower())
                ]
                for fname in files:
                    if extensions:
                        if not any(fname.lower().endswith(e) for e in extensions):
                            continue
                    elif not os.access(os.path.join(root, fname), os.X_OK):
                        continue
                    if fname.lower() in self._EXE_BLACKLIST:
                        continue
                    # Skip .lnk files with clearly garbage names (URL shortcuts,
                    # file-open history entries). Real Start Menu shortcuts are short.
                    if fname.lower().endswith(".lnk") and len(fname) > 80:
                        continue
                    clean = fname
                    for ext in (".exe", ".lnk", ".app", ".desktop", ".msc", ".cpl", ".bat", ".cmd"):
                        clean = clean.replace(ext, "").replace(ext.upper(), "")
                    ftype = "exe"
                    if fname.endswith(".msc"):
                        ftype = "msc"
                    elif fname.endswith(".cpl"):
                        ftype = "cpl"
                    elif fname.endswith(".lnk"):
                        ftype = "lnk"
                    elif fname.endswith(".app"):
                        ftype = "app"
                    elif fname.endswith(".desktop"):
                        ftype = "desktop"
                    self._add_to_cache(clean, os.path.join(root, fname), ftype, clean)
        except PermissionError:
            pass
        except Exception as e:
            logger.debug("[AppSearcher] scan_dir %s: %s", path, e)

    # ─────────────────────────────────────────────────────────────────────────
    #  Map fuzzy search  (NL map + protocol handlers, no hardcoding)
    # ─────────────────────────────────────────────────────────────────────────
    def _fuzzy_search_maps(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Fuzzy-score the query against every key in NATURAL_LANGUAGE_MAP and
        PROTOCOL_HANDLERS.  Returns the best match above threshold, or None.

        Scoring targets:
          • Full key         "ms-settings:bluetooth"  → try matching "bluetooth"
          • Key leaf         the word(s) after last ':' or '-' separator
          • NL name field    "Bluetooth"  from the name value in the NL map

        This is what makes "bluetooth" resolve to ms-settings:bluetooth,
        "wifi" to ms-settings:network-wifi, "privacy mic" to
        ms-settings:privacy-microphone, "dns" to ipconfig /flushdns, etc.
        — without a single hardcoded alias.
        """
        _MIN = 60.0   # same threshold as cache search
        best_score = 0.0
        best_result: Optional[Dict[str, Any]] = None

        # ── Score NATURAL_LANGUAGE_MAP ────────────────────────────────────────
        for map_key, hit in NATURAL_LANGUAGE_MAP.items():
            score = self._score_map_key(query, map_key, hit.get("name", ""))
            if score > best_score:
                best_score = score
                best_result = self._make_result(
                    name=hit.get("name", map_key),
                    path=hit["cmd"],
                    rtype=hit["type"],
                    launch=self._infer_launch(hit["type"]),
                    source="nlmap_fuzzy",
                    extra={k: v for k, v in hit.items()
                           if k not in ("cmd", "type", "name")},
                )

        # ── Score PROTOCOL_HANDLERS ───────────────────────────────────────────
        for map_key, protocol_val in PROTOCOL_HANDLERS.items():
            # Use the key itself as the "name" for protocols
            # e.g. key = "ms-settings:bluetooth", name_hint = "bluetooth"
            name_hint = map_key.split(":")[-1].replace("-", " ").strip()
            score = self._score_map_key(query, map_key, name_hint)
            if score > best_score:
                best_score = score
                best_result = self._make_result(
                    name=name_hint.title() or map_key,
                    path=protocol_val,
                    rtype="protocol",
                    launch="shell",
                    source="protocol_fuzzy",
                )

        if best_score >= _MIN:
            logger.info(
                "[AppSearcher] map fuzzy hit for '%s': %s (score=%.1f)",
                query, best_result.get("path") if best_result else "?", best_score,
            )
            return best_result
        return None

    @staticmethod
    def _score_map_key(query: str, key: str, name: str) -> float:
        """
        Score a query against a map key like "ms-settings:bluetooth" or
        "event viewer", using several targets:

          1. query vs full key            ("bluetooth" in "ms-settings:bluetooth")
          2. query vs key leaf            ("bluetooth" == "bluetooth")
          3. query vs all space/colon/dash tokens in the key
          4. query vs human name field    ("bluetooth" in "Bluetooth")
          5. ALL query words match SOME token in the key (multi-word queries)

        Returns 0.0 if no confident match.
        """
        q   = query.lower().strip()
        k   = key.lower()
        n   = name.lower()

        if not q:
            return 0.0

        # Tokenise the key into meaningful parts
        # "ms-settings:network-wifi" → ["ms", "settings", "network", "wifi"]
        import re as _re
        tokens = [t for t in _re.split(r"[:\-\s_]+", k) if t]

        score = 0.0

        # ── Tier 1: exact token match (leaf = last token) ─────────────────────
        if q == tokens[-1]:                   score = max(score, 95.0)
        elif q == n:                          score = max(score, 95.0)

        # ── Tier 2: exact match against any token ─────────────────────────────
        elif q in tokens:                     score = max(score, 88.0)

        # ── Tier 3: substring inside the leaf or name ─────────────────────────
        if tokens and q in tokens[-1]:        score = max(score, 80.0)
        if q in n:                            score = max(score, 75.0)

        # ── Tier 4: substring of any token ───────────────────────────────────
        if any(q in t for t in tokens):       score = max(score, 70.0)

        # ── Tier 5: any token starts with query ──────────────────────────────
        if any(t.startswith(q) for t in tokens): score = max(score, 65.0)

        # ── Tier 6: multi-word query — ALL words must hit SOME token ─────────
        q_words = q.split()
        if len(q_words) > 1:
            # Every word in the query must be found somewhere in tokens or name
            all_match = all(
                any(w in t for t in tokens) or w in n
                for w in q_words
            )
            if all_match:
                score = max(score, 72.0)

        # ── Penalty: prefer shorter / more specific keys ─────────────────────
        if score > 0:
            score -= len(k) / 300.0

        return score

    # ─────────────────────────────────────────────────────────────────────────
    #  Fuzzy search (cache)
    # ─────────────────────────────────────────────────────────────────────────
    def _fuzzy_search(self, query: str) -> List[Tuple[str, float, Dict]]:
        results = []
        for key, info in self._cache.items():
            score = self._score(query, key, info.get("name", key))
            if score >= _MIN_CACHE_SCORE:
                results.append((info["path"], score, info))
        return results

    def _score(self, query: str, key: str, name: str) -> float:
        """
        Score a cache entry against the query.

        Tier  Score   Condition
        ────  ─────   ─────────────────────────────────────────────────────
          1   100     Exact key match
          2    90     Key *starts with* query
          3    75     Query appears as a *substring* inside key
          4    60     Any word in key *starts with* query (word boundary)
          5    --     Fuzzy char match DISABLED — too many false positives
                      (e.g. "aws" matching "Tailwind-CSS",
                             "claude" matching long video filenames)

        A length penalty (len(key)/200) is subtracted so shorter, more
        specific names rank above longer ones at the same tier.

        .lnk files from non-Start-Menu paths are penalised by −20 so a
        real exe/msc always wins over a shortcut file.
        """
        k = key.lower()
        q = query.lower()

        # Guard: empty query or impossibly short ratio
        if not q or len(q) < 2:
            return 0.0

        score = 0.0

        if q == k:
            score = 100.0
        elif k.startswith(q):
            score = 90.0
        elif q in k:
            score = 75.0
        elif any(w.startswith(q) for w in k.split()):
            score = 60.0
        else:
            # No match — skip fuzzy char (intentionally removed)
            return 0.0

        # Length penalty: prefer shorter/more specific names
        score -= len(k) / 200.0

        # Penalise .lnk shortcuts — prefer real executables / MSC / CPL
        if name.lower().endswith(".lnk"):
            score -= 20.0

        return max(score, 0.0)

    # ─────────────────────────────────────────────────────────────────────────
    #  Web fallback (built-in AppResolver logic)
    # ─────────────────────────────────────────────────────────────────────────
    def _web_resolve(self, original: str, ql: str) -> Optional[Dict[str, Any]]:
        # 1. Known website shortcut
        if ql in KNOWN_WEBSITES:
            url = KNOWN_WEBSITES[ql]
            return self._make_result(name=original, path=url,
                                     rtype="website", launch="browser", source="web")
        # 2. Already a URL
        if self._is_url(original):
            return self._make_result(name=original, path=original,
                                     rtype="url", launch="browser", source="web")
        # 3. Looks like a domain
        if self._is_domain(original):
            url = original if original.startswith("http") else f"https://{original}"
            return self._make_result(name=original, path=url,
                                     rtype="url", launch="browser", source="web")
        # 4. Fallback → .com
        url = f"https://{ql.replace(' ', '')}.com"
        return self._make_result(name=original, path=url,
                                 rtype="website", launch="browser", source="web_fallback")

    @staticmethod
    def _is_url(text: str) -> bool:
        try:
            r = urlparse(text)
            return bool(r.scheme and r.netloc)
        except Exception:
            return False

    @staticmethod
    def _is_domain(text: str) -> bool:
        if " " in text or "." not in text:
            return False
        tlds = (".com", ".org", ".net", ".io", ".ai", ".dev", ".app",
                ".co", ".tv", ".me", ".so", ".gg", ".xyz", ".uk", ".us")
        return any(text.lower().endswith(t) for t in tlds) or text.count(".") >= 2

    @staticmethod
    def _looks_like_system_query(ql: str) -> bool:
        for indicator in _SYSTEM_APP_INDICATORS:
            if indicator in ql:
                return True
        return False

    # ─────────────────────────────────────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────────────────────────────────────
    def _attach_icon(self, result: Dict[str, Any], include_icon: bool) -> Dict[str, Any]:
        """
        Add icon information to a result dict.

        For system apps:
            result["icon_b64"] = "<base64 PNG string>"  # or None

        For websites:
            result["icon_url"] = "https://www.google.com/s2/favicons?..."

        Icon resolution is skipped entirely when include_icon=False (fast path).
        """
        result["icon_b64"] = None
        result["icon_url"] = None

        if not include_icon:
            return result

        raw = self._icon_resolver.get_icon(result)

        if raw and raw.startswith("url:"):
            # Favicon URL returned by the resolver for websites
            result["icon_url"] = raw[4:]   # strip "url:" prefix
        else:
            result["icon_b64"] = raw       # base64 PNG or None

        return result

    def _add_to_cache(self, key: str, path: str, ftype: str, name: str):
        k = key.lower().strip()
        if k and k not in self._cache:
            self._cache[k] = {"path": path, "type": ftype, "name": name}

    @staticmethod
    def _infer_launch(ftype: str) -> str:
        mapping = {
            "msc":       "run",
            "cpl":       "run",
            "exe":       "run",
            "lnk":       "shell",
            "app":       "shell",
            "uwp_shell": "shell",
            "protocol":  "shell",
            "rundll32":  "run",
            "cmd_args":  "run",
            "netsh_cmd": "run_admin",
            "open_file": "run",
            "shell_guid":"run",
            "website":   "browser",
            "url":       "browser",
        }
        return mapping.get(ftype, "run")

    @staticmethod
    def _make_result(*, name: str, path: str, rtype: str,
                     launch: str, source: str,
                     extra: Optional[Dict] = None) -> Dict[str, Any]:
        r: Dict[str, Any] = {
            "name":          name,
            "path":          path,
            "type":          rtype,
            "launch_method": launch,
            "source":        source,
        }
        if extra:
            r.update(extra)
        return r

    # ─────────────────────────────────────────────────────────────────────────
    #  Debug helpers
    # ─────────────────────────────────────────────────────────────────────────
    def get_all_apps(self) -> List[Dict[str, str]]:
        self._ensure_cache()
        return [{"name": v["name"], "path": v["path"]} for v in self._cache.values()]

    def add_website(self, name: str, url: str):
        """Dynamically add a custom website shortcut."""
        KNOWN_WEBSITES[name.lower()] = url
        logger.info("[AppSearcher] added custom site: %s → %s", name, url)