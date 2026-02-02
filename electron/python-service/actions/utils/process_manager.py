import logging
import time
import psutil
from typing import List, Optional
import platform

logger = logging.getLogger(__name__)

class ProcessManager:
    """Manages process detection, waiting, and focusing"""
    
    @staticmethod
    def is_process_running(process_names: List[str]) -> bool:
        """Check if any of the given process names are running"""
        try:
            for proc in psutil.process_iter(['name']):
                proc_name = proc.info['name'].lower()
                for target_name in process_names:
                    if target_name.lower() in proc_name:
                        logger.debug(f"Found running process: {proc_name}")
                        return True
        except Exception as e:
            logger.warning(f"Error checking process: {e}")
        return False
    
    @staticmethod
    def wait_for_process(
        process_names: List[str], 
        timeout: int = 5,
        check_interval: float = 0.3
    ) -> bool:
        """
        Wait for a process to start, with timeout
        
        Args:
            process_names: List of process names to wait for
            timeout: Maximum time to wait in seconds
            check_interval: How often to check (seconds)
            
        Returns:
            True if process started, False if timeout
        """
        logger.info(f"Waiting for process: {process_names} (timeout: {timeout}s)")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if ProcessManager.is_process_running(process_names):
                elapsed = time.time() - start_time
                logger.info(f"Process started successfully after {elapsed:.2f}s")
                return True
            time.sleep(check_interval)
        
        logger.warning(f"Process did not start within {timeout}s")
        return False
    
    @staticmethod
    def focus_window(process_names: List[str]) -> bool:
        """
        Focus/bring to front an already running application
        Platform-specific implementation
        """
        try:
            system = platform.system()
            
            if system == "Windows":
                return ProcessManager._focus_window_windows(process_names)
                    
            elif system == "Darwin":  # macOS
                return ProcessManager._focus_window_macos(process_names)
                
            elif system == "Linux":
                return ProcessManager._focus_window_linux(process_names)
            
            return False
            
        except Exception as e:
            logger.warning(f"Could not focus window: {e}")
            return False
    
    @staticmethod
    def _focus_window_windows(process_names: List[str]) -> bool:
        """Windows-specific window focusing - FIXED to prevent resize"""
        try:
            import win32gui
            import win32con
            import win32process

            def find_window_by_process(hwnd, windows):
                if win32gui.IsWindowVisible(hwnd):
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    try:
                        proc = psutil.Process(pid)
                        proc_name = proc.name().lower()

                        for target_name in process_names:
                            if target_name.lower().replace('.exe', '') in proc_name:
                                windows.append(hwnd)
                                break
                    except:
                        pass
                return True

            windows = []
            win32gui.EnumWindows(find_window_by_process, windows)

            if not windows:
                logger.warning(f"No window found for process: {process_names}")
                return False

            hwnd = windows[0]

            # Check if minimized
            if win32gui.IsIconic(hwnd):
                logger.info("Window is minimized, restoring...")
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                time.sleep(0.2)
            else:
                # If not minimized, just ensure it's visible
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

            time.sleep(0.05)

            # Bring to foreground using simpler method
            try:
                # This is less aggressive and doesn't cause resize
                win32gui.BringWindowToTop(hwnd)
                win32gui.SetForegroundWindow(hwnd)
            except Exception as e:
                logger.debug(f"SetForegroundWindow failed (expected on some systems): {e}")
                # Fallback: Try Alt trick to gain foreground permission
                try:
                    import win32api
                    import win32com.client
                    shell = win32com.client.Dispatch("WScript.Shell")
                    shell.SendKeys('%')
                    win32gui.SetForegroundWindow(hwnd)
                except:
                    pass

            logger.info(f"Focused window: {process_names[0]}")
            return True

        except ImportError:
            logger.warning("pywin32 not installed, cannot focus window on Windows")
            return False
        except Exception as e:
            logger.error(f"Error focusing window on Windows: {e}")
            return False

    @staticmethod
    def _focus_window_macos(process_names: List[str]) -> bool:
        """macOS window focusing"""
        try:
            import subprocess
            app_name = process_names[0].replace('.app', '')
            subprocess.run(
                ['osascript', '-e', f'tell application "{app_name}" to activate'],
                check=True
            )
            logger.info(f"Focused window for {app_name}")
            return True
        except Exception as e:
            logger.warning(f"Error focusing window on macOS: {e}")
            return False
    
    @staticmethod
    def _focus_window_linux(process_names: List[str]) -> bool:
        """Linux window focusing (using wmctrl if available)"""
        try:
            import subprocess
            for proc_name in process_names:
                try:
                    subprocess.run(
                        ['wmctrl', '-a', proc_name.lower()],
                        check=True,
                        stderr=subprocess.DEVNULL
                    )
                    logger.info(f"Focused window for {proc_name}")
                    return True
                except:
                    continue
            return False
        except Exception as e:
            logger.warning(f"Error focusing window on Linux: {e}")
            return False