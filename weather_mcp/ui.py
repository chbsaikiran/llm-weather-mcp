"""A small A2UI v0.8 basic-catalog subset, built only from tool data.

This is a template-based renderer contract, not unrestricted model-generated UI.
Only Card, Column, Row, and literal Text are emitted. No generated HTML or JS.
"""
import json
from uuid import uuid4


def tool_data(result):
    if result.get("isError"):
        return None
    data = result.get("structuredContent")
    if isinstance(data, dict):
        # Some MCP SDK versions wrap non-model return types in `result`.
        return data.get("result", data)
    for content in result.get("content", []):
        if content.get("type") == "text":
            try:
                data = json.loads(content["text"])
                if isinstance(data, dict):
                    return data
            except (ValueError, TypeError):
                continue
    return None


def weather_surface(data):
    """Return A2UI messages for current, hourly, daily, or comparison results."""
    if not isinstance(data, dict):
        return []
    components = []

    def add(kind, props):
        cid = f"c{len(components)}"
        components.append({"id": cid, "component": {kind: props}})
        return cid

    def text(value, hint="body"):
        return add("Text", {"text": {"literalString": str(value)}, "usageHint": hint})

    def group(kind, children):
        return add(kind, {"children": {"explicitList": children}})

    def metric(label, value):
        return group("Column", [text(label, "caption"), text(value, "h3")])

    def val(value, unit=""):
        return "Unavailable" if value is None else f"{value}{unit}"

    def city_card(d):
        loc = d.get("location", {})
        children = [text(loc.get("name", "Weather"), "h2"),
                    text(loc.get("country") or "", "caption")]
        if "temperature_c" in d:
            children += [text(val(d.get("temperature_c"), "°C"), "h1"),
                         text(d.get("conditions", "Unknown")),
                         group("Row", [metric("Feels like", val(d.get("feels_like_c"), "°C")),
                                       metric("Humidity", val(d.get("humidity_percent"), "%")),
                                       metric("Wind", val(d.get("wind_speed_kmh"), " km/h"))]),
                         text(f"Local time: {d.get('observed_at', 'unavailable')} · {d.get('timezone', '')}", "caption")]
        elif "days" in d or "hours" in d:
            daily = "days" in d
            entries = d.get("days" if daily else "hours", [])
            children.append(text("Daily outlook" if daily else "Hourly outlook", "h3"))
            for entry in entries:
                stamp = entry.get("date" if daily else "time", "")
                temp = (f"{val(entry.get('min_temp_c'), '°')} – {val(entry.get('max_temp_c'), '°C')}"
                        if daily else val(entry.get("temperature_c"), "°C"))
                rain = entry.get("max_precipitation_probability_percent" if daily
                                 else "precipitation_probability_percent")
                children.append(group("Row", [text(stamp), text(entry.get("conditions", "Unknown")),
                                               text(temp, "h3"), text(f"Rain {val(rain, '%')}", "caption")]))
            children.append(text(f"Times in {d.get('timezone', 'local timezone')}", "caption"))
        else:
            return None
        children.append(text("Source: Open-Meteo", "caption"))
        return add("Card", {"child": group("Column", children)})

    if "first_city" in data and "second_city" in data:
        cards = [city_card(data[key]) for key in ("first_city", "second_city")]
        if not all(cards):
            return []
        root = group("Column", [group("Row", cards),
                                text(f"Temperature difference (first − second): {val(data.get('temperature_difference_c_first_minus_second'), '°C')}", "h3")])
    else:
        root = city_card(data)
        if root is None:
            return []
    surface = f"weather-{uuid4().hex}"
    return [
        {"surfaceUpdate": {"surfaceId": surface, "components": components}},
        {"beginRendering": {"surfaceId": surface, "root": root}},
    ]
