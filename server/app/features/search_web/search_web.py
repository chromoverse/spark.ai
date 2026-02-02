import os
import sys
import time
import subprocess
import webbrowser
from app.features.search_web.fetch_web_result import fetch_web_results_with_selenium
import logging

logger = logging.getLogger(__name__)


def search_web(details):
    """
    Opens websites normally, or runs Chrome headless search using Selenium
    if 'query' is provided.
    """
    command = details.actionDetails.app_name.lower().strip()
    if(command == ''):
        command = details.actionDetails.platforms[0].lower().strip()
    
    query = getattr(details.actionDetails, "query", "").strip()

    target = details.actionDetails.target.lower().strip()
    logger.info(f"search_web called with command: {command}, query: {query}, target: {target}")

    # --- Website shortcuts ---
    websites = {
        "youtube": "https://youtube.com",
        "google": "https://google.com",
        "github": "https://github.com",
        "gmail": "https://mail.google.com",
        "facebook": "https://facebook.com",
        "chatgpt": "https://chat.openai.com",
        "chess": "https://chess.com",
    }

 # --- Chrome logic ---
    if ("chrome" in command) or ("google" in command) or ("web" in command):
        if query:
            print(f"🔍 Running headless search for '{query}' ...")
            results = fetch_web_results_with_selenium(query)
            details.actionDetails.searchResults = results
            logger.info(f"Fetched {results} results for query: {query}")
            print("✅ Results fetched and appended to actionDetails.")
            return details
        else:
            print("🚀 Launching Chrome ...")
            _open_exe("chrome")
        return

    # # --- Website handling ---
    # for name, url in websites.items():
    #     if name in command:
    #         print(f"🌐 Opening {url} ...")
    #         webbrowser.open(url)
    #         return


    # print("❌ Sorry, I couldn’t find a match for that command.")

def _open_exe(exe):
    """Cross-platform safe app launcher."""
    if sys.platform.startswith("win"):
        os.system(f"start {exe}")
    elif sys.platform.startswith("darwin"):
        subprocess.Popen(["open", "-a", exe])
    else:
        subprocess.Popen([exe])
