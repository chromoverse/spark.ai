# -*- mode: python ; coding: utf-8 -*-
"""
Spark.AI Server PyInstaller Spec
================================
Comprehensive build spec with ALL required modules and proper torch DLL handling.
"""
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

# Get torch lib path for DLL fix
import torch
torch_lib_path = os.path.join(os.path.dirname(torch.__file__), 'lib')

datas = [
    ('app', 'app'),
    ('public', 'public'),
    ('initialization.md', '.'),
    ('encrypted_defaults.json', '.'),
    ('hooks', 'hooks'),
]

# Explicitly add torch lib binaries
binaries = []
if os.path.exists(torch_lib_path):
    for dll in os.listdir(torch_lib_path):
        if dll.endswith('.dll'):
            binaries.append((os.path.join(torch_lib_path, dll), 'torch/lib'))

# ALL hidden imports - comprehensive list
hiddenimports = [
    # Uvicorn
    'uvicorn', 'uvicorn.logging', 'uvicorn.lifespan', 'uvicorn.lifespan.off', 
    'uvicorn.lifespan.on', 'uvicorn.protocols', 'uvicorn.protocols.http',
    'uvicorn.protocols.websockets',
    # FastAPI
    'fastapi', 'starlette',
    # Pydantic
    'pydantic', 'pydantic_settings', 'pydantic_core',
    # SocketIO
    'engineio', 'engineio.async_drivers', 'engineio.async_drivers.aiohttp',
    'socketio', 'python_socketio', 'python_engineio',
    # Database/Cache
    'upstash_redis', 'upstash_redis.asyncio', 'redis', 'pymongo', 'motor',
    # ML/AI  
    'torch', 'torchaudio', 'torchvision',
    'transformers', 'transformers.models',
    'sentence_transformers',
    'faster_whisper', 'ctranslate2',
    'huggingface_hub',
    'onnxruntime',
    # ChromaDB
    'chromadb', 'chromadb.telemetry', 'chromadb.telemetry.product',
    'chromadb.telemetry.product.posthog',
    # Sklearn
    'sklearn', 'sklearn.utils', 'sklearn.utils._cython_blas',
    'sklearn.neighbors', 'sklearn.neighbors.typedefs', 'sklearn.neighbors.quad_tree',
    'sklearn.tree', 'sklearn.tree._utils',
    # Pinecone
    'pinecone',
    # Utils
    'json_repair',
    'cryptography', 'cryptography.fernet',
    'dotenv', 'python_dotenv',
    # Google
    'google', 'google.generativeai', 'google.ai',
    # OpenAI/OpenRouter
    'openai', 'httpx',
    # Audio
    'elevenlabs', 'gtts', 'pyttsx3', 'pygame',
    # Other
    'PIL', 'numpy', 'scipy',
]

# Collect ALL for critical packages
packages_to_collect = [
    'torch', 'torchaudio',
    'transformers', 
    'sentence_transformers',
    'faster_whisper',
    'chromadb',
    'langchain',
    'pydantic_settings',
    'upstash_redis',
    'json_repair',
    'pinecone',
    'huggingface_hub',
    'google.generativeai',
    'elevenlabs',
    'onnxruntime',
    'ctranslate2',
]

for pkg in packages_to_collect:
    try:
        tmp = collect_all(pkg)
        datas += tmp[0]
        binaries += tmp[1]
        hiddenimports += tmp[2]
    except Exception as e:
        print(f"Warning: Could not collect {pkg}: {e}")

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['hooks/hook-torch-dll.py'],
    excludes=['matplotlib', 'tkinter', 'PyQt5', 'PySide2', 'ipython', 'notebook'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='server',
)
