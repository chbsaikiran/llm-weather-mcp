"""Open-Meteo client: no API key required."""
from datetime import date
from typing import Any
import httpx

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog", 51: "Light drizzle",
    53: "Moderate drizzle", 55: "Dense drizzle", 56: "Light freezing drizzle",
    57: "Dense freezing drizzle", 61: "Slight rain", 63: "Moderate rain",
    65: "Heavy rain", 66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains", 80: "Slight rain showers", 81: "Moderate rain showers",
    82: "Violent rain showers", 85: "Slight snow showers",
    86: "Heavy snow showers", 95: "Thunderstorm",
    96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


def describe(code: int | None) -> str:
    return WEATHER_CODES.get(code, "Unknown")


async def get_location(client: httpx.AsyncClient, city: str) -> dict[str, Any]:
    if not city.strip():
        raise ValueError("City must not be empty")
    response = await client.get(GEOCODING_URL, params={"name": city, "count": 5, "language": "en", "format": "json"})
    response.raise_for_status()
    results = response.json().get("results", [])
    if not results:
        raise ValueError(f"No location found for '{city}'. Try a more specific city name.")
    # A city with a country suffix can be disambiguated, e.g. "Paris, France".
    parts = [part.strip().casefold() for part in city.split(",")]
    if len(parts) > 1:
        match = next((item for item in results if item.get("country", "").casefold() == parts[-1] or item.get("country_code", "").casefold() == parts[-1]), None)
        if match:
            return match
    return results[0]


def location_info(location: dict[str, Any]) -> dict[str, Any]:
    return {"name": location["name"], "country": location.get("country"),
            "admin1": location.get("admin1"), "latitude": location["latitude"],
            "longitude": location["longitude"], "timezone": location.get("timezone")}


async def fetch_forecast(client: httpx.AsyncClient, location: dict[str, Any], *,
                         current: bool = False, daily: bool = False, hourly: bool = False,
                         days: int = 7) -> dict[str, Any]:
    params: dict[str, Any] = {
        "latitude": location["latitude"], "longitude": location["longitude"],
        "timezone": "auto", "forecast_days": days,
    }
    if current:
        params["current"] = "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"
    if daily:
        params["daily"] = "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum"
    if hourly:
        params["hourly"] = "temperature_2m,precipitation_probability,weather_code"
    response = await client.get(FORECAST_URL, params=params)
    response.raise_for_status()
    return response.json()


async def current_weather(city: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        loc = await get_location(client, city)
        data = await fetch_forecast(client, loc, current=True, days=1)
    now = data["current"]
    return {"location": location_info(loc), "observed_at": now["time"],
            "timezone": data["timezone"], "temperature_c": now["temperature_2m"],
            "feels_like_c": now["apparent_temperature"],
            "humidity_percent": now["relative_humidity_2m"],
            "precipitation_mm": now["precipitation"],
            "wind_speed_kmh": now["wind_speed_10m"],
            "conditions": describe(now["weather_code"]), "source": "Open-Meteo"}


async def daily_forecast(city: str, days: int = 5) -> dict[str, Any]:
    if not 1 <= days <= 7:
        raise ValueError("days must be between 1 and 7")
    async with httpx.AsyncClient(timeout=15) as client:
        loc = await get_location(client, city)
        data = await fetch_forecast(client, loc, daily=True, days=days)
    d = data["daily"]
    entries = [{"date": day, "conditions": describe(d["weather_code"][i]),
                "min_temp_c": d["temperature_2m_min"][i],
                "max_temp_c": d["temperature_2m_max"][i],
                "max_precipitation_probability_percent": d["precipitation_probability_max"][i],
                "precipitation_sum_mm": d["precipitation_sum"][i]}
               for i, day in enumerate(d["time"])]
    return {"location": location_info(loc), "timezone": data["timezone"],
            "days": entries, "source": "Open-Meteo"}


async def hourly_forecast(city: str, hours: int = 12) -> dict[str, Any]:
    if not 1 <= hours <= 48:
        raise ValueError("hours must be between 1 and 48")
    async with httpx.AsyncClient(timeout=15) as client:
        loc = await get_location(client, city)
        data = await fetch_forecast(client, loc, hourly=True, days=3)
    h = data["hourly"]
    # The API returns hours from local midnight; only show hours from current local hour onward.
    current_hour = data.get("current", {}).get("time")
    if not current_hour:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        local_now = datetime.now(ZoneInfo(data["timezone"]))
        current_hour = local_now.strftime("%Y-%m-%dT%H:00")
    start = next((i for i, t in enumerate(h["time"]) if t >= current_hour[:13]), len(h["time"]))
    entries = [{"time": h["time"][i], "temperature_c": h["temperature_2m"][i],
                "precipitation_probability_percent": h["precipitation_probability"][i],
                "conditions": describe(h["weather_code"][i])}
               for i in range(start, min(start + hours, len(h["time"])))]
    return {"location": location_info(loc), "timezone": data["timezone"],
            "hours": entries, "source": "Open-Meteo"}
