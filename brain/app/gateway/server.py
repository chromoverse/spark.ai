"""Socket.IO /v2 (API.md §3). One connection per device, authenticated by access JWT + device_id.

Identity comes only from the token checked at connect and kept in the socket session. Every
device → brain payload is a Pydantic model with extra="forbid", so a client `user_id` is rejected.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import socketio
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from app.agent.voice import Voice
from app.auth.sessions import check_session
from app.core.errors import BAD_INPUT, INTERNAL, SIGN_IN_AGAIN, ApiError, ok
from app.core.logging import device_id_var, trace_id_var, user_id_var
from app.core.runtime import Runtime
from app.core.security import Principal, decode_access
from app.db.models import Device
from app.gateway import live, presence
from app.gateway.envelope import Envelope
from app.gateway.push import NAMESPACE, user_room
from app.gateway.signals import (
    EngineIncident,
    EnginePlan,
    SignalFinal,
    SignalHandledLocally,
    SignalInterrupt,
    SignalPartial,
    SignalTrace,
    ToolResult,
)

logger = logging.getLogger(__name__)


class ConnectAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(max_length=2048)
    device_id: str = Field(max_length=64)


class DeviceHello(Envelope):
    platform: str = Field(max_length=40)
    app_version: str = Field(max_length=40)
    capabilities: list[str] = Field(default_factory=list, max_length=200)
    tool_versions: dict[str, str] = Field(default_factory=dict)
    hardware: dict[str, Any] = Field(default_factory=dict)


# Every device → brain event and its payload model. The X1 sweep walks this table.
EVENT_MODELS: dict[str, type[Envelope]] = {
    "device.hello": DeviceHello,
    "signal.partial": SignalPartial,
    "signal.final": SignalFinal,
    "signal.handled_locally": SignalHandledLocally,
    "signal.interrupt": SignalInterrupt,
    "signal.trace": SignalTrace,
    "tool.result": ToolResult,
    "engine.incident": EngineIncident,
    "device.engine_plan": EnginePlan,
}


def _refuse() -> socketio.exceptions.ConnectionRefusedError:
    # socketio's own exception: (message, data) reaches the client as err.message / err.data.
    # The builtin ConnectionRefusedError would be flattened to a generic message.
    return socketio.exceptions.ConnectionRefusedError(
        "unauthorized", {"code": "unauthorized", "message": SIGN_IN_AGAIN}
    )


def register(rt: Runtime) -> Voice:
    sio = rt.sio
    voice = Voice(rt)
    heartbeats: dict[str, asyncio.Task[None]] = {}

    async def principal_of(sid: str) -> Principal:
        session = await sio.get_session(sid, namespace=NAMESPACE)
        p: Principal = session["principal"]
        return p

    async def connect(sid: str, environ: dict[str, Any], auth: Any) -> None:
        try:
            creds = ConnectAuth.model_validate(auth)
            p = decode_access(rt.settings, rt.clock, creds.token)
            if str(p.device_id) != creds.device_id:
                raise _refuse()
            async with rt.db() as db:
                await check_session(rt, db, p)
        except (ValidationError, ApiError):
            raise _refuse() from None
        await sio.save_session(sid, {"principal": p}, namespace=NAMESPACE)
        await sio.enter_room(sid, user_room(p.user_id), namespace=NAMESPACE)
        await sio.enter_room(sid, live.device_room(p.device_id), namespace=NAMESPACE)
        await presence.touch(rt, p.user_id, p.device_id)
        heartbeats[sid] = asyncio.create_task(heartbeat(sid, p))
        logger.info("device connected", extra={"device": str(p.device_id)})

    async def disconnect(sid: str, reason: Any = None) -> None:
        task = heartbeats.pop(sid, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        try:
            p = await principal_of(sid)
        except KeyError:
            return
        await presence.drop(rt, p.user_id, p.device_id)

    async def heartbeat(sid: str, p: Principal) -> None:
        """Keeps presence fresh and drops the socket within REFRESH_S of its session ending
        (logout, device removed, refresh-token reuse)."""
        while True:
            await rt.clock.sleep(presence.REFRESH_S)
            try:
                async with rt.db() as db:
                    await check_session(rt, db, p)
                await presence.touch(rt, p.user_id, p.device_id)
            except ApiError:
                await sio.disconnect(sid, namespace=NAMESPACE)
                return
            except Exception:
                logger.warning("heartbeat check failed", exc_info=True)

    def on(event: str, fn: Callable[[Principal, Any], Awaitable[dict[str, Any]]]) -> None:
        model = EVENT_MODELS[event]

        async def handler(sid: str, data: Any) -> dict[str, Any]:
            try:
                payload = model.model_validate(data)
            except ValidationError:
                return ApiError("invalid_input", BAD_INPUT).body()
            p = await principal_of(sid)
            trace_id_var.set(payload.trace_id)
            user_id_var.set(str(p.user_id))
            device_id_var.set(str(p.device_id))
            try:
                return ok(await fn(p, payload))
            except ApiError as exc:
                return exc.body()
            except Exception:
                logger.error("socket handler failed", extra={"event": event}, exc_info=True)
                return ApiError("internal", INTERNAL).body()

        sio.on(event, handler, namespace=NAMESPACE)

    async def device_hello(p: Principal, msg: DeviceHello) -> dict[str, Any]:
        async with rt.db() as db:
            device = await db.scalar(
                select(Device).where(Device.id == p.device_id, Device.user_id == p.user_id)
            )
            if device is None:
                raise ApiError("unauthorized", SIGN_IN_AGAIN)
            device.platform = msg.platform
            device.app_version = msg.app_version
            device.capabilities = msg.capabilities
            device.hardware = msg.hardware
            device.last_seen_at = rt.clock.now()
            await db.commit()
        await presence.touch(rt, p.user_id, p.device_id)
        return {"device_id": str(p.device_id), "server_time": rt.clock.epoch_ms()}

    async def engine_plan(p: Principal, msg: EnginePlan) -> dict[str, Any]:
        """Stored on the device row; the Engines page and reply length use it (§18.3)."""
        async with rt.db() as db:
            device = await db.scalar(
                select(Device).where(Device.id == p.device_id, Device.user_id == p.user_id)
            )
            if device is None:
                raise ApiError("unauthorized", SIGN_IN_AGAIN)
            device.engine_plan = msg.model_dump(exclude={"v", "id", "ts", "trace_id"})
            await db.commit()
        return {"stored": True}

    sio.on("connect", connect, namespace=NAMESPACE)
    sio.on("disconnect", disconnect, namespace=NAMESPACE)
    on("device.hello", device_hello)
    on("signal.partial", voice.partial)
    on("signal.final", voice.final)
    on("signal.handled_locally", voice.handled_locally)
    on("signal.interrupt", voice.interrupt)
    on("signal.trace", voice.trace)
    on("tool.result", voice.tool_result)
    on("engine.incident", voice.engine_incident)
    on("device.engine_plan", engine_plan)
    return voice
