"""Local browser host: run with python web_app.py, then visit localhost:8000."""
import asyncio
from contextlib import suppress
import json
import logging
import os
import sys
import time
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from chat import ROOT, answer
from weather_mcp.ui import tool_data, weather_surface

load_dotenv(ROOT / '.env')
app = FastAPI(title='Weather Studio')
app.mount('/static', StaticFiles(directory=ROOT / 'web'), name='static')
# Local single-worker application. Expiring, bounded, server-owned histories.
sessions = {}


class Query(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


@app.get('/')
async def index():
    return FileResponse(ROOT / 'web' / 'index.html')


def check_origin(request):
    origin = request.headers.get('origin')
    if origin and origin != str(request.base_url).rstrip('/'):
        raise HTTPException(403, 'Cross-origin requests are not supported.')


def get_session(request):
    now = time.monotonic()
    for key, state in list(sessions.items()):
        if not state['lock'].locked() and now - state['used'] > 3600:
            del sessions[key]
    sid = request.cookies.get('weather_session')
    if sid not in sessions:
        if len(sessions) >= 32:
            raise HTTPException(503, 'Local session limit reached. Restart the server to clear sessions.')
        sid = uuid4().hex
        sessions[sid] = {'history': [], 'lock': asyncio.Lock(), 'used': now}
    state = sessions[sid]
    state['used'] = now
    return sid, state


@app.post('/api/reset')
async def reset(request: Request):
    check_origin(request)
    state = sessions.get(request.cookies.get('weather_session'))
    if state is None:
        return {'ok': True}
    if state['lock'].locked():
        raise HTTPException(409, 'Wait for the current answer before resetting.')
    state['history'].clear()
    return {'ok': True}


def demo_data(message):
    """Static fixtures, clearly identified in the UI; no API calls."""
    def city(name, temp):
        return {'location': {'name': name, 'country': 'India'}, 'temperature_c': temp,
                'feels_like_c': temp + 1, 'humidity_percent': 62, 'wind_speed_kmh': 11,
                'conditions': 'Partly cloudy', 'observed_at': 'Illustrative data',
                'timezone': 'Asia/Kolkata', 'source': 'Open-Meteo'}
    if 'compare' in message.lower():
        return {'first_city': city('Hyderabad', 29), 'second_city': city('Bengaluru', 24),
                'temperature_difference_c_first_minus_second': 5}
    if any(word in message.lower() for word in ('forecast', 'rain', 'days', 'hours')):
        return {'location': {'name': 'Hyderabad', 'country': 'India'}, 'timezone': 'Asia/Kolkata',
                'days': [{'date': f'Day {i+1}', 'conditions': condition, 'min_temp_c': 22+i,
                          'max_temp_c': 29+i, 'max_precipitation_probability_percent': rain}
                         for i, (condition, rain) in enumerate([('Partly cloudy', 15), ('Light rain', 65),
                                                                ('Clear sky', 5), ('Overcast', 30), ('Clear sky', 10)])]}
    return city('Hyderabad', 29)


@app.post('/api/chat')
@app.post('/api/demo')
async def chat(request: Request, query: Query):
    check_origin(request)
    if not query.message.strip():
        raise HTTPException(422, 'Please enter a weather question.')
    demo = request.url.path.endswith('/demo')
    sid, state = get_session(request)
    if state['lock'].locked():
        raise HTTPException(409, 'A question is already running in this conversation.')
    if not demo and not os.getenv('OPENAI_API_KEY', '').strip():
        raise HTTPException(503, 'Add OPENAI_API_KEY to .env and restart the server, or choose Demo mode.')
    if not demo and len(state['history']) > 160:
        raise HTTPException(409, 'This conversation is full. Start a new conversation.')
    await state['lock'].acquire()
    queue = asyncio.Queue(maxsize=32)
    run = uuid4().hex

    async def send(kind, **fields):
        await queue.put({'type': kind, **fields})

    async def emit(kind, payload):
        cid = payload['id']
        if kind == 'tool_start':
            await send('TOOL_CALL_START', toolCallId=cid, toolCallName=payload['name'])
            await send('TOOL_CALL_ARGS', toolCallId=cid, delta=payload['arguments'])
            await send('TOOL_CALL_END', toolCallId=cid)
        elif kind == 'tool_end':
            # AG-UI TOOL_CALL_END marks completion of argument emission.
            pass
        elif kind == 'tool_result':
            await send('TOOL_CALL_RESULT', messageId=uuid4().hex, toolCallId=cid,
                       content=json.dumps(payload['result']), role='tool')
            data = tool_data(payload['result'])
            for message in weather_surface(data):
                await send('CUSTOM', name='a2ui', value=message)

    async def produce():
        try:
            await send('RUN_STARTED', threadId=sid, runId=run)
            if demo:
                await send('CUSTOM', name='demo', value=True)
                for message in weather_surface(demo_data(query.message)):
                    await send('CUSTOM', name='a2ui', value=message)
                text = ('This is an illustrative preview, not live weather. Try a forecast or city comparison '
                        'to explore the layouts. Switch off Demo mode to ask the model for real weather data.')
            else:
                parameters = StdioServerParameters(command=sys.executable,
                    args=[str(ROOT / 'server.py')], cwd=str(ROOT))
                async with AsyncOpenAI(timeout=60, max_retries=2) as client:
                    async with stdio_client(parameters) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            listed = await session.list_tools()
                            tools = [{'type': 'function', 'name': t.name, 'description': t.description or '',
                                      'parameters': t.inputSchema, 'strict': False} for t in listed.tools]
                            text = await answer(client, session, tools, state['history'], query.message,
                                                os.getenv('OPENAI_MODEL', 'gpt-4.1-mini'), emit=emit)
            mid = uuid4().hex
            await send('TEXT_MESSAGE_START', messageId=mid, role='assistant')
            # The model call is currently buffered; this is one final text event, not token streaming.
            await send('TEXT_MESSAGE_CONTENT', messageId=mid, delta=text)
            await send('TEXT_MESSAGE_END', messageId=mid)
            await send('RUN_FINISHED', threadId=sid, runId=run)
        except Exception as exc:
            logging.getLogger(__name__).error('Weather run %s failed (%s)', run, type(exc).__name__)
            # Do not leak keys, upstream response bodies, or internal paths to the browser.
            await send('RUN_ERROR', message='The request could not finish. Check your API key, model access, network, and server logs, then retry.')
        finally:
            state['used'] = time.monotonic()
            state['lock'].release()
            if not asyncio.current_task().cancelling():
                await queue.put(None)

    async def stream():
        task = asyncio.create_task(produce())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f'data: {json.dumps(event)}\n\n'
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    response = StreamingResponse(stream(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    response.set_cookie('weather_session', sid, httponly=True, samesite='strict', max_age=3600)
    return response


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8000)
