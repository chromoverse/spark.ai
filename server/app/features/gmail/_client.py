import logging
from typing import Optional
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from app.features.external_service.token_manager import get_valid_access_token

logger = logging.getLogger(__name__)


async def get_gmail_service(
    user_id: str,
    account_email: Optional[str] = None,
):
    """
    Builds and returns an authenticated Gmail API service object.

    This is the server-side entry point for Gmail-backed tools.
    Tools receive this object as a parameter — they never touch tokens directly.

    Usage in direct tools runtime:
        from app.features.gmail._client import get_gmail_service

        service = await get_gmail_service(user_id)
        # pass `service` into tool functions
    """
    access_token = await get_valid_access_token(
        user_id=user_id,
        service="gmail",
        account_email=account_email,
    )

    if not access_token:
        logger.warning("No access token for user=%s", user_id)
        raise Exception(f"No access token for user {user_id}")

    creds = Credentials(token=access_token)

    if not creds.token:
        logger.warning("No access token for user=%s", user_id)
        raise Exception(f"No access token for user {user_id}")
    
    service = build("gmail", "v1", credentials=creds)

    if not service:
        logger.warning("No access token for user=%s", user_id)
        raise Exception(f"No access token for user {user_id}")

    logger.debug("Gmail service built for user=%s", user_id)
    return service
