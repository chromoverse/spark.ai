from pydantic import BaseModel, Field, field_validator
from bson import ObjectId
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import EmailStr
from . import CamelModel

# Base model with ALL fields (for internal use/database)
class UserModel(CamelModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None
    last_active_at: Optional[datetime] = None

    is_user_verified: bool = False
    verification_token: Optional[str] = None
    verification_token_expires: Optional[datetime] = None
    refresh_token: Optional[str] = None  # ⚠️ never expose

    # --- API KEYS ---
    gemini_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    is_gemini_api_quota_reached: bool = False
    is_openrouter_api_quota_reached: bool = False

    # --- UTM / Tracking ---
    advertiser_partner: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None

    # --- Preferences ---
    accepts_promotional_emails: bool = False
    language: str = "en"
    ai_gender: str = "male"
    theme: str = "light"
    notifications_enabled: bool = True

    categories_of_interest: List[str] = Field(default_factory=list)
    favorite_brands: List[str] = Field(default_factory=list)

    # --- Likes / Habits ---
    liked_items: List[str] = Field(default_factory=list)
    disliked_items: List[str] = Field(default_factory=list)
    activity_habits: Dict[str, Any] = Field(default_factory=dict)
    behavioral_tags: List[str] = Field(default_factory=list)

    # --- Memories ---
    personal_memories: List[Dict[str, Any]] = Field(default_factory=list)
    reminders: List[Dict[str, Any]] = Field(default_factory=list)

    # --- Metrics ---
    session_count: int = 0
    preferences_history: List[Dict[str, Any]] = Field(default_factory=list)

    # --- Misc ---
    custom_attributes: Dict[str, Any] = Field(default_factory=dict)

# update user model
class UserUpdateQuery(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None

    gemini_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None

    accepts_promotional_emails: Optional[bool] = None
    language: Optional[str] = None
    ai_gender: Optional[str] = None
    theme: Optional[str] = None
    notifications_enabled: Optional[bool] = None

    categories_of_interest: Optional[List[str]] = None
    favorite_brands: Optional[List[str]] = None

    liked_items: Optional[List[str]] = None
    disliked_items: Optional[List[str]] = None
    activity_habits: Optional[Dict[str, Any]] = None
    behavioral_tags: Optional[List[str]] = None

    personal_memories: Optional[List[Dict[str, Any]]] = None
    reminders: Optional[List[Dict[str, Any]]] = None

    custom_attributes: Optional[Dict[str, Any]] = None


# Response model for API endpoints (excludes sensitive data)
class UserResponse(CamelModel):
    id: str = Field(..., alias="_id")
    username: Optional[str] = None
    email: Optional[EmailStr] = None

    created_at: datetime
    last_login: Optional[datetime] = None
    last_active_at: Optional[datetime] = None

    is_user_verified: bool

    # --- Quota Flags ---
    is_gemini_api_quota_reached: bool
    is_openrouter_api_quota_reached: bool

    # --- Preferences ---
    accepts_promotional_emails: bool
    language: str
    ai_gender: str
    theme: str
    notifications_enabled: bool

    categories_of_interest: List[str]
    favorite_brands: List[str]

    # --- Likes / Habits ---
    liked_items: List[str]
    disliked_items: List[str]
    activity_habits: Dict[str, Any]
    behavioral_tags: List[str]

    # --- Memories ---
    personal_memories: List[Dict[str, Any]]
    reminders: List[Dict[str, Any]]

    # --- Metrics ---
    preferences_history: List[Dict[str, Any]]

    # --- Misc ---
    custom_attributes: Dict[str, Any]

    # Auto-convert ObjectId to string
    @field_validator('id', mode='before')
    @classmethod
    def convert_objectid_to_str(cls, v):
        if isinstance(v, ObjectId):
            return str(v)
        return v
# Minimal response for list endpoints or when you need less data
class UserMinimalResponse(CamelModel):
    id: str = Field(..., alias="_id")
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    theme: str = "light"
    language: str = "en"