"""Exchange-balance snapshot helper (provider-native).

Data source:
- Coinglass Balance page via an isolated, owned headless Puppeteer browser
- Browser script: /workspace/openbb-decision-pipeline/browser/fetch_exchange_balance.js

No legacy raw bridge fallback.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


class ExchangeBalanceFetchError(RuntimeError):
    """Raised when exchange balance fetch fails."""


def _fetch_script_path() -> Path:
    candidates = []
    env_path = os.getenv("COINGLASS_EXCHANGE_BALANCE_FETCH_JS")
    if env_path:
        candidates.append(Path(env_path))

    here = Path(__file__).resolve()
    candidates.extend(
        [
            Path("/workspace/openbb-decision-pipeline/browser/fetch_exchange_balance.js"),
            here.parents[3] / "openbb-decision-pipeline/browser/fetch_exchange_balance.js",
        ]
    )
    for path in candidates:
        if path.exists():
            return path
    raise ExchangeBalanceFetchError(
        "fetch_exchange_balance.js not found; set COINGLASS_EXCHANGE_BALANCE_FETCH_JS"
    )


def fetch_exchange_balance_snapshot() -> dict[str, Any]:
    fetch_script = _fetch_script_path()

    node_script = r"""
const mod = require(process.env.FETCH_SCRIPT);
(async()=>{
  try {
    const data = await mod.fetchAllBalances();
    console.log('__JSON__' + JSON.stringify(data));
  } catch (e) {
    console.log('__JSON__' + JSON.stringify({error: String(e?.message || e)}));
    process.exit(2);
  }
})();
"""

    p = subprocess.run(
        ["node", "-e", node_script],
        capture_output=True,
        text=True,
        timeout=420,
        env={**os.environ, "FETCH_SCRIPT": str(fetch_script)},
    )

    out = (p.stdout or "")
    err = (p.stderr or "")

    marker = "__JSON__"
    payload_line = None
    for line in out.splitlines()[::-1]:
        if line.startswith(marker):
            payload_line = line[len(marker) :]
            break

    if not payload_line:
        raise ExchangeBalanceFetchError(f"no JSON payload from fetch script; rc={p.returncode}; stderr={err[:300]}")

    payload = json.loads(payload_line)
    if p.returncode:
        detail = payload.get("error") or err[:300]
        raise ExchangeBalanceFetchError(f"fetch script failed; rc={p.returncode}; error={detail}")
    if payload.get("error"):
        raise ExchangeBalanceFetchError(f"fetch script error: {payload.get('error')}")

    btc_err = (payload.get("btc") or {}).get("error")
    eth_err = (payload.get("eth") or {}).get("error")
    if btc_err or eth_err:
        raise ExchangeBalanceFetchError(f"coinglass fetch errors: btc={btc_err}, eth={eth_err}")

    payload["_source"] = "kapy-provider:coinglass-puppeteer"
    return payload
