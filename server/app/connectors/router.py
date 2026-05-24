"""
Connector API routes — frontend-facing.

These endpoints power the "Connected Services" UI in Spark.
"""
from fastapi import APIRouter

from app.connectors.registry import (
    get_all_connector_statuses,
    get_connector_status,
    get_connector,
    list_connectors,
)

router = APIRouter(prefix="/connectors", tags=["Connectors"])


@router.get("/list")
async def list_all_connectors(user_id: str):
    """
    Return all available connectors with their connection status.
    Frontend uses this to render the Connected Services grid.
    """
    return await get_all_connector_statuses(user_id)


@router.get("/{connector_id}/status")
async def connector_status(connector_id: str, user_id: str):
    """Check if a specific connector is connected for this user."""
    return await get_connector_status(user_id, connector_id)


@router.get("/{connector_id}/capabilities")
async def connector_capabilities(connector_id: str):
    """Return what a connector can do (for tool selection logic)."""
    connector = get_connector(connector_id)
    return {
        "id": connector.id,
        "capabilities": connector.capabilities,
        "scopes_display": connector.scopes_display,
    }
