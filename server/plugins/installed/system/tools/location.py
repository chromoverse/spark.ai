"""Location tool — IP geolocation."""
import urllib.request
import json
from typing import Dict, Any
from datetime import datetime

from app.plugins.tools.tool_base import BaseTool, ToolOutput


class CurrentLocationTool(BaseTool):
    """Get current location via IP geolocation."""

    TOOL_DESCRIPTION = "Get current location via IP geolocation"
    EXECUTION_TARGET = "client"
    PARAMS_SCHEMA: Dict[str, Any] = {"detailed": {"type": "boolean", "required": False, "default": False, "description": "Return extra info like timezone, ISP, and accuracy note"}}
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"latitude": {"type": "number"}, "longitude": {"type": "number"}, "city": {"type": "string"}, "region": {"type": "string"}, "country": {"type": "string"}, "country_code": {"type": "string"}, "postal": {"type": "string"}, "maps_link": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "where am I right now"}]
    SEMANTIC_TAGS = ["system", "current", "location"]
    TOOL_CATEGORY = "web_knowledge"

    def get_tool_name(self) -> str:
        return "current_location"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        detailed = self.get_input(inputs, "detailed", False)
        try:
            location = self._get_location()
            if not location:
                return ToolOutput(success=False, data={}, error="Could not determine location from any provider.")
            lat, lon = location.get("lat"), location.get("lon")
            data = {
                "latitude": lat, "longitude": lon,
                "city": location.get("city", "N/A"), "region": location.get("region", "N/A"),
                "country": location.get("country", "N/A"), "country_code": location.get("country_code", "N/A"),
                "postal": location.get("postal", "N/A"),
                "maps_link": f"https://maps.google.com/?q={lat},{lon}" if lat and lon else "N/A",
                "timestamp": datetime.now().isoformat(),
            }
            if detailed:
                data["timezone"] = location.get("timezone", "N/A")
                data["isp"] = location.get("isp", "N/A")
                data["accuracy_note"] = "IP-based geolocation. Accuracy ~1–10 km depending on ISP."
            return ToolOutput(success=True, data=data)
        except Exception as e:
            return ToolOutput(success=False, data={}, error=str(e))

    def _get_location(self) -> Dict[str, Any] | None:
        for provider in [self._from_ipapi, self._from_ipinfo, self._from_ipwho]:
            try:
                result = provider()
                if result and result.get("lat") and result.get("lon"):
                    return result
            except Exception:
                continue
        return None

    def _fetch_json(self, url: str) -> Dict:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as res:
            return json.loads(res.read().decode("utf-8"))

    def _from_ipapi(self) -> Dict[str, Any]:
        data = self._fetch_json("http://ip-api.com/json/?fields=status,lat,lon,city,regionName,country,countryCode,zip,timezone,isp")
        if data.get("status") != "success":
            raise ValueError("ip-api returned non-success")
        return {"lat": data["lat"], "lon": data["lon"], "city": data.get("city"), "region": data.get("regionName"), "country": data.get("country"), "country_code": data.get("countryCode"), "postal": data.get("zip"), "timezone": data.get("timezone"), "isp": data.get("isp")}

    def _from_ipinfo(self) -> Dict[str, Any]:
        data = self._fetch_json("https://ipinfo.io/json")
        lat, lon = (None, None) if "loc" not in data else tuple(map(float, data["loc"].split(",")))
        return {"lat": lat, "lon": lon, "city": data.get("city"), "region": data.get("region"), "country": data.get("country"), "country_code": data.get("country"), "postal": data.get("postal"), "timezone": data.get("timezone"), "isp": data.get("org")}

    def _from_ipwho(self) -> Dict[str, Any]:
        data = self._fetch_json("https://ipwho.is/")
        if not data.get("success"):
            raise ValueError("ipwho.is failed")
        return {"lat": data.get("latitude"), "lon": data.get("longitude"), "city": data.get("city"), "region": data.get("region"), "country": data.get("country"), "country_code": data.get("country_code"), "postal": data.get("postal"), "timezone": data.get("timezone", {}).get("id") if isinstance(data.get("timezone"), dict) else None, "isp": data.get("connection", {}).get("isp") if isinstance(data.get("connection"), dict) else None}


__all__ = ["CurrentLocationTool"]
