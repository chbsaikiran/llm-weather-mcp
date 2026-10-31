"""Run with: python server.py (stdio MCP server)."""
from mcp.server.fastmcp import FastMCP
from weather_mcp.weather import current_weather, daily_forecast, hourly_forecast

mcp = FastMCP("Weather Assistant")


@mcp.tool()
async def get_current_weather(city: str) -> dict:
    """Get current temperature, conditions, humidity and wind for a city. Use 'City, Country' for ambiguity."""
    return await current_weather(city)


@mcp.tool()
async def get_weather_forecast(city: str, days: int = 5) -> dict:
    """Get daily weather forecast for a city for 1 to 7 days, including rain probability."""
    return await daily_forecast(city, days)


@mcp.tool()
async def get_hourly_forecast(city: str, hours: int = 12) -> dict:
    """Get the next 1 to 48 hours of temperature, conditions and precipitation probability."""
    return await hourly_forecast(city, hours)


@mcp.tool()
async def compare_weather(city1: str, city2: str) -> dict:
    """Compare current weather in two cities, including temperature difference."""
    import asyncio
    a, b = await asyncio.gather(current_weather(city1), current_weather(city2))
    return {"first_city": a, "second_city": b,
            "temperature_difference_c_first_minus_second": round(a["temperature_c"] - b["temperature_c"], 1)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
