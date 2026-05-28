# Browser Agent vs Native MusicPlayTool - Integration Strategy

## 🎵 Current State

### Native MusicPlayTool (Existing)
**Location:** `server/plugins/installed/media/tools/music.py`

**What it does:**
- Plays music via **mpv + yt-dlp** (no browser)
- Streams YouTube/SoundCloud audio in background
- Plays local audio files
- **Headless** - no UI, just audio

**Advantages:**
- ✅ Faster (no browser needed)
- ✅ Lighter (audio only, no video)
- ✅ Background playback
- ✅ Works without browser open

**Disadvantages:**
- ❌ Audio only (no video)
- ❌ No visual feedback
- ❌ Can't interact with YouTube UI
- ❌ Requires mpv + yt-dlp installed

---

### Browser Agent YouTubeAdapter (New)
**Location:** `server/plugins/installed/web/browser/adapters/youtube.py`

**What it does:**
- Opens YouTube in **user's browser**
- Searches and clicks video
- Full visual experience

**Advantages:**
- ✅ Visual feedback (see video playing)
- ✅ Can interact with UI (like, comment, playlist)
- ✅ Uses existing browser session
- ✅ No external dependencies

**Disadvantages:**
- ❌ Slower (browser automation)
- ❌ Requires browser open
- ❌ Video + audio (heavier)
- ❌ Not background-friendly

---

## 🎯 Integration Strategy

### Option 1: Keep Both, Let LLM Choose (RECOMMENDED)

**Decision Logic:**
```python
if user_wants_background_music:
    use MusicPlayTool  # Fast, headless, audio-only
elif user_wants_to_watch_video:
    use BrowserAgentTool  # Visual, interactive
else:
    use MusicPlayTool  # Default to faster option
```

**Implementation:**
```python
# LLM tool selection based on user intent

# "play some music" → MusicPlayTool
# "play lofi beats" → MusicPlayTool
# "play music in background" → MusicPlayTool

# "watch lofi beats video" → BrowserAgentTool
# "show me lofi beats on youtube" → BrowserAgentTool
# "open lofi beats video" → BrowserAgentTool
```

**Tool Descriptions (for LLM):**
```python
# MusicPlayTool
TOOL_DESCRIPTION = "Play music/audio in background via mpv. Fast, headless, audio-only. Use when user wants to LISTEN to music."

# BrowserAgentTool (youtube_play)
TOOL_DESCRIPTION = "Open and play video on YouTube in browser. Visual, interactive. Use when user wants to WATCH a video."
```

---

### Option 2: Hierarchical Fallback

**Flow:**
```
User: "play lofi beats"
    ↓
Try MusicPlayTool first (faster)
    ↓
If mpv not installed → Fall back to BrowserAgentTool
    ↓
If browser not available → Fall back to browser_action (URL open)
```

**Implementation:**
```python
async def play_music_smart(title: str):
    # Try 1: Native mpv (fastest)
    try:
        result = await MusicPlayTool()._execute({"title": title})
        if result.success:
            return result
    except:
        pass
    
    # Try 2: Browser automation
    try:
        result = await BrowserAgentTool()._execute({
            "intent": "youtube_play",
            "query": title
        })
        if result.success:
            return result
    except:
        pass
    
    # Try 3: URL open (fallback)
    webbrowser.open(f"https://youtube.com/results?search_query={title}")
```

---

### Option 3: Unified MusicTool (Wrapper)

**Create a smart wrapper:**
```python
class SmartMusicTool(BaseTool):
    """Intelligent music player - chooses best method."""
    
    async def _execute(self, inputs):
        mode = inputs.get("mode", "auto")  # auto, audio, video
        title = inputs.get("title")
        
        if mode == "audio" or (mode == "auto" and self._has_mpv()):
            # Use native player
            return await MusicPlayTool()._execute(inputs)
        
        elif mode == "video" or (mode == "auto" and self._has_browser()):
            # Use browser automation
            return await BrowserAgentTool()._execute({
                "intent": "youtube_play",
                "query": title
            })
        
        else:
            # Fallback to URL open
            return await browser_action(action="play_media", title=title)
```

---

## 📊 Comparison Matrix

| Feature | MusicPlayTool | BrowserAgent | browser_action |
|---------|---------------|--------------|----------------|
| **Speed** | ⚡ Fast | 🐢 Slow | ⚡ Fast |
| **Dependencies** | mpv, yt-dlp | Chrome CDP | None |
| **Visual** | ❌ No | ✅ Yes | ✅ Yes |
| **Background** | ✅ Yes | ❌ No | ❌ No |
| **Interactive** | ❌ No | ✅ Yes | ⚠️ Manual |
| **Audio Quality** | 🎵 High | 🎵 Medium | 🎵 Medium |
| **Resource Usage** | 💚 Low | 🔴 High | 💚 Low |

---

## 🎯 Recommended Approach

### Keep Both Tools, Clear Separation

**MusicPlayTool** - For audio playback
```
Use cases:
- "play some music"
- "play lofi beats"
- "play music in background"
- "play [song name]"
```

**BrowserAgentTool (youtube_play)** - For video watching
```
Use cases:
- "watch lofi beats video"
- "show me [video] on youtube"
- "open [video] on youtube"
- "play [video] on youtube" (if context suggests watching)
```

**browser_action (play_media)** - Fallback
```
Use cases:
- When both above fail
- When user explicitly says "open in browser"
```

---

## 🔧 Implementation Changes Needed

### 1. Update Tool Descriptions (for LLM clarity)

**MusicPlayTool:**
```python
TOOL_DESCRIPTION = """
Play music/audio in background using mpv player. Fast, headless, audio-only streaming.
Use when user wants to LISTEN to music without watching video.
Supports YouTube, SoundCloud, and local files.
"""
```

**BrowserAgentTool:**
```python
# Update youtube_play description
TOOL_DESCRIPTION = """
Automated browser agent for transactional flows.
For YouTube: Opens and plays VIDEO in browser with full visual experience.
Use when user wants to WATCH a video, not just listen to audio.
Also supports: book_hotel, buy_product, reserve_table, etc.
"""
```

### 2. Update browser_action.py play_media Handler

**Current:** Always tries BrowserAgentTool first
**Better:** Check if user wants video or audio

```python
async def _handle_play_media(ctx: BrowserActionContext) -> Dict[str, Any]:
    """Smart delegation based on context."""
    title = ctx.title or ctx.entity.get("name") or ctx.entity.get("title")
    
    # Check if user wants video (from context/entity)
    wants_video = (
        "video" in str(title).lower() or
        "watch" in str(ctx.params.get("context", "")).lower() or
        ctx.entity.get("type") == "video"
    )
    
    if wants_video:
        # Try browser automation for video
        try:
            from ..browser.tool import BrowserAgentTool
            tool = BrowserAgentTool()
            result = await tool._execute({
                "intent": "youtube_play",
                "query": str(title),
                "dry_run": False
            })
            if result.success:
                return {
                    "opened": True,
                    "automated": True,
                    "action": "play_media",
                    "title": str(title),
                    "message": f"Playing video: {title}",
                    "data": result.data
                }
        except Exception as e:
            logger.warning("BrowserAgentTool failed: %s", e)
    
    # Fallback to URL open (MusicPlayTool would be called separately by LLM)
    url = ctx.url or _youtube_search_url(str(title))
    ok = await _open_browser(url)
    return {
        "opened": ok,
        "url": url,
        "action": "play_media",
        "title": str(title),
        "automated": False,
        "message": f"Opened YouTube for {title!r}" if ok else "Browser launch failed",
    }
```

---

## 💡 Key Insights

### For Users:
- **"play music"** → Fast audio playback (MusicPlayTool)
- **"watch video"** → Browser with visuals (BrowserAgent)
- **Seamless** - LLM picks the right tool

### For Developers:
- **Keep both tools** - They serve different purposes
- **Clear descriptions** - Help LLM choose correctly
- **Graceful fallback** - If one fails, try another

### For Product:
- **Best of both worlds** - Fast audio + Rich video
- **No breaking changes** - Existing MusicPlayTool still works
- **Better UX** - Right tool for the right job

---

## ✅ Action Items

1. **Update MusicPlayTool description** - Emphasize "audio-only, background"
2. **Update BrowserAgentTool description** - Emphasize "video, visual, interactive"
3. **Keep both tools separate** - Let LLM choose based on user intent
4. **Optional:** Add smart wrapper if needed later

**Bottom line:** Both tools coexist peacefully. MusicPlayTool for audio, BrowserAgent for video. LLM chooses based on user intent. ✨
