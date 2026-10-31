# How the weather chat connects natural language, an LLM, MCP, and APIs

This guide explains the implementation in [chat.py](chat.py),
[server.py](server.py), and [weather_mcp/weather.py](weather_mcp/weather.py).
It follows a question from terminal input to the displayed answer and includes
interview questions, implementation limits, and design tradeoffs.

All weather values and protocol identifiers in examples are illustrative.
They are not live API results. JSON snippets marked as simplified omit fields
that the SDK or MCP server may include.

## 1. The explanation to give in an interview

“I built a terminal weather assistant with an OpenAI model and a local MCP
server. The Python chat application discovers the server's tools and converts
their schemas into OpenAI function definitions. The model interprets the user's
question and returns a structured tool request. My application executes that
request through the MCP client. The MCP server calls Open-Meteo and returns
structured weather data. The application sends those results back to the model,
which generates the answer shown in the terminal. Conversation history supports
follow-up questions.”

The crucial distinction is between **deciding what to call** and **executing
the call**. The model proposes a tool name and arguments. Python executes the
tool and the HTTP requests.

## 2. Components and responsibilities

| Component | Role in this project |
| --- | --- |
| User | Types a question into the terminal. |
| `chat.py` | Hosts the conversation, calls OpenAI, bridges tool requests to MCP, and displays answers. |
| OpenAI model | Interprets language, selects tools and arguments, and writes the answer from returned data. |
| `ClientSession` | MCP client inside `chat.py`; initializes the connection, lists tools, and calls them. |
| `server.py` | Separate Python process exposing four tools through FastMCP. |
| `weather_mcp/weather.py` | Resolves locations, makes weather HTTP requests, and normalizes results. |
| Open-Meteo | External geocoding and weather data provider. |

In MCP terminology, `chat.py` acts as the **host application** and contains an
**MCP client**. `server.py` is the **MCP server**. The OpenAI model is an external
service used by the host, rather than the process running the MCP server.

There are two separate kinds of integration:

| Boundary | Communication |
| --- | --- |
| `chat.py` → OpenAI | HTTPS through the OpenAI Python SDK and Responses API. |
| `chat.py` → `server.py` | MCP messages over the child process's standard input/output. |
| `weather.py` → Open-Meteo | HTTPS GET requests through HTTPX. |

The OpenAI service does not connect directly to the local stdio server. This
application bridges OpenAI function calling and MCP itself.

## 3. End-to-end sequence

```mermaid
sequenceDiagram
    actor U as User
    participant C as chat.py / MCP client
    participant L as OpenAI model
    participant S as server.py / FastMCP
    participant W as Open-Meteo

    C->>S: Start subprocess; initialize MCP session
    C->>S: List tools
    S-->>C: Names, descriptions, input schemas
    Note over C: Convert MCP tools into OpenAI function definitions
    U->>C: What's the weather in Hyderabad?
    C->>L: Question + instructions + tool definitions
    L-->>C: Function call: get_current_weather(city=Hyderabad)
    C->>S: MCP tools/call
    S->>W: Geocoding request
    W-->>S: Location coordinates
    S->>W: Forecast request using coordinates
    W-->>S: Weather data
    S-->>C: MCP tool result
    C->>L: Original context + function call + matching tool result
    L-->>C: Natural-language answer
    C-->>U: Print answer
```

For a typical successful current-weather question, this means two OpenAI
requests, one MCP tool execution, and two Open-Meteo HTTP requests. Tool
discovery happens at startup, rather than before every question. Retries,
additional tool rounds, or clarification responses change these counts.

## 4. Startup: configuration and connections

### Loading configuration

```python
ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
```

`ROOT` makes file paths relative to the project rather than the terminal's
working directory. `.env` supplies configuration such as `OPENAI_API_KEY` and
`OPENAI_MODEL`. Existing environment variables take precedence under the
default `load_dotenv` behavior.

The program checks that an API key exists before starting the server.
`AsyncOpenAI` reads that key from the environment. This is API-based access to
an OpenAI model; the code does not automate the ChatGPT website or use browser
login credentials. Model access depends on the configured API project.

### Starting the MCP server

```python
server = StdioServerParameters(
    command=sys.executable,
    args=[str(ROOT / "server.py")],
    cwd=str(ROOT),
)
```

`sys.executable` uses the same Python interpreter as the chat process, helping
keep both processes in the same virtual environment.

`stdio_client(server)` launches the server subprocess and provides streams.
`ClientSession(read, write)` uses those streams for MCP communication.
`await session.initialize()` performs MCP initialization before tool use.
The SDK manages protocol messages, request IDs, and serialization.

Stdio is a local process transport. This project does not open an HTTP endpoint
for MCP. The server's stdout must remain suitable for protocol communication;
diagnostic output belongs on stderr. Terminal prompts are printed by the parent
chat process, not by the server subprocess.

Nested `async with` blocks manage the lifetimes of the OpenAI client, subprocess
transport, and MCP session.

## 5. How Python functions become discoverable tools

In `server.py`:

```python
mcp = FastMCP("Weather Assistant")

@mcp.tool()
async def get_current_weather(city: str) -> dict:
    """Get current temperature, conditions, humidity and wind for a city."""
    return await current_weather(city)
```

The decorator registers the function with FastMCP. Its name, docstring, type
annotations, and defaults provide metadata used to describe the tool. A client
can discover this metadata without reading the Python source.

| Tool | Arguments | Purpose |
| --- | --- | --- |
| `get_current_weather` | `city` | Current conditions. |
| `get_weather_forecast` | `city`, `days=5` | Daily forecast, validated to 1–7 days. |
| `get_hourly_forecast` | `city`, `hours=12` | Hourly forecast, validated to 1–48 hours. |
| `compare_weather` | `city1`, `city2` | Current conditions in two places and temperature difference. |

Startup discovery in `chat.py` is:

```python
listed = await session.list_tools()
tools = [
    {
        "type": "function",
        "name": tool.name,
        "description": tool.description or "",
        "parameters": tool.inputSchema,
        "strict": False,
    }
    for tool in listed.tools
]
```

This is the adapter between MCP tool metadata and OpenAI function definitions.
The model receives tool descriptions and input schemas; it does not receive the
Python implementation or an executable function object.

A simplified definition looks like:

```json
{
  "type": "function",
  "name": "get_current_weather",
  "description": "Get current weather for a city",
  "parameters": {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"]
  },
  "strict": false
}
```

`strict=False` allows using the discovered schemas without converting them to
OpenAI's strict schema requirements. It also means this implementation does not
request strict schema guarantees from the model. Parsing and server-side
validation remain important. Descriptions guide model selection; they do not
guarantee the correct tool will always be selected.

## 6. Reading a natural-language question

The terminal loop uses:

```python
message = (await asyncio.to_thread(input, "You: ")).strip()
```

`input()` is blocking, so it runs in a worker thread while the asynchronous event
loop remains available. Empty messages are skipped. `exit` and `quit` end the
session; `/reset` clears the in-memory conversation.

For a normal message, `main()` calls `answer(...)`.

```python
items = [*history, {"role": "user", "content": message}]
```

`items` starts as a new list containing previous conversation items and the new
question. There is no hand-written keyword parser converting “weather” into a
function call. The language interpretation is delegated to the model.

## 7. First OpenAI request: decide what information is needed

```python
response = await client.responses.create(
    model=model,
    instructions=INSTRUCTIONS,
    input=items,
    tools=tools,
    store=False,
)
```

| Argument | Why it is sent |
| --- | --- |
| `model` | Selects the configured OpenAI model. |
| `instructions` | Defines assistant behavior, including using weather tools and acknowledging failures. |
| `input` | Supplies conversation context and the user's question. |
| `tools` | Advertises the available function names and argument schemas. |
| `store=False` | Requests that the generated response not be stored for later retrieval through the API. |

`store=False` does not stop the request from being transmitted to OpenAI and
should not be described as a universal data-retention guarantee. This project
manages its own conversation history by sending previous items again.

For “What's the weather in Hyderabad?”, the model may return a function-call
item, simplified below:

```json
{
  "type": "function_call",
  "name": "get_current_weather",
  "arguments": "{\"city\":\"Hyderabad\"}",
  "call_id": "call_example_1"
}
```

Notice that `arguments` is a JSON **string** that must be parsed into a Python
dictionary. `call_id` identifies this particular requested invocation.

The model has produced a request to run code; no weather API has been called
by the model itself. It may instead return a clarification such as “Which city?”
without a tool call. Tool execution is not forced on every turn.

## 8. Executing the model's request through MCP

`answer()` keeps the model's output and extracts function calls:

```python
items.extend(response.output)
calls = [item for item in response.output if item.type == "function_call"]
```

Preserving the full output retains messages, function-call items, and any
reasoning-related protocol items returned by a compatible model. This does not
mean the application exposes the model's private reasoning to the user.

For each requested call:

```python
allowed = {tool["name"] for tool in tools}
if call.name not in allowed:
    raise ValueError("Unknown weather tool")
arguments = json.loads(call.arguments)
if not isinstance(arguments, dict):
    raise ValueError("Tool arguments must be an object")
result = await session.call_tool(call.name, arguments=arguments)
```

The allowlist prevents dispatching a name that was not advertised. JSON parsing
and the dictionary check validate the basic shape of the arguments. The MCP
server and weather functions provide further argument validation. There is no
`eval()` or arbitrary Python execution here.

At the protocol level, `session.call_tool` sends an MCP `tools/call` request.
Conceptually, a simplified JSON-RPC request is:

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "get_current_weather",
    "arguments": {"city": "Hyderabad"}
  }
}
```

The MCP SDK creates this protocol message. The application does not manually
construct it. FastMCP dispatches the request to the registered Python function.
The JSON-RPC `id` matches an MCP request with its response; the OpenAI `call_id`
matches a model function request with its tool output. They serve different
protocol layers and are not interchangeable.

## 9. Inside the server: obtaining real weather data

The execution path is:

```text
get_current_weather(city)                # server.py
    → current_weather(city)             # weather.py
        → get_location(client, city)
        → fetch_forecast(client, location, current=True, days=1)
        → normalize provider data into a Python dictionary
```

### Request A: geocoding

`get_location()` calls:

```text
GET https://geocoding-api.open-meteo.com/v1/search
```

Parameters include the city string, `count=5`, language, and JSON format.
The response supplies coordinates and location metadata. Blank cities and empty
search results produce `ValueError`.

The code attempts country matching among returned results when the input has a
comma-separated suffix. Otherwise, it takes the first result. This is a
best-effort heuristic: it passes the full input string to geocoding and does not
guarantee successful disambiguation or ask the user to choose a returned match.

### Request B: weather

`fetch_forecast()` calls:

```text
GET https://api.open-meteo.com/v1/forecast
```

It sends latitude, longitude, `timezone=auto`, forecast days, and the requested
current, daily, or hourly fields. HTTPX uses a 15-second timeout configuration;
`raise_for_status()` surfaces unsuccessful HTTP responses.

`current_weather()` maps provider fields into meaningful keys such as
`temperature_c`, `humidity_percent`, `conditions`, and `observed_at`.
`describe()` translates numeric weather codes into readable descriptions.

Daily forecasts build a list of days. Hourly forecasts request three days of
data and slice from the current local hour to the requested limit. That hour can
include the current partially elapsed hour. `compare_weather()` obtains both
cities' current weather concurrently with `asyncio.gather`, then computes the
temperature difference in Python.

These are ordinary API integrations behind the MCP boundary. MCP standardizes
how the tool is discovered and invoked; it does not replace HTTP or fetch
weather data by itself.

## 10. Sending results back to the LLM

The returned object is an MCP `CallToolResult`, which can contain content,
structured data, and error information. It is not simply the original weather
dictionary.

```python
output = result.model_dump_json()
items.append({
    "type": "function_call_output",
    "call_id": call.call_id,
    "output": output,
})
```

The application serializes the MCP result wrapper into a string and attaches it
to the model's matching `call_id`. An illustrative simplified output item is:

```json
{
  "type": "function_call_output",
  "call_id": "call_example_1",
  "output": "{\"content\":[{\"type\":\"text\",\"text\":\"Weather result...\"}]}"
}
```

The loop makes another Responses API request with the expanded `items` list:
earlier history, user question, model tool request, and tool result. This is how
the model learns what the API returned. Executing a function locally would not
automatically make its return value available to the remote model.

The model can now produce an answer such as:

> According to Open-Meteo, Hyderabad is currently 29°C with partly cloudy skies.

That temperature is an example only. The intended behavior is to use actual
returned fields. Grounding answers in tools reduces reliance on memorized
weather information, but it does not guarantee error-free interpretation or
perfect compliance with instructions.

## 11. Returning the final answer and preserving context

When a response contains no function calls:

```python
if not response.output_text:
    raise RuntimeError("The model returned no answer. Please try again.")
history[:] = items
return response.output_text
```

`main()` then prints:

```python
print(f"Assistant: {text}\n")
```

There is no token streaming in this implementation. The terminal displays the
answer after the tool loop completes.

`history[:] = items` updates the existing history list only after a successful
answer. A failed turn does not commit its intermediate messages. This is a
conversation-state choice, not a rollback of external actions or API charges.

For a follow-up such as “What about Bengaluru?”, prior context lets the model
infer that the user is asking about weather. The model still needs a fresh tool
result for the new city. History is temporary memory, not model training or
fine-tuning. It disappears on exit or `/reset` and is not saved to a database.

## 12. The bounded tool loop

`for _ in range(8)` limits each turn to eight model requests. A model response
can request multiple tools; those calls are executed sequentially by
`for call in calls`. After their results are appended, the next model request
can return an answer or request more tools.

Eight rounds does not mean eight total tool executions. A round can contain
several calls. If the eighth response still asks for tools, those calls are
executed, then the function raises the round-limit error without another model
request to summarize them.

The limit helps prevent an unbounded tool-request cycle. It is not a complete
cost budget or overall wall-clock deadline.

## 13. Failure handling: what the code actually guarantees

| Situation | Current behavior |
| --- | --- |
| Missing API key | Prints setup guidance and exits before opening MCP. |
| OpenAI SDK error during a turn | Prints a generic credential/access/quota/connection message. |
| Invalid JSON, non-object arguments, unknown tool name | Produces an error output for the model through the local `ValueError`/`TypeError` handler. |
| Tool execution error returned as an MCP result | Serialized and sent to the model, including available error metadata. |
| Empty final model text | Raises `RuntimeError`, which the terminal loop displays. |
| Tool-round limit reached | Raises `RuntimeError`; failed turn is not committed. |
| EOF, `exit`, or `quit` | Ends the input loop. |
| Ctrl+C | Top-level handler prints a goodbye message. |

Not every failure is caught. Startup failures, some MCP transport/session errors,
and exceptions outside the handled types can terminate the application. FastMCP
tool errors and MCP protocol errors are different: a returned tool error can be
fed back to the model, while a broken session may prevent any result arriving.

`AsyncOpenAI(timeout=60, max_retries=2)` configures request timeouts and retries
for SDK-supported retryable errors. It does not mean a whole conversational turn
will finish within 60 seconds. The weather HTTP client has its own timeout.

## 14. Security, privacy, and practical limits

The code uses an environment-based API key and `.env` is git-ignored. Never paste
real credentials into interview notes or commit them to source control. Tool
definitions, user conversation, and weather results are transmitted to OpenAI.
City queries and coordinates are transmitted to Open-Meteo by the server.

The instructions tell the model to treat tool output as data rather than
instructions. This is a prompt-injection mitigation, not a complete security
boundary. The allowlist and server-side validation provide application-level
controls; a production system would also need authorization and resource limits
appropriate to its tools.

Other current limits to discuss honestly:

- History grows without truncation, summarization, or token-budget management.
- The app has no persistent sessions, web interface, or multi-user isolation.
- Weather responses are not cached and HTTP clients are created per weather operation.
- Newly added server tools are discovered on the next startup; the client does not refresh them during a session.
- A new FastMCP tool's schema must still be compatible with the OpenAI adapter; discovery alone does not guarantee compatibility.
- This is not a retrieval-augmented document search system, a fine-tuned model, or a model running locally.
- External API availability, ambiguous locations, and model interpretation can affect answer quality.

## 15. Common interview questions and answers

### How does the model know which function to call?

The host sends names, descriptions, JSON input schemas, the question, and
conversation context. The model generates a structured function-call item from
that context. Python dispatches the selected tool; it does not use keyword
matching to choose it.

### Does the LLM execute Python or call Open-Meteo directly?

No. In this implementation it returns a tool name and JSON arguments. `chat.py`
calls MCP, and the server executes Python code that makes HTTP requests.

### Why use MCP when Python could call the weather functions directly?

Direct function calls would be simpler for a single local script. MCP adds a
standard discovery and invocation interface, a process boundary, and reuse by
other MCP-compatible clients. The same `server.py` can serve the terminal chat
or another MCP host without putting OpenAI-specific logic in the weather tools.

### Are OpenAI function calling and MCP the same protocol?

No. Function calling is how the model expresses a request for a supplied tool.
MCP is how the host discovers and invokes the external tool server. The adapter
in `chat.py` connects these interfaces.

### Why are two model requests usually needed?

The first determines which external information to request. The application
executes the request. The second gives the model that result so it can answer.
A clarification may need no tool, while a more complex task may require more
rounds.

### What prevents fabricated weather?

Instructions require tools and the model receives real provider data. However,
this is not a hard guarantee: the code does not force tool execution or
programmatically verify every sentence. Stronger guarantees would require
additional output checks or deterministic presentation of critical readings.

### What is the difference between async and parallel execution here?

`await` allows the event loop to handle other work while an I/O operation waits.
It does not automatically run all calls in parallel. The chat tool loop executes
calls sequentially, while `compare_weather()` explicitly uses `asyncio.gather`
to fetch two cities concurrently.

### Can the MCP server work without OpenAI?

Yes. Running `server.py` exposes weather tools to an MCP client such as Inspector.
Only `chat.py` needs the OpenAI API key. The server contains no model API calls.

### How would you improve this for production?

Start with error handling and observability across both protocol boundaries,
bounded history and usage budgets, stronger schema validation, and meaningful
integration tests. Add caching, persistent sessions, user authorization, or a
remote MCP transport when the actual deployment requires them. These are
possible improvements, not features already present in this repository.

## 16. What the current tests establish

`tests/test_chat.py` uses a mocked OpenAI client and MCP session to check that:

- A model tool request reaches the MCP session with decoded arguments.
- The tool result and matching call ID are included in subsequent model input.
- Successful answers update history, while a failed turn leaves it unchanged.
- Repeated tool requests hit the round limit.

`tests/test_weather.py` checks two weather-code mappings. These tests do not
establish real model quality, external API availability, exhaustive error
handling, or correct geocoding for every city. A local MCP discovery smoke check
can verify subprocess startup and registration without a paid model request.

Run the tests with:

```bash
python -m unittest discover -s tests -v
```

## 17. Code-reading checklist

Follow these locations in order when explaining the project live:

1. `server.py`: `@mcp.tool()` registrations and stdio entry point.
2. `chat.py`, `main()`: subprocess parameters and session initialization.
3. `main()`: `list_tools()` and schema conversion.
4. `main()`: terminal input and call to `answer()`.
5. `answer()`: first Responses API request.
6. `answer()`: function-call extraction, argument parsing, and `session.call_tool()`.
7. `weather.py`: geocoding, forecast HTTP request, and result normalization.
8. `answer()`: `function_call_output`, subsequent model request, and history update.
9. `main()`: displaying the final text.

The key flow to remember is:

```text
Natural language → model tool request → Python MCP client → MCP server
→ external weather APIs → MCP result → model answer → terminal
```

## References

- [Project chat client](chat.py)
- [Project MCP server](server.py)
- [Project weather API implementation](weather_mcp/weather.py)
- [Official OpenAI function calling guide](https://developers.openai.com/api/docs/guides/function-calling)

The implementation descriptions above refer to this repository. The OpenAI
guide provides the external API background for the function-calling loop.
