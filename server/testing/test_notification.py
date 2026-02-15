from app.agent.client_core.notification import show_approval_notification,show_info_notification

show_approval_notification(
    user_id="test_user",
    task_id="test_task",
    question="Approve this task?",
    on_response_callback=None
)
# show_info_notification("Test Notification", "This is a test notification from the server.")