# If spawned by Electron
from app.utils.path_manager import PathManager

path_manager = PathManager()

print(path_manager.get_user_data_dir())
print(path_manager.get_models_dir())
print(path_manager.get_redis_url())
print(path_manager.get_memory_dir())