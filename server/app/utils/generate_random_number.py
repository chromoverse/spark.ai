import secrets

def generate_otp(length: int = 6) -> str:
    """Generate a cryptographically secure OTP."""
    return ''.join(secrets.choice('0123456789') for _ in range(length))