#!/usr/bin/env python
"""
Build script for the Spark.AI server executable.
Run this script from within the .venv to build the PyInstaller bundle.

This script:
1. Verifies dependencies
2. Encrypts checks for PyTorch device
3. Encrypts .env secrets into bundled JSON
4. Builds the PyInstaller bundle (with torch DLL fix and bundled secrets)
5. Copies necessary files to dist
"""
import os
import subprocess
import shutil
import sys
import logging
import argparse
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_project_root() -> Path:
    """Get the absolute path to the project root (server directory)."""
    return Path(__file__).resolve().parent.parent


def get_venv_python(root_dir: Path) -> str | None:
    """Locate the Python executable in the local .venv directory."""
    venv_dir = root_dir / ".venv"
    if sys.platform == "win32":
        python_exe = venv_dir / "Scripts" / "python.exe"
    else:
        python_exe = venv_dir / "bin" / "python"
    
    if python_exe.exists():
        return str(python_exe)
    return None


def clean_build_artifacts(root_dir: Path):
    """Remove build and dist directories for a clean build."""
    logger.info("🧹 Cleaning previous build artifacts...")
    dirs_to_remove = [root_dir / "build", root_dir / "dist"]
    
    for d in dirs_to_remove:
        if d.exists():
            try:
                shutil.rmtree(d)
                logger.info(f"   Removed {d}")
            except Exception as e:
                logger.warning(f"   Failed to remove {d}: {e}")


def verify_dependencies(python_cmd: str) -> bool:
    """Verify all required dependencies are installed."""
    logger.info("🔍 Verifying dependencies...")
    
    required_modules = [
        ("pydantic_settings", "pydantic-settings"),
        ("torch", "torch"),
        ("uvicorn", "uvicorn"),
        ("fastapi", "fastapi"),
        ("cryptography", "cryptography"), # Added for secrets encryption
    ]
    
    all_ok = True
    for module_name, pip_name in required_modules:
        try:
            subprocess.check_call(
                [python_cmd, "-c", f"import {module_name}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            logger.info(f"   ✅ {module_name}")
        except subprocess.CalledProcessError:
            logger.error(f"   ❌ {module_name} - install with: pip install {pip_name}")
            all_ok = False
    
    return all_ok


def verify_torch_device(python_cmd: str):
    """Check torch device availability."""
    logger.info("🔥 Checking PyTorch device...")
    try:
        result = subprocess.run(
            [python_cmd, "-c", """
import torch
if torch.cuda.is_available():
    print(f"cuda ({torch.cuda.get_device_name(0)})")
elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
    print("mps")
else:
    print("cpu")
"""],
            capture_output=True,
            text=True
        )
        device = result.stdout.strip()
        logger.info(f"   Device: {device}")
    except Exception as e:
        logger.warning(f"   Could not determine device: {e}")


def encrypt_secrets(python_cmd: str, root_dir: Path) -> bool:
    """Run the secret encryption script."""
    logger.info("🔐 Encrypting secrets...")
    try:
        encrypt_script = root_dir / "script" / "encrypt_secrets.py"
        subprocess.check_call([python_cmd, str(encrypt_script)])
        return True
    except subprocess.CalledProcessError:
        logger.error("❌ Failed to encrypt secrets")
        return False


def run_pyinstaller(python_cmd: str, root_dir: Path) -> bool:
    """Run PyInstaller with the spec file."""
    logger.info("📦 Starting PyInstaller build...")
    logger.info("   This may take several minutes...")
    
    try:
        subprocess.check_call([
            python_cmd, '-m', 'PyInstaller', 
            'server.spec', 
            '--noconfirm', 
            '--clean'
        ], cwd=root_dir)
        logger.info("   ✅ PyInstaller build complete!")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"   ❌ PyInstaller failed with exit code {e.returncode}")
        return False


def post_build_setup(root_dir: Path):
    """Perform post-build operations."""
    dist_dir = root_dir / "dist" / "server"
    
    if not dist_dir.exists():
        logger.error(f"❌ Dist directory not found at {dist_dir}")
        return False
    
    logger.info("📋 Post-build operations...")
    
    # We NO LONGER need to copy .env to dist because secrets are now bundled!
    # But we'll copy .env.sample if it exists
    env_sample = root_dir / ".env.sample"
    if env_sample.exists():
        target_sample = dist_dir / ".env.sample"
        try:
            shutil.copyfile(env_sample, target_sample)
            logger.info(f"   Copied .env.sample to dist (for reference)")
        except Exception as e:
            logger.warning(f"   Failed to copy .env.sample: {e}")
    
    return True


def print_success_message(root_dir: Path):
    """Print success message with next steps."""
    dist_exe = root_dir / "dist" / "server" / "server.exe"
    
    print("\n" + "=" * 60)
    print("🎉 ZERO-CONFIG BUILD SUCCESSFUL!")
    print("=" * 60)
    print(f"\n📁 Executable: {dist_exe}")
    print("\n� Ready to ship! The exe contains all necessary secrets.")
    print("\nℹ️  Models will be auto-downloaded on first run.")
    print("ℹ️  User config (if needed) will be created in %LOCALAPPDATA%\\SparkAI")
    print("\n🚀 To run: cd dist\\server && .\\server.exe")
    print("=" * 60 + "\n")


def build(clean: bool = True, verify_only: bool = False):
    """Main build function."""
    root_dir = get_project_root()
    os.chdir(root_dir)
    
    print("\n" + "=" * 60)
    print("🔧 Spark.AI Server Build Script (Zero-Config)")
    print("=" * 60)
    logger.info(f"Working directory: {root_dir}")

    # Locate venv Python
    venv_python = get_venv_python(root_dir)
    if venv_python:
        logger.info(f"Using .venv Python: {venv_python}")
        python_cmd = venv_python
    else:
        logger.warning("⚠️  Could not find .venv. Using system Python.")
        python_cmd = sys.executable

    # Verify dependencies
    if not verify_dependencies(python_cmd):
        logger.error("\n❌ Missing dependencies. Please install them and try again.")
        sys.exit(1)
    
    # Check torch device
    verify_torch_device(python_cmd)
    
    if verify_only:
        logger.info("\n✅ Verification complete. Skipping build (--verify-only)")
        return

    # Encrypt secrets (CRITICAL STEP)
    if not encrypt_secrets(python_cmd, root_dir):
        logger.error("❌ Aborting build due to encryption failure")
        sys.exit(1)

    # Clean previous builds
    if clean:
        clean_build_artifacts(root_dir)

    # Run PyInstaller
    if not run_pyinstaller(python_cmd, root_dir):
        sys.exit(1)

    # Post-build setup
    if not post_build_setup(root_dir):
        sys.exit(1)

    # Success message
    print_success_message(root_dir)


def main():
    parser = argparse.ArgumentParser(
        description="Build the Spark.AI server executable"
    )
    parser.add_argument(
        "--clean", 
        action="store_true", 
        default=True,
        help="Clean build artifacts before building (default: True)"
    )
    parser.add_argument(
        "--no-clean", 
        action="store_true",
        help="Skip cleaning build artifacts"
    )
    parser.add_argument(
        "--verify-only", 
        action="store_true",
        help="Only verify dependencies, don't build"
    )
    
    args = parser.parse_args()
    
    clean = not args.no_clean
    build(clean=clean, verify_only=args.verify_only)


if __name__ == "__main__":
    main()
