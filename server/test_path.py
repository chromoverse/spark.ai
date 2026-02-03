from app.config import USER_DATA_DIR

# print(USER_DATA_DIR)


import sys
from pathlib import Path
# -----------------------------------------------------------------------------
# Path Management Strategy used:
# 1. BUNDLE_DIR: Read-only application files (code, default configs)
# 2. USER_DATA_DIR: Writable persistent data (.env, logs, models, databases)
# -----------------------------------------------------------------------------
BUNDLE_DIR = Path(sys._MEIPASS)
    
    # Store user data in AppData/Local/SparkAI to avoid permission issues and persist updates
USER_DATA_DIR = Path.home() / "AppData" / "Local" / "SparkAI"

print(BUNDLE_DIR)
print(USER_DATA_DIR)

# if getattr(sys, 'frozen', False):
#     # Production (Frozen/Bundled)
#     # sys._MEIPASS is where PyInstaller extracts the bundle
    