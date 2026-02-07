from pydantic import BaseModel, ConfigDict
from typing import Any


def to_camel(string: str) -> str:
    parts = string.split("_")
    return parts[0] + "".join(word.capitalize() for word in parts[1:])


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True
    )

from .pqh_response_model import CognitiveState, PQHResponse
from .chat_model import ChatModel
from .user_model import UserModel 