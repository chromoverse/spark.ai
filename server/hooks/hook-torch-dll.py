"""
PyInstaller Runtime Hook for PyTorch DLL Loading
=================================================
This hook runs BEFORE the application code, ensuring torch DLLs
can be found before any module imports torch.

CRITICAL: This must run before ANY other imports.
"""
import sys
import os

def setup_torch_dll_path():
    """Add torch lib directory to DLL search path."""
    if not getattr(sys, 'frozen', False):
        return  # Only needed for frozen exe
    
    # Get the PyInstaller bundle directory
    bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    
    # Possible torch lib locations
    torch_lib_paths = [
        os.path.join(bundle_dir, 'torch', 'lib'),
        os.path.join(bundle_dir, '_internal', 'torch', 'lib'),
        os.path.join(bundle_dir, 'torch'),
    ]
    
    for torch_lib in torch_lib_paths:
        if os.path.isdir(torch_lib):
            # Prepend to PATH
            os.environ['PATH'] = torch_lib + os.pathsep + os.environ.get('PATH', '')
            
            # Python 3.8+ on Windows: use add_dll_directory
            if hasattr(os, 'add_dll_directory'):
                try:
                    os.add_dll_directory(torch_lib)
                except Exception:
                    pass
            
            # Also add parent torch directory
            torch_parent = os.path.dirname(torch_lib)
            if os.path.isdir(torch_parent):
                os.environ['PATH'] = torch_parent + os.pathsep + os.environ.get('PATH', '')
                if hasattr(os, 'add_dll_directory'):
                    try:
                        os.add_dll_directory(torch_parent)
                    except Exception:
                        pass
            break

# Execute immediately when hook is loaded
setup_torch_dll_path()
