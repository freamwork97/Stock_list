import time
import os
from typing import Any, Optional

import httpx

from .auth import TokenManager
from .config import KiwoomConfig


def parse_price(value: str | int | float | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return abs(float(value))
    clean = str(value).strip().replace(",", "").lstrip("+-")
    return float(clean) if clean else 0.0


class KiwoomClient:
    MIN_REQUEST_INTERVAL = 0.35

    def __init__(self, config: Optional[KiwoomConfig] = None):
        self.config = config or KiwoomConfig.from_env()
        self.token_manager = TokenManager(self.config)
        self._last_request_time = 0.0

    def _wait_for_rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    def _request(
        self,
        api_id: str,
        path: str,
        body: dict[str, Any],
        cont_yn: str = "",
        next_key: str = "",
        retry_count: int = 3,
    ) -> dict[str, Any]:
        url = f"{self.config.base_url}{path}"

        for attempt in range(retry_count):
            self._wait_for_rate_limit()
            headers = self.token_manager.get_auth_header(api_id)
            if cont_yn:
                headers["cont-yn"] = cont_yn
            if next_key:
                headers["next-key"] = next_key

            try:
                with httpx.Client(timeout=20) as client:
                    response = client.post(url, headers=headers, json=body)
                    if response.status_code == 429 and attempt < retry_count - 1:
                        retry_after = response.headers.get("Retry-After")
                        wait_s = int(retry_after) if retry_after else (attempt + 1) * 2
                        time.sleep(wait_s)
                        continue
                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPStatusError:
                if attempt == retry_count - 1:
                    raise

        return {"return_code": 1, "return_msg": "request failed"}

    # PDF reference endpoints
    # ka10030: 거래량 상위
    def get_volume_rank(self, market: str = "ALL", count: int = 50) -> dict[str, Any]:
        stex_tp = "1" if self.config.is_paper else "3"
        return self._request(
            api_id="ka10030",
            path="/api/dostk/rkinfo",
            body={
                "mrkt_tp": "000",
                "sort_tp": "1",
                "mang_stk_incls": "0",
                "crd_tp": "0",
                "trde_qty_tp": "0",
                "pric_tp": "0",
                "trde_prica_tp": "0",
                "mrkt_open_tp": "0",
                "stex_tp": stex_tp,
            },
        )

    # ka10027: 전일대비 등락률 상위
    def get_change_rate_rank(self, market: str = "ALL", count: int = 30) -> dict[str, Any]:
        stex_tp = "1" if self.config.is_paper else "3"
        return self._request(
            api_id="ka10027",
            path="/api/dostk/rkinfo",
            body={
                "mrkt_tp": "000",
                "sort_tp": "1",
                "trde_qty_cnd": "0000",
                "stk_cnd": "0",
                "crd_cnd": "0",
                "updown_incls": "1",
                "pric_cnd": "0",
                "trde_prica_cnd": "0",
                "stex_tp": stex_tp,
            },
        )

    # ka10171: 조건검색 목록
    def get_condition_list(self) -> dict[str, Any]:
        api_id = os.getenv("KIWOOM_CONDITION_LIST_API_ID", "ka10171")
        path = os.getenv("KIWOOM_CONDITION_PATH", "/api/dostk/websocket")
        return self._request(api_id=api_id, path=path, body={})

    # ka10172: 조건검색 결과
    def search_by_condition(self, condition_idx: str) -> dict[str, Any]:
        api_id = os.getenv("KIWOOM_CONDITION_SEARCH_API_ID", "ka10172")
        path = os.getenv("KIWOOM_CONDITION_PATH", "/api/dostk/websocket")
        return self._request(
            api_id=api_id,
            path=path,
            body={"seq": condition_idx, "search_type": "0"},
        )

    # ka10080: 주식분봉차트조회
    def get_stock_chart(self, stock_code: str, tick_unit: str = "1") -> dict[str, Any]:
        return self._request(
            api_id="ka10080",
            path="/api/dostk/chart",
            body={
                "stk_cd": stock_code,
                "tic_scope": str(tick_unit),
                "upd_stkpc_tp": "1",
            },
        )

    def close(self) -> None:
        self.token_manager.revoke()
