from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.sessions import check_session
from app.core.errors import SIGN_IN_AGAIN, ApiError
from app.core.logging import device_id_var, user_id_var
from app.core.runtime import Runtime
from app.core.security import Principal, decode_access


def get_rt(request: Request) -> Runtime:
    rt: Runtime = request.app.state.rt
    return rt


async def get_db(rt: Annotated[Runtime, Depends(get_rt)]) -> AsyncIterator[AsyncSession]:
    async with rt.db() as session:
        yield session


async def get_principal(
    request: Request,
    rt: Annotated[Runtime, Depends(get_rt)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Principal:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError("unauthorized", SIGN_IN_AGAIN)
    p = decode_access(rt.settings, rt.clock, token)
    await check_session(rt, db, p)
    user_id_var.set(str(p.user_id))
    device_id_var.set(str(p.device_id))
    return p


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


Rt = Annotated[Runtime, Depends(get_rt)]
Db = Annotated[AsyncSession, Depends(get_db)]
Me = Annotated[Principal, Depends(get_principal)]
