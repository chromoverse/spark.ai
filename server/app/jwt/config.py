from datetime import datetime, timedelta, timezone
from jose import jwt
import hashlib
from passlib.context import CryptContext

SECRET_KEY = "spark-secret-key-for-jwt-token-signing-123456"
ALGO = "HS256"
ISSUER = "Spark Industries"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str):
    password = hashlib.sha256(password.encode()).hexdigest()
    return pwd_context.hash(password)

def verify_password(plain, hashed):
    plain = hashlib.sha256(plain.encode()).hexdigest()
    return pwd_context.verify(plain, hashed)

def create_token(user_id: str, token_type: str, expires_in: int):
    now = datetime.now(timezone.utc)

    payload = {
        "sub": user_id,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_in)).timestamp()),
        "iss": ISSUER,
    }

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGO)

def create_access_token(user_id: str):
    return create_token(user_id, "access", 30)

def create_refresh_token(user_id: str):
    return create_token(user_id, "refresh", 60 * 24 * 7)

def decode_token(token: str):
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGO], issuer=ISSUER)