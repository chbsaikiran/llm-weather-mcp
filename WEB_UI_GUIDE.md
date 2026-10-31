# Weather Studio: Material components, A2UI, and AG-UI

## Run locally

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python web_app.py
```

Open **http://127.0.0.1:8000**. The server binds to loopback. This is a local
extension of the Python project, not a hosted deployment.

Set `OPENAI_API_KEY` and optionally `OPENAI_MODEL` in `.env` for real questions.
The key stays in Python; it is not sent to the browser. OpenAI API calls incur
usage charges. Restart the server after changing configuration.

Choose **Demo mode** to explore static current-weather, forecast, and comparison
layouts without an OpenAI key or weather API calls. Demo outputs are labeled as
illustrative. Demo questions select predefined fixtures, not real city data;
they are never added to model history. Changing modes clears the conversation.

## What the interface does

- Starter prompts cover current weather, a five-day forecast, and city comparisons.
- Natural-language questions use the same MCP and model tool loop as terminal chat.
- Status messages show when the assistant is working and when weather results arrive.
- Current-weather cards show temperature, conditions, humidity, wind, and local time.
- Daily and hourly results become forecast rows with temperatures and rain probabilities.
- City comparisons display both cards and the computed temperature difference.
- Follow-up buttons request a five-day or twelve-hour outlook for a displayed city.
- New conversation clears server-side history. Mobile layouts stack cards and simplify navigation.

## Three boundaries, three jobs

```text
Browser
  → POST /api/chat, receive server-sent events
Python host (web_app.py + chat.answer)
  → OpenAI Responses API: language interpretation, tool selection, final explanation
  → local MCP session: discovery and tool execution
MCP server (server.py)
  → Open-Meteo: geocoding and weather HTTP requests
```

MCP connects the host to tools. AG-UI-style events connect the host to the
browser. A2UI messages describe what the browser should render. These layers
solve different problems and do not replace each other.

## Google components

The page progressively loads Google's **Material Web 2.3.0** components from
`esm.run` and upgrades the Ask and New conversation controls. Native HTML controls
remain as a fallback if the CDN cannot load. Typography uses Google Fonts with
system font fallbacks. Weather cards use project CSS rather than claiming to be
a Google-provided weather component.

No Node build is required. Loading Google components and fonts requires internet
access. For a production application, consider bundling and serving these assets
locally instead of relying on third-party CDNs.

## A2UI implementation: deliberately bounded

`weather_mcp/ui.py` turns successful structured MCP weather results into a small
**A2UI v0.8 basic-catalog subset**:

1. `surfaceUpdate` supplies an adjacency list of component IDs and properties.
2. `beginRendering` identifies the surface and its root component.
3. `web/app.js` resolves the component tree using an allowlisted renderer.

Supported components are `Card`, `Column`, `Row`, and literal `Text`. Containers
use explicit child lists; text uses `literalString` and supported `usageHint`
values. Components are created with DOM APIs and text content, never generated
HTML, scripts, or `eval`.

The model selects weather tools. Their returned data determines the UI template.
The model does **not** generate arbitrary component trees in this version. This
is template-based generative UI: the presentation changes with the agent's tool
results while application code controls the available components and layout.

This is a custom, limited renderer, not Google's full renderer SDK or a claim
of complete A2UI compliance. It does not implement data-model binding, catalog
negotiation, dynamic surface updates, or A2UI `userAction` messages. Follow-up
buttons send ordinary chat prompts. The explicitly selected v0.8 wire format
is a legacy version; newer A2UI versions have different contracts.

## AG-UI implementation: event subset over SSE

`web_app.py` emits AG-UI-shaped event dictionaries over server-sent events:

| Event | Purpose |
| --- | --- |
| `RUN_STARTED` | Identifies the conversation thread and run. |
| `TOOL_CALL_START` | Announces the selected MCP tool. |
| `TOOL_CALL_ARGS` | Carries JSON argument text. |
| `TOOL_CALL_END` | Ends argument emission, before execution results arrive. |
| `TOOL_CALL_RESULT` | Carries the serialized MCP result. |
| `CUSTOM`, name `a2ui` | Carries one declarative surface message. |
| `TEXT_MESSAGE_START/CONTENT/END` | Delivers the assistant's final explanation. |
| `RUN_FINISHED` | Marks successful completion. |
| `RUN_ERROR` | Reports a failed run. |

The frontend consumes the SSE response with `fetch` because the endpoint is a
POST. `EventSource` normally initiates a GET. The parser buffers partial network
chunks so JSON is parsed only after a full SSE frame arrives.

The OpenAI response is currently **buffered**, not streamed token by token.
Tool progress and surfaces are delivered during the run, and the completed
explanation is sent in one text-content event. There is no simulated typing.

This is an application-specific endpoint using an AG-UI event subset, not the
complete standard AG-UI request contract or the AG-UI SDK. Requests contain
`{ "message": "..." }`; thread IDs, run IDs, and history are owned by the server.
A general-purpose AG-UI client would need an adapter to this request format.

## History, isolation, and failure handling

Each browser receives an opaque HttpOnly session cookie. Histories are held
in server memory, expire after an idle hour, and are limited to 32 sessions.
One request can run per conversation at a time. A conversation over 160 history
items must be reset before another real query. This is a coarse guard, not a
token-accurate context budget. Use a single server worker for this local design.

Same-origin checks reject cross-origin browser requests. This is not a public
authentication system. The loopback app should not be exposed publicly without
authentication, shared session storage, rate limits, and deployment hardening.

The original `answer()` commits history after a successful model answer.
Weather surfaces may already be visible if a later model request fails; the
page displays an error and allows retrying the question. Disconnecting the
browser cancels the producer and closes its MCP context. Already performed
network calls and charges cannot be undone.

`chat.py` still works as a terminal application. Its optional `emit` callback
lets the browser host observe tools without duplicating the model loop.
`server.py` remains the standalone stdio MCP entry point.

## Verification

```bash
python -m unittest discover -s tests -v
node --check web/app.js
```

Tests cover component references, tool error exclusion, SSE lifecycle, demo
labeling, session isolation, reset, request validation, missing-key guidance,
and static asset delivery. Mocked model tests cover the underlying tool loop.
These tests do not replace a live model/weather API check or browser layout QA.

## Official references

- [Google Material Web](https://github.com/material-components/material-web)
- [A2UI v0.8 protocol](https://a2ui.org/specification/v0.8-a2ui/)
- [AG-UI event concepts](https://docs.ag-ui.com/concepts/events)
