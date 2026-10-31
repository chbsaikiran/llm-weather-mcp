import json
import os
import unittest
from unittest.mock import patch

import httpx

from weather_mcp.ui import tool_data, weather_surface
from web_app import app, sessions, demo_data


class SurfaceTests(unittest.TestCase):
    def test_all_weather_layouts_have_resolvable_component_trees(self):
        for question in ('current', 'forecast', 'compare'):
            messages = weather_surface(demo_data(question))
            components = messages[0]['surfaceUpdate']['components']
            ids = {component['id'] for component in components}
            self.assertIn(messages[1]['beginRendering']['root'], ids)
            for component in components:
                kind, props = next(iter(component['component'].items()))
                self.assertIn(kind, {'Text', 'Card', 'Row', 'Column'})
                if kind == 'Card':
                    self.assertIn(props['child'], ids)
                if kind in {'Row', 'Column'}:
                    self.assertTrue(set(props['children']['explicitList']) <= ids)

    def test_errors_do_not_become_weather_cards(self):
        self.assertIsNone(tool_data({'isError': True, 'structuredContent': {'temperature_c': 20}}))
        self.assertEqual(weather_surface({'error': 'failed'}), [])

    def test_mcp_structured_and_text_results(self):
        data = demo_data('current')
        self.assertEqual(tool_data({'structuredContent': data}), data)
        self.assertEqual(tool_data({'content': [{'type': 'text', 'text': json.dumps(data)}]}), data)


class WebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        sessions.clear()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_demo_sse_lifecycle_and_surface(self):
        response = await self.client.post('/api/demo', json={'message': 'compare cities'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/event-stream', response.headers['content-type'])
        events = [json.loads(frame[6:]) for frame in response.text.strip().split('\n\n')]
        self.assertEqual(events[0]['type'], 'RUN_STARTED')
        self.assertEqual(events[-1]['type'], 'RUN_FINISHED')
        self.assertTrue(any(e.get('name') == 'a2ui' for e in events))
        self.assertTrue(any(e.get('name') == 'demo' for e in events))
        self.assertTrue(all(not state['history'] for state in sessions.values()))
        self.assertTrue(all(not state['lock'].locked() for state in sessions.values()))
        self.assertIn('HttpOnly', response.headers['set-cookie'])

    async def test_missing_key_is_actionable(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            response = await self.client.post('/api/chat', json={'message': 'weather'})
        self.assertEqual(response.status_code, 503)
        self.assertIn('Demo mode', response.json()['detail'])

    async def test_validation_and_origin(self):
        for message in ('', '   ', 'x' * 4001):
            response = await self.client.post('/api/demo', json={'message': message})
            self.assertEqual(response.status_code, 422)
        response = await self.client.post('/api/demo', json={'message': 'weather'},
                                          headers={'Origin': 'https://other.example'})
        self.assertEqual(response.status_code, 403)

    async def test_independent_sessions_and_reset(self):
        await self.client.post('/api/demo', json={'message': 'current'})
        sid = self.client.cookies['weather_session']
        sessions[sid]['history'].append({'role': 'user', 'content': 'private context'})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as other:
            await other.post('/api/demo', json={'message': 'forecast'})
            other_sid = other.cookies['weather_session']
        self.assertNotEqual(sid, other_sid)
        self.assertEqual(sessions[other_sid]['history'], [])
        response = await self.client.post('/api/reset')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sessions[sid]['history'], [])

    async def test_home_and_assets(self):
        for path in ('/', '/static/app.js', '/static/style.css'):
            response = await self.client.get(path)
            self.assertEqual(response.status_code, 200)
