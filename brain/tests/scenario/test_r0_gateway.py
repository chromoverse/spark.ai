"""R0 acceptance: device registration, device.hello, presence, settings.changed fan-out,
and socket auth. # proves §9, §10, §12, §26.1"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import socketio

from tests.conftest import Brain
from tests.fakes.device import FakeDevice

pytestmark = pytest.mark.scenario


@pytest.fixture
async def devices(brain: Brain) -> AsyncIterator[list[FakeDevice]]:
    made: list[FakeDevice] = []
    yield made
    for d in made:
        await d.close()


def _device(brain: Brain, made: list[FakeDevice], tokens: dict) -> FakeDevice:  # type: ignore[type-arg]
    d = FakeDevice(brain.url, tokens)
    made.append(d)
    return d


async def test_r0_two_devices_both_receive_settings_changed(
    brain: Brain, devices: list[FakeDevice]
) -> None:
    laptop_t = await brain.sign_in("asha@example.com", "Laptop")
    desktop_t = await brain.sign_in("asha@example.com", "Desktop")
    other_t = await brain.sign_in("ben@example.com", "Ben's laptop")
    assert laptop_t["user"]["id"] == desktop_t["user"]["id"] != other_t["user"]["id"]

    laptop, desktop, other = (_device(brain, devices, t) for t in (laptop_t, desktop_t, other_t))
    for d in (laptop, desktop, other):
        await d.connect()
        assert (await d.hello())["ok"] is True

    r = await brain.client.patch(
        "/v2/settings", json={"verbosity": "brief"}, headers=brain.auth(laptop_t)
    )
    assert r.status_code == 200 and r.json()["data"]["verbosity"] == "brief"

    for d in (laptop, desktop):
        event = await d.next("settings.changed")
        assert event["changed"] == {"verbosity": "brief"}
        assert event["v"] == 2 and event["id"].isdigit() and event["ts"] > 0
    with pytest.raises(TimeoutError):
        await other.next("settings.changed", within=0.3)


async def test_r0_refresh_token_cannot_open_a_socket(
    brain: Brain, devices: list[FakeDevice]
) -> None:
    tokens = await brain.sign_in()
    second = await brain.sign_in(device="Desktop")
    d = _device(brain, devices, tokens)
    bad_auths = [
        {"token": tokens["refresh_token"], "device_id": tokens["device_id"]},
        {"token": tokens["access_token"], "device_id": second["device_id"]},  # not this token's
        {"token": tokens["access_token"], "device_id": tokens["device_id"], "user_id": "x"},
        {},
    ]
    for auth in bad_auths:
        with pytest.raises(socketio.exceptions.ConnectionError):
            await d.connect(auth=auth)
    await d.connect()
    assert d.sio.connected


async def test_device_hello_registers_device_and_presence(
    brain: Brain, devices: list[FakeDevice]
) -> None:
    tokens = await brain.sign_in()
    d = _device(brain, devices, tokens)
    await d.connect()
    ack = await d.hello(capabilities=["apps", "media"], hardware={"ram_gb": 32})
    assert ack["data"]["device_id"] == tokens["device_id"]

    r = await brain.client.get("/v2/devices", headers=brain.auth(tokens))
    [item] = r.json()["data"]["items"]
    assert item["online"] and item["current"] and item["name"] == "Laptop"
    assert item["capabilities"] == ["apps", "media"] and item["platform"] == "win32"

    await d.close()
    await asyncio.sleep(0.2)  # the server handles the disconnect asynchronously
    r = await brain.client.get("/v2/devices", headers=brain.auth(tokens))
    assert r.json()["data"]["items"][0]["online"] is False


async def test_hello_rejects_client_identity_and_bad_envelopes(
    brain: Brain, devices: list[FakeDevice]
) -> None:
    d = _device(brain, devices, await brain.sign_in())
    await d.connect()
    for bad in ({"user_id": "someone-else"}, {"v": 1}, {"capabilities": "apps"}):
        ack = await d.hello(**bad)
        assert ack["ok"] is False and ack["error"]["code"] == "invalid_input", bad


async def test_socket_dropped_after_logout(brain: Brain, devices: list[FakeDevice]) -> None:
    tokens = await brain.sign_in()
    d = _device(brain, devices, tokens)
    await d.connect()
    await brain.client.post("/v2/auth/logout", headers=brain.auth(tokens))
    brain.clock.advance(30)  # next presence heartbeat re-checks the session
    await asyncio.wait_for(d.disconnected.wait(), 3)


async def test_settings_patch_rules(brain: Brain, devices: list[FakeDevice]) -> None:
    tokens = await brain.sign_in()
    d = _device(brain, devices, tokens)
    await d.connect()
    h = brain.auth(tokens)

    r = await brain.client.patch("/v2/settings", json={"language": "hi"}, headers=h)
    assert r.status_code == 422
    assert r.json()["error"]["message"].startswith("English is all I speak for now")
    assert (
        await brain.client.patch("/v2/settings", json={"language": None}, headers=h)
    ).status_code == 422

    r = await brain.client.patch(
        "/v2/settings", json={"voice": "tara", "address_as": "boss"}, headers=h
    )
    assert (await d.next("settings.changed"))["changed"] == {"voice": "tara", "address_as": "boss"}
    r = await brain.client.patch("/v2/settings", json={"voice": None}, headers=h)
    assert r.json()["data"]["voice"] is None
    assert (await d.next("settings.changed"))["changed"] == {"voice": None}

    await brain.client.patch("/v2/settings", json={"address_as": "boss"}, headers=h)  # no-op
    with pytest.raises(TimeoutError):
        await d.next("settings.changed", within=0.3)
    assert (await brain.client.get("/v2/settings", headers=h)).json()["data"][
        "address_as"
    ] == "boss"


async def test_devices_defaults_and_removal(brain: Brain) -> None:
    laptop = await brain.sign_in(device="Laptop")
    desktop = await brain.sign_in(device="Desktop")
    h = brain.auth(laptop)

    r = await brain.client.patch(
        f"/v2/devices/{desktop['device_id']}", json={"is_default_for": ["laptop"]}, headers=h
    )
    assert r.json()["data"]["is_default_for"] == ["laptop"]
    r = await brain.client.patch(
        f"/v2/devices/{laptop['device_id']}",
        json={"is_default_for": ["laptop"], "name": "Work laptop"},
        headers=h,
    )
    assert r.json()["data"]["name"] == "Work laptop"
    items = {
        i["id"]: i
        for i in (await brain.client.get("/v2/devices", headers=h)).json()["data"]["items"]
    }
    assert items[desktop["device_id"]]["is_default_for"] == []  # moved, not duplicated

    r = await brain.client.delete(f"/v2/devices/{desktop['device_id']}", headers=h)
    assert r.status_code == 200
    r = await brain.client.post(
        "/v2/auth/refresh", json={"refresh_token": desktop["refresh_token"]}
    )
    assert r.status_code == 401
    assert len((await brain.client.get("/v2/devices", headers=h)).json()["data"]["items"]) == 1
