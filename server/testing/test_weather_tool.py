import asyncio
import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

try:
    from tools.tools.system.weather import WeatherCurrentTool, _fetch_json
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment-dependent import gate
    WeatherCurrentTool = None  # type: ignore[assignment]
    _fetch_json = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc


@unittest.skipIf(_IMPORT_ERROR is not None, f"Weather tool imports unavailable: {_IMPORT_ERROR}")
class WeatherCurrentToolTests(unittest.TestCase):
    def test_current_weather_rejects_invalid_coordinates_before_http_request(self):
        tool = WeatherCurrentTool()

        result = asyncio.run(tool.execute({"lat": "", "lon": ""}))

        self.assertFalse(result.success)
        self.assertEqual(result.error, "Latitude and longitude must be valid numbers.")

    def test_fetch_json_surfaces_provider_reason_from_http_error_body(self):
        error = HTTPError(
            url="https://api.open-meteo.com/v1/forecast",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(b'{"error":true,"reason":"Latitude must be in range of -90 to 90"}'),
        )

        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as ctx:
                _fetch_json("https://api.open-meteo.com/v1/forecast", service_name="Weather service")

        self.assertEqual(
            str(ctx.exception),
            "Weather service rejected the request: Latitude must be in range of -90 to 90",
        )


if __name__ == "__main__":
    unittest.main()
