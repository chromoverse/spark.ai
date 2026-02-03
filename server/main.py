"""
Spark.AI Server Entry Point
===========================
This is the main entry point for the server application.

Path management and environment loading are handled by app.config.
PyTorch DLL fix is handled by the runtime hook (hooks/hook-torch-dll.py).
"""
import sys
import os

# Set working directory for PyInstaller bundle
if getattr(sys, 'frozen', False):
    os.chdir(getattr(sys, '_MEIPASS', '.'))

try:
    import uvicorn
    from app.config import settings  # Handles .env loading and path management
    
    def serve():
        """Start the uvicorn server."""
        uvicorn.run(
            "app.main:app", 
            host="127.0.0.1", 
            port=settings.port, 
            reload=False  # Must be False for PyInstaller bundle
        )

except Exception as e:
    print(f"ERROR during import/setup: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    input("\nPress Enter to exit...")
    sys.exit(1)


if __name__ == "__main__":
    try:
        serve()
    except Exception as e:
        print(f"ERROR during server execution: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        input("\nPress Enter to exit...")
        sys.exit(1)