# app/client_core/__init__.py
"""
Client Core - Standalone Task Execution Package

This package can be copied into Electron's Python process.
All imports are relative - no server dependencies.

Usage:
    from client_core.main import initialize_client, receive_tasks_from_server
    
    # Initialize once at startup
    initialize_client()
    
    # Receive tasks from server via WebSocket
    await receive_tasks_from_server(user_id, task_records)
"""

__version__ = "1.0.0"
__all__ = [
    "initialize_client",
    "get_execution_engine", 
    "receive_tasks_from_server"
]

from .main import initialize_client, get_execution_engine, receive_tasks_from_server
