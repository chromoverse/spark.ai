from concurrent.futures import ThreadPoolExecutor
from app.services.actions.action_dispatcher import dispatch_action

def run_action_in_thread(action_type, details):
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(dispatch_action, action_type, details)
        return future.result()
