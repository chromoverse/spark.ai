from fastapi.encoders import jsonable_encoder
from typing import Any, Dict
from fastapi import APIRouter, Body,Depends,  Query,Request
from app.cache import get_user_details, set_user_details, update_user_details
from app.db.mongo import get_db
from app.utils.serialize_mongo_doc import serialize_doc
from app.models.user_model import UserModel , UserResponse, UserUpdateQuery
from app.schemas import auth_schema
from app.dependencies.auth import get_current_user
from app.jwt.config import create_access_token,create_refresh_token
from app.helper.email_validation import is_valid_email
from app.helper.response_helper import send_response, send_error
from bson import ObjectId
from datetime import datetime,timezone,timedelta
from app.utils.generate_random_number import generate_otp
from app.emails import verification_email
from pymongo import ReturnDocument

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])

@router.post("/register")
async def register_user(request: Request, user: UserModel):
    if not user.email or not is_valid_email(user.email):
        return send_error(
            message="Email address is required or Invalid email address",
            status_code=400
        )

    db = get_db()

    # 1️⃣ Check if user already exists
    existing_user = await db.users.find_one({"email": user.email})

    if existing_user and existing_user["is_user_verified"] == True:
        return send_error(
            message="User with this email already exists",
            status_code=409
        )
    
    if existing_user and existing_user["is_user_verified"] == False:
        new_otp = generate_otp(6)
        updated_user = await db.users.find_one_and_update(
            {"_id": existing_user["_id"]},
             {"$set": 
                {
                "last_login": datetime.now(timezone.utc),
                "verification_token": new_otp,
                "verification_token_expires": datetime.now(timezone.utc) + timedelta(minutes=10)
                }
            },
            return_document=ReturnDocument.AFTER
        )

        # Serialize for JSON (ObjectId + datetime)
        user_doc = serialize_doc(updated_user)

        # Send verification email
        verification_email.send(
        to_email=user.email,
        user_name=updated_user["username"],
        otp_code=new_otp,
        )

        # Send response with tokens
        return send_response(
            request=request,
            data={
                "user": user_doc,
                "emailStatus" : "Verification Token Sent"
            },
            message="User registered successfully",
            status_code=201
        )


    # create new user if no existing user
    try:
        user.username = user.email.split("@")[0]
        result = await db.users.insert_one(user.model_dump())
        if not result.inserted_id:
            return send_error(
                message="Failed to register user",
                status_code=500
            )

        user_id = str(result.inserted_id)

        # generate otp code for verification
        otp_code = generate_otp(6)

        # Update user document with refresh_token
        user_doc = await db.users.find_one_and_update(
            {"_id": ObjectId(user_id)},
            {"$set": 
                {
                "last_login": datetime.now(timezone.utc),
                "verification_token": otp_code,
                "verification_token_expires": datetime.now(timezone.utc) + timedelta(minutes=10)
                }
            },
            return_document=ReturnDocument.AFTER
        )

        # Serialize for JSON (ObjectId + datetime)
        user_doc = serialize_doc(user_doc)

        # Send verification email
        verification_email.send(
        to_email=user.email,
        user_name=user.username,
        otp_code=otp_code,
        )

        # Send response with tokens
        return send_response(
            request=request,
            data={
                "user": user_doc,
                "emailStatus" : "Verification Token Sent"
            },
            message="User registered successfully",
            status_code=201
        )

    except Exception as e:
        return send_error(
            message="Failed to register user",
            status_code=500,
            errors=str(e)
        )


# This route is for verifying otp either verifying the user's email for the first time or login verification
@router.post("/verify-otp")
async def verify_otp_code(request: Request, data : auth_schema.VerifyTokenData):
    if not data.email or not is_valid_email(data.email):
        return send_error(
            message="Email address is required or Invalid email address",
            status_code=400
        )
    
    if not data.otp or len(data.otp) != 6:
        return send_error(
            message="OTP is required and should be 6 digits",
            status_code=400
        )

    # get db connection
    db = get_db()
    user = await db.users.find_one({"email": data.email})

    if not user:
        return send_error(
            message="User not found",
            status_code=404
        )

    if not user["verification_token"] or not user["verification_token_expires"]:
        return send_error(
            message="Verification token not found",
            status_code=400
        )

    if user["verification_token"] != data.otp:
        return send_error(
            message="Invalid verification token",
            status_code=400
        )
    
    current_time = datetime.now(timezone.utc)
    expires_time = user["verification_token_expires"]
    if expires_time.tzinfo is None:
        expires_time = expires_time.replace(tzinfo=timezone.utc)

    if expires_time < current_time:
        return send_error(
            message="Verification token has expired",
            status_code=400
        )

    user_id = str(user["_id"])
    access_token = create_access_token(user_id)
    refresh_token = create_refresh_token(user_id)

    user_doc = await db.users.find_one_and_update(
        {"_id": ObjectId(user["_id"])},
        {"$set": 
                { 
                "refresh_token": refresh_token,
                "last_login": datetime.now(timezone.utc),
                "verification_token_expires": None,
                "is_user_verified": True
                }
            },
            return_document=ReturnDocument.AFTER 
    )

    user_doc = serialize_doc(user_doc)

    return send_response(
        request=request,
        data=user_doc,
        access_token=access_token,
        refresh_token=refresh_token,
        message="User verified successfully",
        status_code=200
    )


@router.post("/sign-in", response_model = UserResponse)
async def login(request: Request, user: auth_schema.LoginData):
    if not user.email or not is_valid_email(user.email):
        return send_error(
            message="Email address is required or Invalid email address",
            status_code=400
        )

    db = get_db()

    # 1️⃣ Check if user already exists
    existing_user = await db.users.find_one({"email": user.email})

    if not existing_user:
        return send_error(
            message="User not found",
            status_code=404
        )
    
    # send verification email for login
    try:
        otp_code = generate_otp(6)

        # Update user document for otp
        user_doc = await db.users.find_one_and_update(
            {"_id": existing_user["_id"]},
            {"$set": 
                {
                "last_login": datetime.now(timezone.utc),
                "verification_token": otp_code,
                "verification_token_expires": datetime.now(timezone.utc) +      timedelta(minutes=10)
                }
            },
            return_document=ReturnDocument.AFTER
        )

        # Serialize for JSON (ObjectId + datetime)
        user_doc = serialize_doc(user_doc)

        # Send verification email
        verification_email.send(
        to_email=existing_user["email"],
        user_name=existing_user["username"],
        otp_code=otp_code,
        )

        # Send response with tokens
        return send_response(
            request=request,
            data={
                "user": "Verification OTP Email Sent Successfully",
                "emailStatus" : "Verification Token Sent",
                "user" :  user_doc
            },
            message="User Signed In Successfully. Verify OTP to continue",
            status_code=201
        )

    except Exception as e:
        return send_error(
            message="Failed to register user",
            status_code=500,
            errors=str(e)
        )


# This route is for inserting api keys
@router.post("/insert-api-keys")
async def insert_keys(request:Request ,payload: auth_schema.APIKeys, user = Depends(get_current_user)):
    from app.cache import set_user_details
    db= get_db()
    print("user from middlware",user, "type of user",type(user))
    updated_user = await db.users.find_one_and_update(
        {"_id": ObjectId(user["_id"])},
        {"$set": {
            "openrouter_api_key": payload.openrouter_api_key,
            "gemini_api_key": payload.gemini_api_key
        }},
        return_document=ReturnDocument.AFTER
    )

    updated_user = serialize_doc(updated_user)
    print("updated_user",updated_user)
    await set_user_details(updated_user["_id"],updated_user)
    return send_response(
        request=request,
        data=updated_user,
        message="API keys updated successfully",
        status_code=200
    )


# This route is for updating user details
@router.patch("/update-user-details")
async def update_user_details_endpoint(
    request: Request,
    user_id: str = Query(
        ...,
        alias="userId",
        max_length=24,
        regex="^[a-f0-9]{24}$",
    ),
    payload: Dict[str, Any] = Body(...),
    user=Depends(get_current_user)
):
    if not user:
        return send_error("User not found", 404)

    try:
        object_id = ObjectId(user_id)
    except Exception:
        return send_error("Invalid user ID format", 400)

    protected_fields = {
        "_id",
        "created_at",
        "email",
        "refresh_token",
        "verification_token",
        "verification_token_expires",
        "session_count",
    }

    # Remove nulls & protected fields
    update_data = {
        k: v for k, v in payload.items()
        if v is not None and k not in protected_fields
    }

    if not update_data:
        return send_error("No valid fields to update", 400)
    print("update fields", update_data)
    # Optional validation against UserModel
    valid_fields = set(UserModel.model_fields.keys())
    print("valid fields", valid_fields)
    invalid_fields = set(update_data.keys()) - valid_fields
    if invalid_fields:
        return send_error(
            f"Invalid fields: {', '.join(invalid_fields)}",
            400
        )

    update_data["last_active_at"] = datetime.now(timezone.utc).isoformat()
    print("Updated data", update_data)

    db = get_db()
    updated_user = await db.users.find_one_and_update(
        {"_id": object_id},
        {"$set": update_data},
        return_document=ReturnDocument.AFTER
    )

    if not updated_user:
        return send_error("User not found", 404)

    updated_user = serialize_doc(updated_user)
    updated_user.pop("refresh_token", None)
    updated_user.pop("verification_token", None)

    return send_response(
        request=request,
        data=updated_user,
        message="User updated successfully",
        status_code=200
    )


## this route is for auto rotating the refresh and access_token
@router.post("/refresh-token")
async def refresh_access_token_endpoint(request: Request, body: auth_schema.RefreshTokenRequest):
    refresh_token = body.refresh_token
    if not refresh_token:
        return send_error(message="Refresh token is required", status_code=400)
    
    from app.jwt import config as jwt_config
    from jose.exceptions import JWTError, JWSError
    
    # Validate token format and decode with error handling
    try:
        jwt_doc = jwt_config.decode_token(refresh_token)
    except (JWTError, JWSError, ValueError, Exception) as e:
        # Token is malformed or invalid
        return send_error(message="Invalid or malformed refresh token", status_code=401)

    # Check if token is valid and is a refresh token
    if not jwt_doc or jwt_doc.get("type") != "refresh":
        return send_error(message="Invalid refresh token", status_code=401)

    user_id = jwt_doc["sub"]
    access_token = jwt_config.create_access_token(user_id)
    new_refresh_token = jwt_config.create_refresh_token(user_id)
    db = get_db()

    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"refresh_token": new_refresh_token}}
    )    
    
    return send_response(
        request=request,
        data={
            "access_token": access_token,
            "refresh_token": "Refresh Token is not sent for security reasons but we have set it everywhere as needed. Contact us if you need it.",
        },
        access_token=access_token,
        refresh_token=new_refresh_token,  # Fixed: should be new_refresh_token, not refresh_token
        message="Token refreshed successfully",
        status_code=200
    )


# get-user
@router.get("/get-me")
async def get_me_endpoint(request: Request, user=Depends(get_current_user)):
    print("user before serializing -------------- ", user)
    user_model = UserResponse(**user)
    print("user after model serializing -------------- ", user_model)

    user_dict = jsonable_encoder(user_model)
    print("user after jsonable_encoder -------------- ", user_dict)
    return send_response (
        request=request,
        data=user_dict,
        message="User details",
        status_code=200
    )

@router.get("/get-users")
async def get_users():
    db = get_db()
    res = db.users.find({})
    print("users", res)
    return res

@router.get("/load_user", response_model=UserResponse)
async def test_load_user_from_redis(user_id: str):
    from app.cache import load_user
    details = await load_user(user_id)
    if not details:
        # Return empty response for not found
        return UserResponse(
            _id="",
            username=None,
            email=None,
            created_at=datetime.now(),
            last_login=None,
            last_active_at=None,
            is_user_verified=False,
            is_gemini_api_quota_reached=False,
            is_openrouter_api_quota_reached=False,
            accepts_promotional_emails=False,
            language="en",
            ai_gender="male",
            theme="light",
            notifications_enabled=True,
            categories_of_interest=[],
            favorite_brands=[],
            liked_items=[],
            disliked_items=[],
            activity_habits={},
            behavioral_tags=[],
            personal_memories=[],
            reminders=[],
            preferences_history=[],
            custom_attributes={}
        )
    # Convert the dict to UserResponse model for camelCase serialization
    user_response = UserResponse(**details)
    return user_response