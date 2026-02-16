from app.agent.shared.utils.process_manager.process_manager import ProcessManager, Direction
import json

pm = ProcessManager()

# print(pm.get_screen_info(0))
# print(json.dumps(pm.list_running_processes(), indent=2))
pm.bring_to_focus("docker")
# pm.close_process("control panel")
# print(pm.find_process("notepad"))
