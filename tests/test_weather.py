import unittest
from weather_mcp.weather import describe


class WeatherTests(unittest.TestCase):
    def test_clear_sky(self):
        self.assertEqual(describe(0), "Clear sky")

    def test_unknown_code(self):
        self.assertEqual(describe(999), "Unknown")


if __name__ == "__main__":
    unittest.main()
