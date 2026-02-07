"""
Test script for ModelManager
Run this to verify everything works
"""

from model_manager import ModelManager

def test_model_manager():
    print("🚀 Testing Model Manager\n")
    
    # Initialize
    manager = ModelManager("model_config.json")
    
    # Check what device was detected
    print(f"Detected Device: {manager.device_type.upper()}\n")
    
    # Get model info without downloading
    info = manager.get_model_info("qwen2.5-7b")
    
    print("📊 Model Information:")
    print(f"  - Path: {info['path']}")
    print(f"  - Exists: {'✅ Yes' if info['exists'] else '❌ No'}")
    print(f"  - Size: ~{info['size_gb']} GB")
    print(f"  - Quantization: {info['quantization']}")
    print(f"  - Device: {info['device'].upper()}\n")
    
    # Attempt to get model (will prompt to download if missing)
    if not info['exists']:
        print("⚠️  Model not found. Starting download process...\n")
    
    try:
        model_path = manager.get_model_path("qwen2.5-7b")
        print(f"\n✅ Model ready at: {model_path}")
        return True
    except FileNotFoundError as e:
        print(f"\n❌ Error: {e}")
        return False

if __name__ == "__main__":
    success = test_model_manager()
    
    if success:
        print("\n" + "="*50)
        print("✅ ALL TESTS PASSED")
        print("="*50)
    else:
        print("\n" + "="*50)
        print("❌ TEST FAILED")
        print("="*50)