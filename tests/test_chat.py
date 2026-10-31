import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from chat import answer


class ChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_result_and_history_reach_model(self):
        call = SimpleNamespace(type="function_call", name="get_current_weather",
                               arguments='{"city":"Hyderabad"}', call_id="call_1")
        final = SimpleNamespace(type="message")
        client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(side_effect=[
            SimpleNamespace(output=[call], output_text=""),
            SimpleNamespace(output=[final], output_text="It is sunny."),
        ])))
        result = Mock()
        result.model_dump_json.return_value = '{"conditions":"Clear sky"}'
        session = SimpleNamespace(call_tool=AsyncMock(return_value=result))
        history = [{"role": "user", "content": "Earlier question"}]
        tools = [{"name": "get_current_weather"}]
        text = await answer(client, session, tools, history, "Weather?", "test-model")
        self.assertEqual(text, "It is sunny.")
        session.call_tool.assert_awaited_once_with(
            "get_current_weather", arguments={"city": "Hyderabad"})
        sent = client.responses.create.await_args_list[1].kwargs
        self.assertIn(call, sent["input"])
        self.assertEqual(sent["input"][3]["call_id"], "call_1")
        self.assertFalse(sent["store"])
        self.assertEqual(history[-1], final)

    async def test_failed_turn_does_not_change_history(self):
        client = SimpleNamespace(responses=SimpleNamespace(
            create=AsyncMock(side_effect=RuntimeError("failure"))))
        history = []
        with self.assertRaises(RuntimeError):
            await answer(client, None, [], history, "Weather?", "test-model")
        self.assertEqual(history, [])

    async def test_tool_loop_is_bounded(self):
        call = SimpleNamespace(type="function_call", name="unknown",
                               arguments="{}", call_id="call_1")
        client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(
            return_value=SimpleNamespace(output=[call], output_text=""))))
        history = []
        with self.assertRaisesRegex(RuntimeError, "Too many tool rounds"):
            await answer(client, None, [], history, "Weather?", "test-model")
        self.assertEqual(client.responses.create.await_count, 8)
        self.assertEqual(history, [])
