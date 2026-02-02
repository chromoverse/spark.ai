import inspect
try:
    from huggingface_hub import snapshot_download
    print(f"Signature: {inspect.signature(snapshot_download)}")
    try:
        import huggingface_hub
        print(f"Version: {huggingface_hub.__version__}")
    except:
        pass
except ImportError:
    print("huggingface_hub not installed")
