from pydantic import BaseModel, Field
from typing import List, Optional, Dict

class Token(BaseModel):
  access_token: str
  token_type: str

class VerifyTokenData(BaseModel):
  otp: str
  email: str  
class LoginData(BaseModel):
  email: str  

class APIKeys(BaseModel):
  openrouter_api_key: str
  gemini_api_key: str  

class RefreshTokenRequest(BaseModel):
    refresh_token: str  