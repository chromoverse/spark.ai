from pydantic import BaseModel, ConfigDict
from typing import Any
from importlib import import_module


def to_camel(string: str) -> str:
    parts = string.split("_")
    return parts[0] + "".join(word.capitalize() for word in parts[1:])


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True
    )


__all__ = [
    "Any",
    "BaseModel",
    "CamelModel",
    "ChatModel",
    "CognitiveState",
    "ConfigDict",
    "PQHResponse",
    "UserModel",
    "to_camel",
]


_LAZY_EXPORTS = {
    "CognitiveState": "app.models.pqh_response_model",
    "PQHResponse": "app.models.pqh_response_model",
    "ChatModel": "app.models.chat_model",
    "UserModel": "app.models.user_model",
}


def __getattr__(name: str):
    module_name = _LAZY_EXPORTS.get(name)
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
