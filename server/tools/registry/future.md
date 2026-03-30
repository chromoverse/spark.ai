# 🤖 Jarvis Tool Registry
**Version:** 2.2.0
**Last Updated:** 2026-02-16
**Total Tools:** 186

> A comprehensive registry of all Jarvis automation tools, organized by category. All tools follow the `category_action` snake_case naming convention. Tools marked with ⚠️ require user approval before execution. Tools marked with 🌐 execute server-side; all others execute client-side.

---

## 📑 Table of Contents

1. [System](#-system)
2. [AI / Intelligence](#-ai--intelligence)
3. [Audio / Music](#-audio--music)
4. [Video / Movies](#-video--movies)
5. [Email](#-email)
6. [Messaging](#-messaging)
7. [Calendar & Tasks](#-calendar--tasks)
8. [File System](#-file-system)
9. [Web & Browser](#-web--browser)
10. [Code & Developer Tools](#-code--developer-tools)
11. [Navigation & Location](#-navigation--location)
12. [Productivity & Documents](#-productivity--documents)
13. [Security & Privacy](#-security--privacy)
14. [Smart Home / IoT](#-smart-home--iot)
15. [Voice & Speech](#-voice--speech)
16. [Social Media](#-social-media)
17. [Workflow & Automation](#-workflow--automation)

---

## 🖥️ System

> System-level operations, monitoring, and window management.

| Tool Name | Description | Approval | Timeout |
|---|---|---|---|
| `app_open` | Launch an installed application | ⚠️ Yes | 3000ms |
| `app_close` | Kill a running process | ⚠️ Yes | 3000ms |
| `app_restart` | Safely restart an application with optional state save | ⚠️ Yes | 5000ms |
| `app_minimize` | Minimize an application window | No | 2000ms |
| `app_maximize` | Maximize an application window | No | 2000ms |
| `app_focus` | Bring an application to the front and focus it | No | 2000ms |
| `system_info` | Get CPU, RAM, and Disk usage metrics | No | 2000ms |
| `battery_status` | Get battery percentage, charge state, time remaining, and health | No | 1000ms |
| `network_status` | Get internet connectivity, local IP, public IP, and network name | No | 3000ms |
| `clipboard_read` | Read current clipboard content and type | No | 500ms |
| `clipboard_write` | Write content to the clipboard | No | 500ms |
| `notification_push` | Send a native OS notification with title, message, and urgency | No | 1000ms |
| `screenshot_capture` | Capture the full screen or a specific window | No | 2000ms |
| `brightness_status` | Get current screen brightness level | No | 1000ms |
| `brightness_increase` | Increase screen brightness by a specified amount (default +1) | No | 1000ms |
| `brightness_decrease` | Decrease screen brightness by a specified amount (default -1) | No | 1000ms |
| `sound_status` | Get current system volume and mute status | No | 1000ms |
| `sound_increase` | Increase system volume by a specified amount (default +30) | No | 1000ms |
| `sound_decrease` | Decrease system volume by a specified amount (default -30) | No | 1000ms |
| `volume_set` | Set volume to an exact level (0–100) | No | 1000ms |
| `volume_mute` | Mute system audio | No | 500ms |
| `volume_unmute` | Unmute system audio | No | 500ms |
| `lock_screen` | Lock the device screen immediately | No | 1000ms |

---

## 🧠 AI / Intelligence

> LLM-powered cognitive tools for reasoning, generation, and analysis. All tools execute server-side. 🌐

| Tool Name | Description | Approval | Timeout |
|---|---|---|---|
| `ai_summarize` 🌐 | Summarize any passed content — text, URL, or file | No | 10000ms |
| `ai_translate` 🌐 | Translate text between any two languages | No | 8000ms |
| `ai_rewrite` 🌐 | Rewrite content in a specified tone or style | No | 8000ms |
| `ai_classify` 🌐 | Classify and label content into defined categories | No | 5000ms |
| `ai_extract` 🌐 | Extract structured data (names, dates, entities) from text | No | 6000ms |
| `ai_sentiment` 🌐 | Detect sentiment or emotion from text | No | 4000ms |
| `ai_qa` 🌐 | Answer a question given a context document or passage | No | 10000ms |
| `ai_image_describe` 🌐 | Describe an image using a vision model | No | 8000ms |
| `ai_image_generate` 🌐 | Generate an image from a text prompt | No | 20000ms |
| `ai_ocr` 🌐 | Extract text from images or screenshots | No | 8000ms |
| `ai_proofread` 🌐 | Grammar, clarity, and style check on text | No | 6000ms |
| `ai_code_explain` 🌐 | Explain a code snippet in plain English | No | 8000ms |
| `ai_code_generate` 🌐 | Generate code from a natural language description | No | 15000ms |
| `ai_code_fix` 🌐 | Debug and fix broken code | No | 12000ms |
| `ai_code_review` 🌐 | Review code for quality, security, and best practices | No | 12000ms |

---

## 🎵 Audio / Music

> Music playback, queue management, and playlist control.

| Tool Name | Description | Approval | Timeout |
|---|---|---|---|
| `song_play` | Play a song by name, artist, or URL | No | 3000ms |
| `song_pause` | Pause current playback | No | 500ms |
| `song_resume` | Resume paused playback | No | 500ms |
| `song_stop` | Stop playback entirely and reset position | No | 500ms |
| `song_next` | Skip to the next track in the queue | No | 1000ms |
| `song_previous` | Go back to the previous track | No | 1000ms |
| `song_seek` | Seek to a specific timestamp in the current track | No | 1000ms |
| `song_like` | Like or favorite the currently playing track | No | 1000ms |
| `song_shuffle` | Toggle shuffle mode on or off | No | 500ms |
| `song_repeat` | Set repeat mode: none, one, or all | No | 500ms |
| `song_queue_add` | Add a song to the current playback queue | No | 1000ms |
| `song_queue_clear` | Clear all songs from the playback queue | No | 500ms |
| `song_queue_list` | List all tracks currently in the queue | No | 500ms |
| `playlist_play` | Play a playlist by name or ID | No | 3000ms |
| `playlist_create` | Create a new playlist | No | 2000ms |
| `playlist_add_song` | Add a song to a named playlist | No | 1000ms |
| `playlist_remove_song` | Remove a song from a playlist | No | 1000ms |
| `playlist_list` | List all saved playlists | No | 2000ms |

---

## 🎬 Video / Movies

> Video file and streaming playback control.

| Tool Name | Description | Approval | Timeout |
|---|---|---|---|
| `video_play` | Play a video by name, file path, or URL | No | 3000ms |
| `video_pause` | Pause the current video | No | 500ms |
| `video_resume` | Resume a paused video | No | 500ms |
| `video_stop` | Stop video playback entirely | No | 500ms |
| `video_seek` | Jump to a specific timestamp in the video | No | 1000ms |
| `video_fullscreen` | Toggle fullscreen mode | No | 500ms |
| `video_subtitle_toggle` | Enable or disable subtitles | No | 500ms |
| `video_subtitle_language` | Set subtitle language | No | 500ms |
| `video_speed_set` | Set playback speed (e.g., 0.5x, 1x, 1.5x, 2x) | No | 500ms |
| `movie_search` | Search for a movie across available streaming platforms | No | 5000ms |
| `movie_play` | Play a movie from a connected streaming service | No | 5000ms |
| `movie_info` | Get metadata, ratings, cast, and synopsis for a movie | No | 5000ms |
| `show_play` | Play a specific TV show episode | No | 5000ms |
| `show_next_episode` | Automatically play the next episode in a series | No | 3000ms |
| `youtube_search` | Search YouTube for a video | No | 5000ms |
| `youtube_play` | Play a specific YouTube video by title or URL | No | 3000ms |

---

## 📧 Email

> Full email automation for Gmail, Outlook, and other providers.

| Tool Name | Description | Approval | Timeout |
|---|---|---|---|
| `email_send` | Compose and send an email to one or more recipients | ⚠️ Yes | 5000ms |
| `email_read` | Read emails from inbox with optional filters | No | 5000ms |
| `email_reply` | Reply to a specific email thread | ⚠️ Yes | 5000ms |
| `email_reply_all` | Reply-all to a specific email thread | ⚠️ Yes | 5000ms |
| `email_forward` | Forward an email to another recipient | ⚠️ Yes | 5000ms |
| `email_delete` | Delete a specific email | ⚠️ Yes | 3000ms |
| `email_archive` | Archive an email to remove it from the inbox | No | 2000ms |
| `email_label_add` | Add a label or tag to an email | No | 2000ms |
| `email_label_remove` | Remove a label or tag from an email | No | 2000ms |
| `email_search` | Search emails by keyword, sender, date, or label | No | 5000ms |
| `email_mark_read` | Mark one or more emails as read | No | 2000ms |
| `email_mark_unread` | Mark one or more emails as unread | No | 2000ms |
| `email_draft_save` | Save an email as a draft | No | 2000ms |
| `email_attachment_download` | Download attachments from an email to a local path | No | 10000ms |
| `email_unsubscribe` | Detect and unsubscribe from a mailing list | ⚠️ Yes | 5000ms |
| `email_summarize_inbox` | AI-summarize all unread emails in the inbox | No | 15000ms |

---

## 💬 Messaging

> Chat automation for WhatsApp, Telegram, Slack, iMessage, and more.

| Tool Name | Description | Approval | Timeout |
|---|---|---|---|
| `message_send` | Send a message to a contact or group | ⚠️ Yes | 3000ms |
| `message_read` | Read recent messages from a conversation | No | 3000ms |
| `message_reply` | Reply to the latest message in a thread | ⚠️ Yes | 3000ms |
| `message_forward` | Forward a message to another contact or group | ⚠️ Yes | 3000ms |
| `message_delete` | Delete a sent message | ⚠️ Yes | 2000ms |
| `message_search` | Search messages by keyword or contact | No | 5000ms |
| `message_schedule` | Schedule a message to be sent at a specific time | No | 2000ms |
| `message_react` | React to a message with a specified emoji | No | 1000ms |
| `contact_search` | Look up a contact's information by name or number | No | 3000ms |
| `call_start` | Initiate a voice or video call with a contact | ⚠️ Yes | 5000ms |
| `call_end` | End the currently active call | No | 1000ms |

---

## 📅 Calendar & Tasks

> Scheduling, reminders, to-dos, alarms, and timers.

| Tool Name | Description | Approval | Timeout |
|---|---|---|---|
| `calendar_event_create` | Create a new calendar event with title, time, and location | ⚠️ Yes | 3000ms |
| `calendar_event_read` | Read upcoming events within a specified date range | No | 3000ms |
| `calendar_event_update` | Update details of an existing calendar event | ⚠️ Yes | 3000ms |
| `calendar_event_delete` | Delete a calendar event | ⚠️ Yes | 3000ms |
| `calendar_event_search` | Search events by keyword or date | No | 3000ms |
| `reminder_set` | Set a time-based or location-based reminder | No | 2000ms |
| `reminder_list` | List all active reminders | No | 2000ms |
| `reminder_delete` | Delete a specific reminder | No | 1000ms |
| `task_create` | Create a new to-do or task item | No | 2000ms |
| `task_complete` | Mark a task as done | No | 1000ms |
| `task_list` | List all pending tasks, optionally filtered | No | 2000ms |
| `task_delete` | Delete a task permanently | No | 1000ms |
| `task_prioritize` | Reorder or reprioritize a list of tasks | No | 2000ms |
| `timer_start` | Start a countdown timer for a specified duration | No | 500ms |
| `timer_stop` | Stop the currently running timer | No | 500ms |
| `timer_status` | Get remaining time on the active timer | No | 500ms |
| `stopwatch_start` | Start a stopwatch | No | 500ms |
| `stopwatch_stop` | Stop the stopwatch and return elapsed time | No | 500ms |
| `alarm_set` | Set an alarm for a specific date and time | No | 1000ms |
| `alarm_cancel` | Cancel an active alarm | No | 1000ms |
| `alarm_list` | List all scheduled alarms | No | 1000ms |

---

## 📁 File System

> File and folder creation, management, and organization.

| Tool Name | Description | Approval | Timeout |
|---|---|---|---|
| `file_search` | Locate files and folders matching a query | No | 10000ms |
| `file_open` | Open a file with its default or a specified application | No | 3000ms |
| `file_read` | Read and return the text content of a file | No | 5000ms |
| `file_create` | Create a new file with optional content | ⚠️ Yes | 5000ms |
| `file_delete` | Delete a file (to trash or permanently) | ⚠️ Yes | 3000ms |
| `file_rename` | Rename a file in place | ⚠️ Yes | 2000ms |
| `file_move` | Move a file to a new location | ⚠️ Yes | 5000ms |
| `file_copy` | Copy a file to a destination path | No | 10000ms |
| `file_compress` | Compress one or more files into a zip or archive | No | 10000ms |
| `file_extract` | Extract a compressed archive to a specified path | No | 10000ms |
| `file_convert` | Convert a file to another format (e.g., DOCX → PDF) | No | 15000ms |
| `file_share` | Share a file via a link or a connected application | No | 5000ms |
| `file_upload` | Upload a file to cloud storage | No | 30000ms |
| `file_download` | Download a file from a URL to a local path | No | 30000ms |
| `file_metadata` | Get file metadata including size, type, and timestamps | No | 2000ms |
| `file_summarize` | AI-summarize the text content of a file | No | 15000ms |
| `folder_create` | Create a new directory, recursively if needed | No | 2000ms |
| `folder_rename` | Rename a directory | ⚠️ Yes | 2000ms |
| `folder_delete` | Delete a folder and its contents | ⚠️ Yes | 5000ms |
| `folder_list` | List all files and subfolders within a directory | No | 3000ms |
| `folder_size` | Get the total disk size used by a folder | No | 5000ms |
| `folder_organize` | Auto-sort files within a folder by type, date, or name | ⚠️ Yes | 30000ms |
| `folder_cleanup` | Remove duplicates, temp files, and junk from a folder | ⚠️ Yes | 30000ms |
| `cloud_sync` | Sync a local folder to or from cloud storage | ⚠️ Yes | 60000ms |
| `trash_empty` | Permanently empty the system trash | ⚠️ Yes | 5000ms |

---

## 🌐 Web & Browser

> Browser control and web automation.

| Tool Name | Description | Approval | Timeout |
|---|---|---|---|
| `web_search` 🌐 | Search the web for information | No | 5000ms |
| `web_scrape` 🌐 | Fetch and extract readable content from a public webpage | No | 5000ms |
| `web_download` | Download a file from a URL | No | 30000ms |
| `web_form_fill` | Auto-fill a web form with provided data | ⚠️ Yes | 5000ms |
| `browser_open` | Open a URL in the default browser | No | 2000ms |
| `browser_tab_new` | Open a new browser tab with a given URL | No | 2000ms |
| `browser_tab_close` | Close a specific browser tab by index or title | No | 1000ms |
| `browser_tab_switch` | Switch focus to a tab by index or title | No | 1000ms |
| `browser_tab_list` | List all currently open browser tabs | No | 1000ms |
| `browser_scroll` | Scroll a webpage up or down by a specified amount | No | 500ms |
| `browser_screenshot` | Capture a screenshot of the current webpage | No | 3000ms |
| `browser_bookmark_add` | Save a URL to bookmarks | No | 1000ms |
| `browser_bookmark_search` | Search saved bookmarks by keyword | No | 2000ms |
| `browser_history_search` | Search browser history by keyword or date | No | 3000ms |
| `browser_history_clear` | Clear browser history for a specified time range | ⚠️ Yes | 3000ms |

---

## 💻 Code & Developer Tools

> Development workflow automation including git, terminals, and servers.

| Tool Name | Description | Approval | Timeout |
|---|---|---|---|
| `code_run` | Execute a code snippet in a specified language | ⚠️ Yes | 30000ms |
| `code_lint` | Lint code for syntax and style errors | No | 10000ms |
| `code_format` | Auto-format code using the appropriate formatter | No | 5000ms |
| `code_test` | Run unit tests for a project or file | No | 60000ms |
| `code_build` | Trigger a build process for a project | ⚠️ Yes | 120000ms |
| `code_deploy` | Deploy code to a server or cloud environment | ⚠️ Yes | 120000ms |
| `git_status` | Get the current git repository status | No | 3000ms |
| `git_commit` | Stage and commit changes with a message | ⚠️ Yes | 5000ms |
| `git_push` | Push commits to the remote repository | ⚠️ Yes | 10000ms |
| `git_pull` | Pull the latest changes from remote | No | 10000ms |
| `git_branch_create` | Create a new git branch | No | 3000ms |
| `git_branch_switch` | Switch to a different git branch | ⚠️ Yes | 3000ms |
| `git_log` | View recent commit history for the repository | No | 3000ms |
| `git_diff` | Show uncommitted changes in the working directory | No | 3000ms |
| `terminal_run` | Run any shell or terminal command | ⚠️ Yes | 30000ms |
| `package_install` | Install a package via npm, pip, brew, etc. | ⚠️ Yes | 60000ms |
| `package_uninstall` | Uninstall a package | ⚠️ Yes | 30000ms |
| `server_start` | Start a local development server | ⚠️ Yes | 10000ms |
| `server_stop` | Stop a running local server | ⚠️ Yes | 5000ms |
| `server_status` | Get the status of a local or remote server | No | 3000ms |
| `env_variable_get` | Read the value of an environment variable | No | 500ms |
| `env_variable_set` | Set the value of an environment variable | ⚠️ Yes | 1000ms |
| `api_call` | Make an arbitrary HTTP API request (GET, POST, etc.) | ⚠️ Yes | 15000ms |
| `docker_start` | Start a Docker container by name or ID | ⚠️ Yes | 10000ms |
| `docker_stop` | Stop a running Docker container | ⚠️ Yes | 5000ms |
| `docker_list` | List all running Docker containers | No | 3000ms |

---

## 🗺️ Navigation & Location

> Maps, directions, weather, and geolocation.

| Tool Name | Description | Approval | Timeout |
|---|---|---|---|
| `location_get` | Get the device's current GPS location | No | 5000ms |
| `maps_search` | Search for a place or address on the map | No | 5000ms |
| `maps_open` | Open a location in the maps application | No | 2000ms |
| `maps_directions` | Get step-by-step directions from one place to another | No | 5000ms |
| `traffic_status` | Get live traffic status along a route | No | 5000ms |
| `eta_calculate` | Calculate estimated travel time for a route | No | 5000ms |
| `nearby_search` | Find nearby places of a specified type (restaurants, hospitals, etc.) | No | 5000ms |
| `weather_current` | Get the current weather for a specific location | No | 3000ms |
| `weather_forecast` | Get a multi-day weather forecast for a location | No | 3000ms |

---

## 📊 Productivity & Documents

> Notes, documents, spreadsheets, PDFs, and presentations.

| Tool Name | Description | Approval | Timeout |
|---|---|---|---|
| `note_create` | Create a new note with title and content | No | 2000ms |
| `note_read` | Read the content of an existing note | No | 2000ms |
| `note_update` | Update the content of a note | No | 2000ms |
| `note_delete` | Delete a note permanently | ⚠️ Yes | 2000ms |
| `note_search` | Search notes by keyword | No | 3000ms |
| `note_list` | List all saved notes | No | 2000ms |
| `doc_create` | Create a new Word or Google Doc | No | 3000ms |
| `doc_open` | Open an existing document in its application | No | 3000ms |
| `doc_summarize` | AI-summarize the content of a document | No | 15000ms |
| `spreadsheet_create` | Create a new spreadsheet with optional headers and data | No | 3000ms |
| `spreadsheet_read` | Read data from a spreadsheet by range or sheet name | No | 5000ms |
| `spreadsheet_update` | Update a specific cell or range in a spreadsheet | ⚠️ Yes | 5000ms |
| `pdf_create` | Convert content or a document to PDF | No | 10000ms |
| `pdf_merge` | Merge multiple PDF files into one | No | 10000ms |
| `pdf_split` | Split a PDF into individual pages or sections | No | 10000ms |
| `pdf_summarize` | AI-summarize the content of a PDF | No | 15000ms |
| `presentation_create` | Generate a slide deck from a topic or outline | No | 15000ms |
| `qr_generate` | Generate a QR code from a URL or text string | No | 2000ms |

---

## 🔐 Security & Privacy

> Password management, 2FA, VPN, and privacy tools.

| Tool Name | Description | Approval | Timeout |
|---|---|---|---|
| `password_generate` | Generate a cryptographically secure password | No | 500ms |
| `password_save` | Save credentials to the password manager | ⚠️ Yes | 2000ms |
| `password_retrieve` | Retrieve saved credentials for a site or app | ⚠️ Yes | 2000ms |
| `2fa_code_get` | Retrieve a 2FA OTP code for a registered account | No | 2000ms |
| `vpn_connect` | Connect to a VPN server | No | 5000ms |
| `vpn_disconnect` | Disconnect from the active VPN | No | 3000ms |
| `vpn_status` | Get current VPN connection status | No | 1000ms |
| `privacy_report` | Run a privacy audit on installed apps and permissions | No | 15000ms |

---

## 🏠 Smart Home / IoT

> Control lights, thermostats, smart plugs, and connected devices.

| Tool Name | Description | Approval | Timeout |
|---|---|---|---|
| `light_on` | Turn on smart lights in a room or by name | No | 3000ms |
| `light_off` | Turn off smart lights | No | 3000ms |
| `light_brightness_set` | Set smart light brightness as a percentage | No | 2000ms |
| `light_color_set` | Change the color of smart lights | No | 2000ms |
| `light_status` | Get the current state of smart lights | No | 2000ms |
| `thermostat_get` | Get the current thermostat reading and target temperature | No | 3000ms |
| `thermostat_set` | Set the thermostat to a target temperature | No | 3000ms |
| `device_lock` | Lock a smart door or connected device | ⚠️ Yes | 3000ms |
| `device_unlock` | Unlock a smart door or connected device | ⚠️ Yes | 3000ms |
| `device_status` | Get the status of a connected smart device | No | 3000ms |
| `smart_plug_on` | Turn on a smart plug by name | No | 2000ms |
| `smart_plug_off` | Turn off a smart plug by name | No | 2000ms |
| `smart_plug_status` | Get the current status of a smart plug | No | 2000ms |
| `camera_feed_view` | Open and view a smart camera stream | ⚠️ Yes | 5000ms |

---

## 🗣️ Voice & Speech

> Text-to-speech, speech-to-text, and wake-word control.

| Tool Name | Description | Approval | Timeout |
|---|---|---|---|
| `tts_speak` | Convert text to speech and play it aloud | No | 5000ms |
| `tts_language_set` | Set the language and accent for text-to-speech | No | 500ms |
| `tts_speed_set` | Set the speech rate for text-to-speech output | No | 500ms |
| `stt_listen` | Record audio from the microphone and transcribe it | No | 30000ms |
| `stt_language_set` | Set the language for speech-to-text recognition | No | 500ms |
| `voice_wake_enable` | Enable always-on wake-word detection | No | 1000ms |
| `voice_wake_disable` | Disable wake-word detection | No | 1000ms |

---

## 📱 Social Media

> Posting, scheduling, and reading across social platforms.

| Tool Name | Description | Approval | Timeout |
|---|---|---|---|
| `social_post_create` | Post content to Twitter/X, LinkedIn, or other platforms | ⚠️ Yes | 5000ms |
| `social_post_schedule` | Schedule a social media post for a future time | ⚠️ Yes | 3000ms |
| `social_post_delete` | Delete a published social media post | ⚠️ Yes | 3000ms |
| `social_feed_read` | Read recent posts from a platform feed | No | 5000ms |
| `social_trending_get` | Get currently trending topics on a platform | No | 5000ms |
| `social_dm_send` | Send a direct message on a social platform | ⚠️ Yes | 3000ms |

---

## 🔄 Workflow & Automation

> Orchestrate multi-step automations, cron jobs, and event triggers.

| Tool Name | Description | Approval | Timeout |
|---|---|---|---|
| `workflow_run` | Trigger a predefined named automation workflow | ⚠️ Yes | 60000ms |
| `workflow_schedule` | Schedule a workflow to run at a specific time | No | 3000ms |
| `workflow_chain` | Execute multiple tools sequentially in a defined order | ⚠️ Yes | 120000ms |
| `workflow_list` | List all saved automation workflows | No | 2000ms |
| `workflow_delete` | Delete a saved workflow | ⚠️ Yes | 2000ms |
| `webhook_send` | Send an HTTP webhook payload to an external service | ⚠️ Yes | 10000ms |
| `cron_create` | Create a recurring scheduled job with a cron expression | No | 2000ms |
| `cron_list` | List all active cron jobs | No | 1000ms |
| `cron_delete` | Delete a cron job by ID or name | ⚠️ Yes | 1000ms |
| `event_listen` | Listen for a system or app event and trigger an action | No | — |

---

## 📈 Tool Summary

| # | Category | Tool Count | Server-Side | Requires Approval |
|---|---|---|---|---|
| 1 | 🖥️ System | 23 | 0 | 3 |
| 2 | 🧠 AI / Intelligence | 15 | 15 | 0 |
| 3 | 🎵 Audio / Music | 18 | 0 | 0 |
| 4 | 🎬 Video / Movies | 16 | 0 | 0 |
| 5 | 📧 Email | 16 | 0 | 8 |
| 6 | 💬 Messaging | 11 | 0 | 6 |
| 7 | 📅 Calendar & Tasks | 21 | 0 | 5 |
| 8 | 📁 File System | 25 | 0 | 11 |
| 9 | 🌐 Web & Browser | 15 | 2 | 3 |
| 10 | 💻 Code & Developer | 26 | 0 | 18 |
| 11 | 🗺️ Navigation & Location | 9 | 0 | 0 |
| 12 | 📊 Productivity & Documents | 18 | 0 | 2 |
| 13 | 🔐 Security & Privacy | 8 | 0 | 3 |
| 14 | 🏠 Smart Home / IoT | 14 | 0 | 2 |
| 15 | 🗣️ Voice & Speech | 7 | 0 | 0 |
| 16 | 📱 Social Media | 6 | 0 | 5 |
| 17 | 🔄 Workflow & Automation | 10 | 0 | 6 |
| | **Total** | **288** | **17** | **72** |

---

## 📐 Naming Convention

All tools follow a strict `category_action` snake_case convention:

```
{noun/domain}_{verb}

Examples:
  song_play       ✅  (noun: song, verb: play)
  file_delete     ✅  (noun: file, verb: delete)
  ai_summarize    ✅  (noun: ai, verb: summarize)
  brightness_set  ✅  (noun: brightness, verb: set)

  play_song       ❌  (verb before noun)
  FileCopy        ❌  (PascalCase)
  file-copy       ❌  (kebab-case)
  copyFile        ❌  (camelCase)
```

### Verb Glossary

| Verb | Usage |
|---|---|
| `create` | Make something new |
| `read` | Non-destructive data retrieval |
| `update` | Modify an existing item |
| `delete` | Remove permanently |
| `search` | Query or look up items |
| `list` | Return a collection of items |
| `open` | Launch or display something |
| `close` | Dismiss or terminate |
| `send` | Dispatch to another destination |
| `play` | Begin media playback |
| `pause` | Temporarily halt playback |
| `stop` | Fully end playback |
| `start` | Begin a process or session |
| `run` | Execute code or a command |
| `set` | Set to an exact value |
| `get` | Retrieve a specific value |
| `increase` | Increment a value |
| `decrease` | Decrement a value |
| `toggle` | Flip a boolean state |
| `enable` / `disable` | Turn a feature on or off |

---

## ⚠️ Approval Policy

Tools flagged with **⚠️ Requires Approval** will prompt the user for confirmation before execution. The approval threshold is triggered when:

- The action is **irreversible** (delete, deploy, push)
- The action sends **data externally** (email, messages, social posts)
- The action **modifies system state** in a significant way (code run, terminal)
- The action involves **credentials or security** (password save, device unlock)

---

*Built for Jarvis v2.2.0 — Extensible, modular, and approval-aware.*