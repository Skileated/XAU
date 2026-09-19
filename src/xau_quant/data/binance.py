"""Binance Spot market data acquisition provider."""

import asyncio
import hashlib
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import websockets

from xau_quant.common.paths import project_paths
from xau_quant.data.provider import DataProvider

logger = logging.getLogger(__name__)


class BinanceSpotProvider(DataProvider):
    """Acquires genuine Binance Spot public market data."""

    BASE_URL = "https://api.binance.com"
    WS_BASE_URL = "wss://stream.binance.com:9443/ws"

    def __init__(
        self,
        base_url: str = BASE_URL,
        ws_base_url: str = WS_BASE_URL,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.ws_base_url = ws_base_url.rstrip("/")
        self.timeout = timeout_seconds
        self._user_agent = "xau-quant-platform/0.1.0"

    @property
    def venue_name(self) -> str:
        return "binance"

    def _make_request(
        self, path: str, params: Optional[Dict[str, Any]] = None
    ) -> Tuple[int, bytes, Dict[str, str], float]:
        """Execute a conservative HTTP GET request to a public Binance endpoint."""
        url = f"{self.base_url}{path}"
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            url = f"{url}?{query}"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "application/json",
            },
        )

        start_time = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                elapsed = time.time() - start_time
                status_code = resp.status
                body = resp.read()
                headers = {k: v for k, v in resp.headers.items()}
                return status_code, body, headers, elapsed
        except urllib.error.HTTPError as exc:
            elapsed = time.time() - start_time
            body = exc.read()
            headers = {k: v for k, v in exc.headers.items()} if exc.headers else {}
            logger.error(
                f"Binance HTTP {exc.code} for {url}: {body.decode('utf-8', errors='replace')}"
            )
            raise RuntimeError(
                f"Binance HTTP {exc.code}: {body.decode('utf-8', errors='replace')}"
            ) from exc
        except Exception as exc:
            elapsed = time.time() - start_time
            logger.error(f"Binance request failed for {url}: {exc}")
            raise RuntimeError(f"Binance connection failed: {exc}") from exc

    def ping(self) -> bool:
        """Verify endpoint reachability via /api/v3/ping."""
        try:
            status, body, headers, elapsed = self._make_request("/api/v3/ping")
            return status == 200 and body.strip() == b"{}"
        except Exception:
            return False

    def get_server_time(self) -> int:
        """Query Binance official server time via /api/v3/time.

        Returns epoch milliseconds.
        """
        status, body, headers, elapsed = self._make_request("/api/v3/time")
        data = json.loads(body.decode("utf-8"))
        return int(data["serverTime"])

    def fetch_historical_raw(
        self,
        symbol: str = "BTCUSDT",
        interval: str = "1m",
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        limit: int = 500,
        destination_dir: Optional[Path] = None,
    ) -> Tuple[Path, bytes, Dict[str, Any]]:
        """Fetch raw klines and save immutably under data/raw/binance/spot/<symbol>/<interval>/."""
        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": limit,
        }
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms

        endpoint = "/api/v3/klines"
        acq_time_utc = datetime.now(timezone.utc)
        status_code, raw_bytes, headers, elapsed = self._make_request(endpoint, params)

        parsed = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(parsed, list):
            raise ValueError(f"Unexpected Binance response format: {parsed}")

        if destination_dir is None:
            destination_dir = (
                project_paths.data_raw / "binance" / "spot" / symbol.upper() / interval
            )
        destination_dir.mkdir(parents=True, exist_ok=True)

        # File naming using timestamp and record range
        timestamp_str = acq_time_utc.strftime("%Y%m%d_%H%M%S")
        if parsed:
            first_ms = parsed[0][0]
            last_ms = parsed[-1][0]
            filename = (
                f"binance_spot_{symbol.lower()}_{interval}_{first_ms}_{last_ms}_"
                f"{timestamp_str}_raw.json"
            )
        else:
            filename = f"binance_spot_{symbol.lower()}_{interval}_empty_{timestamp_str}_raw.json"

        target_file = destination_dir / filename
        target_file.write_bytes(raw_bytes)

        file_hash = hashlib.sha256(raw_bytes).hexdigest()
        metadata: Dict[str, Any] = {
            "venue": "binance",
            "market_type": "spot",
            "instrument": symbol.upper(),
            "timeframe": interval,
            "endpoint": f"{self.base_url}{endpoint}",
            "requested_limit": limit,
            "requested_start_ms": start_time_ms,
            "requested_end_ms": end_time_ms,
            "actual_records": len(parsed),
            "first_kline_open_time_ms": parsed[0][0] if parsed else None,
            "last_kline_open_time_ms": parsed[-1][0] if parsed else None,
            "acquisition_timestamp_utc": acq_time_utc.isoformat(),
            "http_status": status_code,
            "request_elapsed_seconds": round(elapsed, 4),
            "used_weight_1m": headers.get("x-mbx-used-weight-1m"),
            "sha256": file_hash,
            "raw_file_path": str(target_file),
        }

        logger.info(
            f"Saved {len(parsed)} raw klines for {symbol} to {target_file} "
            f"(SHA256: {file_hash[:12]}...)"
        )
        return target_file, raw_bytes, metadata

    async def _run_ws_probe(
        self,
        symbol: str,
        duration_seconds: float,
    ) -> Dict[str, Any]:
        """Execute short-lived public WebSocket stream probe."""
        stream_name = f"{symbol.lower()}@trade"
        ws_url = f"{self.ws_base_url}/{stream_name}"

        # Quantify clock skew against Binance server time
        t_before = time.time() * 1000.0
        server_time_ms = self.get_server_time()
        t_after = time.time() * 1000.0
        local_est_ms = (t_before + t_after) / 2.0
        clock_skew_ms = local_est_ms - server_time_ms

        messages: List[Dict[str, Any]] = []
        observed_latencies: List[float] = []
        connect_start = time.time()
        first_msg_time: Optional[float] = None

        async with websockets.connect(ws_url) as ws:
            connect_duration = time.time() - connect_start
            deadline = time.time() + duration_seconds

            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(
                        ws.recv(), timeout=max(0.1, deadline - time.time())
                    )
                    local_recv_ms = time.time() * 1000.0
                    msg = json.loads(raw)
                    messages.append(msg)

                    if first_msg_time is None:
                        first_msg_time = local_recv_ms

                    # Server event time from trade message ('E' event time or 'T' trade time)
                    server_event_ms = float(msg.get("T", msg.get("E", 0)))
                    if server_event_ms > 0:
                        # Compensated latency = (local_recv_ms - clock_skew_ms) - server_event_ms
                        adjusted_local_ms = local_recv_ms - clock_skew_ms
                        latency_ms = adjusted_local_ms - server_event_ms
                        observed_latencies.append(latency_ms)
                except asyncio.TimeoutError:
                    break

        avg_latency = (
            sum(observed_latencies) / len(observed_latencies) if observed_latencies else None
        )

        return {
            "connection_established": True,
            "stream_used": stream_name,
            "ws_url": ws_url,
            "connect_duration_seconds": round(connect_duration, 4),
            "clock_skew_ms": round(clock_skew_ms, 2),
            "messages_received_count": len(messages),
            "first_message_timestamp_utc": datetime.fromtimestamp(
                (first_msg_time / 1000.0) if first_msg_time else time.time(), tz=timezone.utc
            ).isoformat(),
            "observed_latencies_ms": [round(x, 2) for x in observed_latencies[:10]],
            "average_latency_ms": round(avg_latency, 2) if avg_latency is not None else None,
            "sample_message": messages[0] if messages else None,
            "clean_shutdown": True,
        }

    def test_websocket(
        self,
        symbol: str = "BTCUSDT",
        duration_seconds: float = 5.0,
    ) -> Dict[str, Any]:
        """Synchronous wrapper for public WebSocket connectivity test."""
        return asyncio.run(self._run_ws_probe(symbol=symbol, duration_seconds=duration_seconds))
