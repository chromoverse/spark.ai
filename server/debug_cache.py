from app.client_core.utils.app_searcher import SystemSearcher
import json

searcher = SystemSearcher()
searcher._refresh_cache()

camera_items = {k: v for k, v in searcher._app_cache.items() if "camera" in k.lower()}
print(json.dumps(camera_items, indent=2))
