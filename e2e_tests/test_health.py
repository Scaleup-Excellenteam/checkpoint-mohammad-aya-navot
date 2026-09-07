import json
import unittest
from urllib.request import urlopen

from e2e_tests.common import HTTP_BASE_URL


class HealthEndpointTests(unittest.TestCase):

    def test_health_endpoint_returns_healthy(self):
        url = f"{HTTP_BASE_URL}/health"

        with urlopen(url, timeout=3) as response:
            self.assertEqual(response.status, 200)

            data = json.loads(
                response.read().decode("utf-8")
            )

        self.assertEqual(
            data.get("Status"),
            "Healthy",
        )


if __name__ == "__main__":
    unittest.main()