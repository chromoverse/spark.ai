from fastapi import Request, HTTPException, status, Depends
from jose import JWTError
from bson import ObjectId
from app.utils.serialize_mongo_doc import serialize_doc

from app.jwt.config import decode_token
from app.db.mongo import get_db

async def get_current_user(request: Request, db=Depends(get_db)):
    token = request.cookies.get("access_token") or request.headers.get("Authorization") or request.query_params.get("access_token")

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if token.startswith("Bearer "):
        token = token.split(" ")[1]

    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # ✅ enforce access token
    if payload.get("type") != "access":
        raise HTTPException(status_code=403, detail="Access token required")

    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    # ✅ fetch user from MongoDB
    user = await db.users.find_one({"_id": ObjectId(user_id)})

    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    
    # ✅ attach full user to request
    request.state.user = user

    return user
