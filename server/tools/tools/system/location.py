"""
Location tools - Get current location via IP geolocation.
"""

import logging
import urllib.request
import json
from typing import Dict, Any
from datetime import datetime

from ..base import BaseTool, ToolOutput


class CurrentLocationTool(BaseTool):
    """Get current location using IP geolocation.

    Inputs:
    - detailed (boolean, optional) - return extra info like timezone, ISP, etc.

    Outputs:
    - latitude (float)
    - longitude (float)
    - city (string)
    - region (string)
    - country (string)
    - country_code (string)
    - postal (string)
    - timezone (string)
    - isp (string)
    - maps_link (string)
    """

    def get_tool_name(self) -> str:
        return "current_location"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        detailed = self.get_input(inputs, "detailed", False)

        try:
            location = self._get_location()

            if not location:
                return ToolOutput(
                    success=False,
                    data={},
                    error="Could not determine location from any provider."
                )

            lat = location.get("lat")
            lon = location.get("lon")

            data = {
                "latitude": lat,
                "longitude": lon,
                "city": location.get("city", "N/A"),
                "region": location.get("region", "N/A"),
                "country": location.get("country", "N/A"),
                "country_code": location.get("country_code", "N/A"),
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
            self.logger.error(f"Failed to get location: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    def _get_location(self) -> Dict[str, Any] | None:
        """Try multiple geolocation providers in order of reliability."""

        providers = [
            self._from_ipapi,        # ip-api.com  (best free, no key needed)
            self._from_ipinfo,       # ipinfo.io   (fallback)
            self._from_ipwho,        # ipwho.is    (fallback)
        ]

        for provider in providers:
            try:
                result = provider()
                if result and result.get("lat") and result.get("lon"):
                    self.logger.info(f"Location fetched via {provider.__name__}")
                    return result
            except Exception as e:
                self.logger.warning(f"{provider.__name__} failed: {e}")
                continue

        return None

    def _fetch_json(self, url: str) -> Dict:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as res:
            return json.loads(res.read().decode("utf-8"))

    def _from_ipapi(self) -> Dict[str, Any]:
        """ip-api.com - most accurate free provider, no API key needed."""
        data = self._fetch_json("http://ip-api.com/json/?fields=status,lat,lon,city,regionName,country,countryCode,zip,timezone,isp")
        if data.get("status") != "success":
            raise ValueError("ip-api returned non-success status")
        return {
            "lat": data["lat"],
            "lon": data["lon"],
            "city": data.get("city"),
            "region": data.get("regionName"),
            "country": data.get("country"),
            "country_code": data.get("countryCode"),
            "postal": data.get("zip"),
            "timezone": data.get("timezone"),
            "isp": data.get("isp"),
        }

    def _from_ipinfo(self) -> Dict[str, Any]:
        """ipinfo.io fallback."""
        data = self._fetch_json("https://ipinfo.io/json")
        lat, lon = None, None
        if "loc" in data:
            lat, lon = map(float, data["loc"].split(","))
        return {
            "lat": lat,
            "lon": lon,
            "city": data.get("city"),
            "region": data.get("region"),
            "country": data.get("country"),
            "country_code": data.get("country"),
            "postal": data.get("postal"),
            "timezone": data.get("timezone"),
            "isp": data.get("org"),
        }

    def _from_ipwho(self) -> Dict[str, Any]:
        """ipwho.is fallback."""
        data = self._fetch_json("https://ipwho.is/")
        if not data.get("success"):
            raise ValueError("ipwho.is returned non-success")
        return {
            "lat": data.get("latitude"),
            "lon": data.get("longitude"),
            "city": data.get("city"),
            "region": data.get("region"),
            "country": data.get("country"),
            "country_code": data.get("country_code"),
            "postal": data.get("postal"),
            "timezone": data.get("timezone", {}).get("id"),
            "isp": data.get("connection", {}).get("isp"),
        }


__all__ = ["CurrentLocationTool"]