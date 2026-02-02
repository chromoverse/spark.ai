"""
Test script for using Python Service independently
"""

import sys
import os
import json

# Add the parent directory to the path so we can import python_service
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from python_service import execute_action, handle_action

# Example 1: Using execute_action (simpler method)
def test_simple_action():
    """Test opening an app using execute_action"""
    print("Testing: Opening Notepad")
    result = execute_action('open_app', app_name='notepad')
    print(f"Result: {json.dumps(result, indent=2)}\n")
    return result

# Example 2: Using handle_action with full payload
def test_full_payload():
    """Test with full payload structure"""
    print("Testing: Full payload example")
    
    payload = {
        "userQuery": "Spark open notepad",
        "answer": "नोटपैड खोल रहा हूं, सर।",
        "answerEnglish": "Opening notepad, Sir.",
        "actionCompletedMessage": "हो गया सर, देख सकते हैं। कुछ और चाहिए?",
        "actionCompletedMessageEnglish": "Done Sir, you can check. Need anything else?",
        "action": "open_notepad",
        "emotion": "neutral",
        "answerDetails": {
            "content": "Hey there new is me lorem ipsum",
            "sources": [],
            "references": [],
            "additional_info": {}
        },
        "actionDetails": {
            "type": "open_app",
            "query": "open notepad",
            "title": "",
            "artist": "",
            "topic": "",
            "platforms": [],
            "app_name": "notepad",  # Changed from "whatsapp" to "notepad"
            "target": "",
            "location": "",
            "searchResults": [],
            "confirmation": {
                "isConfirmed": True,  # Changed from string "true" to boolean True
                "actionRegardingQuestion": ""
            },
            "additional_info": {}
        }
    }
    
    result = handle_action(payload)
    print(f"Result: {json.dumps(result, indent=2)}\n")
    return result

# Example 3: Test other actions
def test_send_message():
    """Test sending a message"""
    print("Testing: Sending a message")
    result = execute_action(
        'send_message',
        target='John Doe',
        content='Hello from Python Service!'
    )
    print(f"Result: {json.dumps(result, indent=2)}\n")
    return result

def test_create_task():
    """Test creating a task"""
    print("Testing: Creating a task")
    result = execute_action(
        'create_task',
        task_description='Finish the Python Service documentation',
        due_date='2024-12-31',
        priority='high'
    )
    print(f"Result: {json.dumps(result, indent=2)}\n")
    return result

if __name__ == "__main__":
    print("=" * 60)
    print("Python Service - Standalone Testing")
    print("=" * 60 + "\n")
    
    # Uncomment the tests you want to run:
    
    # test_simple_action()
    # test_full_payload()
    # test_send_message()
    # test_create_task()
    
    print("\nNote: Uncomment the test functions you want to run above")
