"""
Weather tools — current conditions and 7-day forecast.
Uses Open-Meteo (free, no API key) + ip-api for auto location.
"""

import urllib.request
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from ..base import BaseTool, ToolOutput


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

WMO_CODES: Dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}


def _fetch_json(url: str) -> Dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=6) as res:
        return json.loads(res.read().decode("utf-8"))


def _get_location(lat: Optional[float], lon: Optional[float]) -> Dict[str, Any]:
    """Use provided coords or auto-detect via IP geolocation."""
    if lat is not None and lon is not None:
        return {"lat": lat, "lon": lon, "city": "Custom", "country": ""}

    data = _fetch_json(
        "http://ip-api.com/json/?fields=status,lat,lon,city,regionName,country,countryCode"
    )
    if data.get("status") != "success":
        raise RuntimeError("Could not determine location automatically.")

    return {
        "lat": data["lat"],
        "lon": data["lon"],
        "city": data.get("city", "Unknown"),
        "region": data.get("regionName", ""),
        "country": data.get("country", ""),
        "country_code": data.get("countryCode", ""),
    }


def _wmo_description(code: int) -> str:
    return WMO_CODES.get(code, f"Unknown ({code})")


# ---------------------------------------------------------------------------
# Tool 1 — Current Weather
# ---------------------------------------------------------------------------

class WeatherCurrentTool(BaseTool):
    """Get current weather conditions at a location.

    Inputs:
    - lat (float, optional) - latitude (auto-detected if omitted)
    - lon (float, optional) - longitude (auto-detected if omitted)
    - units (string, optional) - "metric" (default) or "imperial"

    Outputs:
    - location (string)
    - temperature (number)
    - feels_like (number)  
    - humidity (number)
    - condition (string)
    - wind_speed (number)
    - wind_direction (string)
    - uv_index (number)
    - is_day (boolean)
    - units (string)
    - timestamp (string)
    """

    def get_tool_name(self) -> str:
        return "weather_current"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        lat = self.get_input(inputs, "lat", None)
        lon = self.get_input(inputs, "lon", None)
        units = self.get_input(inputs, "units", "metric")

        try:
            loc = _get_location(lat, lon)
            weather = self._fetch_current(loc["lat"], loc["lon"], units)

            location_str = ", ".join(filter(None, [
                loc.get("city"), loc.get("region"), loc.get("country")
            ]))

            temp_unit = "°C" if units == "metric" else "°F"
            speed_unit = "km/h" if units == "metric" else "mph"

            return ToolOutput(
                success=True,
                data={
                    "location": location_str,
                    "latitude": loc["lat"],
                    "longitude": loc["lon"],
                    "temperature": f"{weather['temperature_2m']}{temp_unit}",
                    "feels_like": f"{weather['apparent_temperature']}{temp_unit}",
                    "humidity": f"{weather['relative_humidity_2m']}%",
                    "condition": _wmo_description(weather["weather_code"]),
                    "wind_speed": f"{weather['wind_speed_10m']} {speed_unit}",
                    "wind_direction": _wind_direction(weather["wind_direction_10m"]),
                    "uv_index": weather.get("uv_index", "N/A"),
                    "is_day": bool(weather.get("is_day", 1)),
                    "precipitation": f"{weather.get('precipitation', 0)} mm",
                    "units": units,
                    "timestamp": datetime.now().isoformat(),
                }
            )

        except Exception as e:
            self.logger.error(f"weather_current failed: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    def _fetch_current(self, lat: float, lon: float, units: str) -> Dict:
        temp_unit = "celsius" if units == "metric" else "fahrenheit"
        wind_unit = "kmh" if units == "metric" else "mph"

        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,apparent_temperature,relative_humidity_2m,"
            f"weather_code,wind_speed_10m,wind_direction_10m,uv_index,"
            f"precipitation,is_day"
            f"&temperature_unit={temp_unit}"
            f"&wind_speed_unit={wind_unit}"
            f"&forecast_days=1"
        )

        data = _fetch_json(url)
        return data["current"]


# ---------------------------------------------------------------------------
# Tool 2 — Weather Forecast
# ---------------------------------------------------------------------------

class WeatherForecastTool(BaseTool):
    """Get a 7-day weather forecast at a location.

    Inputs:
    - lat (float, optional) - latitude (auto-detected if omitted)
    - lon (float, optional) - longitude (auto-detected if omitted)
    - days (int, optional) - number of days 1–16 (default 7)
    - units (string, optional) - "metric" (default) or "imperial"

    Outputs:
    - location (string)
    - forecast (array of daily objects)
      - date (string)
      - condition (string)
      - temp_max (number)
      - temp_min (number)
      - precipitation_sum (number)
      - wind_speed_max (number)
      - sunrise (string)
      - sunset (string)
      - uv_index_max (number)
    - units (string)
    - timestamp (string)
    """

    def get_tool_name(self) -> str:
        return "weather_forecast"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        lat = self.get_input(inputs, "lat", None)
        lon = self.get_input(inputs, "lon", None)
        days = min(self.get_input(inputs, "days", 7), 16)
        units = self.get_input(inputs, "units", "metric")

        try:
            loc = _get_location(lat, lon)
            forecast = self._fetch_forecast(loc["lat"], loc["lon"], days, units)

            location_str = ", ".join(filter(None, [
                loc.get("city"), loc.get("region"), loc.get("country")
            ]))

            temp_unit = "°C" if units == "metric" else "°F"
            speed_unit = "km/h" if units == "metric" else "mph"

            daily = forecast["daily"]
            dates = daily["time"]
            result_days = []

            for i, date in enumerate(dates):
                result_days.append({
                    "date": date,
                    "condition": _wmo_description(daily["weather_code"][i]),
                    "temp_max": f"{daily['temperature_2m_max'][i]}{temp_unit}",
                    "temp_min": f"{daily['temperature_2m_min'][i]}{temp_unit}",
                    "feels_like_max": f"{daily['apparent_temperature_max'][i]}{temp_unit}",
                    "feels_like_min": f"{daily['apparent_temperature_min'][i]}{temp_unit}",
                    "precipitation_sum": f"{daily['precipitation_sum'][i]} mm",
                    "precipitation_probability": f"{daily.get('precipitation_probability_max', [None]*len(dates))[i]}%",
                    "wind_speed_max": f"{daily['wind_speed_10m_max'][i]} {speed_unit}",
                    "sunrise": daily["sunrise"][i],
                    "sunset": daily["sunset"][i],
                    "uv_index_max": daily.get("uv_index_max", [None]*len(dates))[i],
                })

            return ToolOutput(
                success=True,
                data={
                    "location": location_str,
                    "latitude": loc["lat"],
                    "longitude": loc["lon"],
                    "days_returned": len(result_days),
                    "forecast": result_days,
                    "units": units,
                    "timestamp": datetime.now().isoformat(),
                }
            )

        except Exception as e:
            self.logger.error(f"weather_forecast failed: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    def _fetch_forecast(self, lat: float, lon: float, days: int, units: str) -> Dict:
        temp_unit = "celsius" if units == "metric" else "fahrenheit"
        wind_unit = "kmh" if units == "metric" else "mph"

        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&daily=weather_code,temperature_2m_max,temperature_2m_min,"
            f"apparent_temperature_max,apparent_temperature_min,"
            f"precipitation_sum,precipitation_probability_max,"
            f"wind_speed_10m_max,sunrise,sunset,uv_index_max"
            f"&temperature_unit={temp_unit}"
            f"&wind_speed_unit={wind_unit}"
            f"&forecast_days={days}"
            f"&timezone=auto"
        )

        return _fetch_json(url)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wind_direction(degrees: float) -> str:
    """Convert wind degrees to compass direction."""
    directions = ["N","NNE","NE","ENE","E","ESE","SE","SSE",
                  "S","SSW","SW","WSW","W","WNW","NW","NNW"]
    idx = round(degrees / 22.5) % 16
    return directions[idx]


__all__ = ["WeatherCurrentTool", "WeatherForecastTool"]