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
        "data": {"latitude": {"type": "number"}, "longitude": {"type": "number"}, "city": {"type": "string"}, "region": {"type": "string"}, "country": {"type": "string"}, "country_code": {"type": "string"}, "postal": {"type": "string"}, "location_string": {"type": "string", "description": "Human-friendly combined location, e.g. 'Mumbai, Maharashtra'. Preferred binding target for downstream search tools."}, "maps_link": {"type": "string"}},
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
            city = location.get("city") or "N/A"
            region = location.get("region") or "N/A"
            data = {
                "latitude": lat, "longitude": lon,
                "city": city, "region": region,
                "country": location.get("country", "N/A"), "country_code": location.get("country_code", "N/A"),
                "postal": location.get("postal", "N/A"),
                "location_string": _build_location_string(city, region, location.get("country")),
                "maps_link": f"https://maps.google.com/?q={lat},{lon}" if lat and lon else "N/A",
                "timestamp": datetime.now().isoformat(),
            }
            if detailed:
                data["timezone"] = location.get("timezone", "N/A")
                data["isp"] = location.get("isp", "N/A")
                data["accuracy_note"] = "IP-based geolocation. Accuracy ~1–10 km depending on ISP."

            # Cache country_code so future product_search calls in this
            # process can route to the right marketplace without SQH having
            # to re-plan current_location every time.
            try:
                cc = location.get("country_code")
                user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "")
                if cc and user_id:
                    from plugins.installed.web.tools.entity_search import remember_country_code
                    remember_country_code(user_id, cc)
            except Exception:
                pass

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


def _build_location_string(city: str | None, region: str | None, country: str | None) -> str:
    """Build a human-friendly location label, skipping missing/duplicate parts.

    Examples:
      ("Mumbai", "Maharashtra", "India") -> "Mumbai, Maharashtra"
      ("Singapore", "Singapore", "Singapore") -> "Singapore"
      ("Mumbai", "N/A", "India") -> "Mumbai, India"
      (None, None, "India") -> "India"
    """
    def _clean(v: str | None) -> str:
        if not v:
            return ""
        s = str(v).strip()
        return "" if s.upper() in {"N/A", "NA", "NONE"} else s

    c, r, co = _clean(city), _clean(region), _clean(country)

    parts: list[str] = []
    if c:
        parts.append(c)
    # Avoid repeating the same word (city == region for city-states like Singapore)
    if r and r.lower() != c.lower():
        parts.append(r)
    if not parts and co:
        parts.append(co)
    elif co and len(parts) == 1 and parts[0].lower() != co.lower():
        # Only add country when we have nothing else informative beyond city
        if not r:
            parts.append(co)

    return ", ".join(parts) if parts else "Unknown"


__all__ = ["CurrentLocationTool"]
