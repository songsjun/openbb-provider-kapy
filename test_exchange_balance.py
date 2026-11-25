"""Offline checks for the provider's owned-browser bridge."""
import json
import runpy
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from openbb_kapy.marketdata import exchange_balance as provider


class ExchangeBalanceBridgeTests(unittest.TestCase):
    def call_bridge(self, result):
        with patch.object(provider, "_fetch_script_path", return_value=Path("/test/collector.js")), \
             patch.object(provider.subprocess, "run", return_value=result) as run, \
             patch("requests.get", side_effect=AssertionError("shared CDP must not be used")):
            payload = provider.fetch_exchange_balance_snapshot()
        return payload, run

    def test_owned_browser_does_not_require_shared_cdp(self):
        data = {"btc": {"asset": "BTC"}, "eth": {"asset": "ETH"}}
        result = subprocess.CompletedProcess([], 0, "__JSON__" + json.dumps(data), "")
        payload, run = self.call_bridge(result)
        self.assertEqual(payload["btc"]["asset"], "BTC")
        self.assertEqual(payload["_source"], "kapy-provider:coinglass-puppeteer")
        self.assertNotIn("WS_ENDPOINT", run.call_args.args[0][2])
        self.assertIn("collectionMethod: 'api'", run.call_args.args[0][2])

    def test_failed_process_cannot_publish_an_apparently_successful_payload(self):
        result = subprocess.CompletedProcess([], 2, '__JSON__{"btc":{},"eth":{}}', "failed")
        with self.assertRaisesRegex(provider.ExchangeBalanceFetchError, "rc=2"):
            self.call_bridge(result)

    def test_failed_process_keeps_the_collectors_error_message(self):
        result = subprocess.CompletedProcess([], 2, '__JSON__{"error":"browser startup failed"}', "")
        with self.assertRaisesRegex(provider.ExchangeBalanceFetchError, "browser startup failed"):
            self.call_bridge(result)

    def test_importing_deribit_smoke_script_does_not_call_live_services(self):
        with patch("asyncio.run") as run:
            runpy.run_path(str(Path(__file__).with_name("test_deribit.py")))
        # Close a coroutine created by the old import-time call before asserting.
        for call in run.call_args_list:
            call.args[0].close()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
