from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from . import CamelModel


class OAuthTokenModel(CamelModel):
    """Stored in MongoDB collection: oauth_tokens"""
    user_id: str
    service: str                          # 'gmail' | 'slack' | 'github' | ...
    account_email: Optional[str] = None   # which google account was connected
    refresh_token: str                    # AES-256 encrypted before storing
    scope: Optional[str] = None           # scopes granted by user
    is_active: bool = True
    connected_at: datetime = Field(default_factory=datetime.utcnow)
    last_refreshed: Optional[datetime] = None


class OAuthTokenResponse(BaseModel):
    """Safe public response — never exposes tokens"""
    user_id: str
    service: str
    account_email: Optional[str]
    scope: Optional[str]
    is_active: bool
    connected_at: datetime