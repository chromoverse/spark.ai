#!/usr/bin/env python
"""
Encrypt Secrets Script
======================
Run this BEFORE building the exe to encrypt your .env file.

Usage:
    python script/encrypt_secrets.py

This will:
1. Read .env from server root
2. Encrypt all values
3. Save to app/encrypted_defaults.json (bundled with exe)
"""
import sys
import json
from pathlib import Path

# Add parent to path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.security.crypto import encrypt_dict


def main():
    root_dir = Path(__file__).parent.parent
    env_file = root_dir / ".env"
    output_file = root_dir / "encrypted_defaults.json"
    
    if not env_file.exists():
        print(f"❌ .env file not found at {env_file}")
        sys.exit(1)
    
    print(f"📖 Reading secrets from {env_file}")
    
    # Parse .env file
    secrets = {}
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            # Skip lines without =
            if '=' not in line:
                continue
            
            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip()
            
            if key and value:
                secrets[key] = value
    
    print(f"   Found {len(secrets)} secrets")
    
    # Encrypt all values
    print("🔐 Encrypting secrets...")
    encrypted = encrypt_dict(secrets)
    
    # Save to JSON
    with open(output_file, 'w') as f:
        json.dump(encrypted, f, indent=2)
    
    print(f"✅ Encrypted secrets saved to {output_file}")
    print("\n📦 Now run build_server.py to create the exe")


if __name__ == "__main__":
    main()
