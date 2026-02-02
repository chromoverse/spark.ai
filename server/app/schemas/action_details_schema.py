ACTION_DETAILS_SCHEMA = {
    "type": "",             # core action category (e.g., "play_song", "search", "open_app", "navigate", "message", "control_device")
    "query": "",            # raw query string / parsed phrase
    "title": "",            # for content titles (song, video, note, etc.)
    "artist": "",           # for music
    "topic": "",            # for search/news/weather
    "platforms": [],        # prioritized array like ["youtube", "musicplayer", "spotify"]
    "app_name": "",         # if opening or interacting with an app
    "target": "",           # recipient (for messages, reminders, calls)
    "location": "",         # for map/weather-based actions
    "additional_info": {},  # flexible dict for extension
}