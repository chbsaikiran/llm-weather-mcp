# AI Weather Assistant — Python MCP Server

A complete local MCP server with four tools, backed by the free [Open-Meteo](https://open-meteo.com/) geocoding and forecast APIs. No weather API key required.

## Requirements

- Python 3.10+ (3.11 or 3.12 recommended)
- Internet connection for Open-Meteo requests
- An MCP-compatible client such as Claude Desktop, or MCP Inspector for testing

## Installation

```bash
cd ai-weather-mcp
python -m venv .venv
```

Activate the virtual environment:

- macOS/Linux: `source .venv/bin/activate`
- Windows PowerShell: `.venv\Scripts\Activate.ps1`

Install:

```bash
python -m pip install -r requirements.txt
```

## Chat with an OpenAI model

### Prefer a browser interface?

Run `python web_app.py` after installing requirements, then open
**http://127.0.0.1:8000**. Weather Studio provides Material Web controls,
weather cards, forecasts, city comparisons, and progressive agent events.
Use **Demo mode** for labeled illustrative data without API calls, or configure
`.env` to ask real questions. See [WEB_UI_GUIDE.md](WEB_UI_GUIDE.md) for setup,
architecture, and the supported A2UI / AG-UI subsets.

For interview preparation, read [A2UI_AGUI_INTERVIEW_GUIDE.md](A2UI_AGUI_INTERVIEW_GUIDE.md)
for protocol concepts, code walkthroughs, example messages, and practice Q&A.

### Terminal chat

Run `python -m pip install -r requirements.txt` after activating the virtual
environment. Copy `.env.example` to `.env` and set your own `OPENAI_API_KEY`.
`OPENAI_MODEL` defaults to `gpt-4.1-mini`; change it to a Responses API model
available to your OpenAI API project. The `.env` file is ignored by git.

```bash
python chat.py
```

Try "What's the weather in Hyderabad, India?" followed by "Compare it with
Bengaluru". Type `/reset` to clear the conversation or `exit` to quit.
The chat client starts `server.py` automatically, discovers its MCP tools,
and lets the model call them before producing a natural-language answer.
Conversation history is held in memory until exit or reset. Each request sends
the conversation and weather tool results to OpenAI with `store=False`.
This uses your OpenAI API credentials and incurs API usage charges.

`python server.py` remains the standalone MCP entry point and does not require
an OpenAI API key. Only `chat.py` uses the LLM.

The integration follows the official
[OpenAI function calling guide](https://developers.openai.com/api/docs/guides/function-calling).

## Test with MCP Inspector

```bash
npx @modelcontextprotocol/inspector .venv/bin/python server.py
```

On Windows use:

```powershell
npx @modelcontextprotocol/inspector .venv\Scripts\python.exe server.py
```

Requires Node.js/npm for `npx`. Open the Inspector URL printed in the terminal, connect, list tools, and call `get_current_weather` with `{"city":"Hyderabad, India"}`. Inspector tests the server without an AI model.

## Connect to Claude Desktop

Open Claude Desktop's MCP configuration file and add an entry under `mcpServers` as shown in `claude_desktop_config.example.json`. Replace both example paths with **absolute** paths on your computer. On Windows, set `command` to the full path to `.venv\\Scripts\\python.exe`, and use escaped backslashes (`\\`) or forward slashes in JSON paths. If you already have other servers configured, merge the `weather-assistant` entry rather than replacing them. Restart Claude Desktop and check that the server/tools appear.

**Important:** `python server.py` starts a stdio MCP server, not a web page. It normally waits silently for JSON-RPC messages from an MCP client; use Inspector or Claude Desktop to interact with it.

## Tools

- `get_current_weather(city)` — current conditions
- `get_weather_forecast(city, days=5)` — 1–7 day daily forecast
- `get_hourly_forecast(city, hours=12)` — next 1–48 hours
- `compare_weather(city1, city2)` — current conditions in two cities

## Demo prompts

1. "What's the current weather in Hyderabad, India?"
2. "Compare current weather in Hyderabad, India and Bengaluru, India."
3. "Show the next 5 days in London, United Kingdom."
4. "Will it rain in Tokyo, Japan during the next 12 hours?"

## Architecture

`User -> AI client -> MCP tool call -> Python FastMCP server -> Open-Meteo API -> tool result -> AI response`

The server uses Open-Meteo's current/daily/hourly weather data and geocoding service. Weather information is provider-supplied and may differ from physical observations. Geocoding chooses the first match unless a country match is found in the first five results. API/network failures are surfaced as tool errors.

## Run tests

```bash
python -m unittest discover -s tests -v
```

## Troubleshooting

- **No tools visible:** Check absolute paths in client configuration, dependencies installed in the selected virtual environment, and restart the client.
- **No location found:** Try `City, Country` spelling.
- **API/network errors:** Check your internet connection and Open-Meteo availability.
- **Inspector cannot launch:** Install a current Node.js version that includes npm/npx.
