from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import httpx

from .config import KiwoomConfig


@dataclass
class Token:
    access_token: str
    token_type: str
    expires_dt: str

    @property
    def is_expired(self) -> bool:
        if not self.expires_dt:
            return False
        try:
            expires_time = datetime.strptime(self.expires_dt, "%Y%m%d%H%M%S")
            return datetime.now() >= expires_time - timedelta(minutes=1)
        except ValueError:
            return False


class TokenManager:
    def __init__(self, config: KiwoomConfig):
        self.config = config
        self._token: Optional[Token] = None

    @property
    def token(self) -> str:
        if self._token is None or self._token.is_expired:
            self._refresh_token()
        return self._token.access_token

    def _refresh_token(self) -> None:
        url = f"{self.config.base_url}/oauth2/token"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.config.app_key,
            "secretkey": self.config.app_secret,
        }
        with httpx.Client(timeout=15) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()

        token = result.get("token") or result.get("access_token")
        if not token:
            raise RuntimeError(f"Token missing in response: {result}")

        self._token = Token(
            access_token=token,
            token_type=result.get("token_type", "Bearer"),
            expires_dt=result.get("expires_dt", ""),
        )

    def get_auth_header(self, api_id: str) -> dict[str, str]:
        return {
            "api-id": api_id,
            "authorization": f"Bearer {self.token}",
            "content-type": "application/json;charset=UTF-8",
        }

    def revoke(self) -> None:
        if self._token is None:
            return

        url = f"{self.config.base_url}/oauth2/revoke"
        headers = {
            "api-id": "au10002",
            "authorization": f"Bearer {self._token.access_token}",
            "content-type": "application/json;charset=UTF-8",
        }
        payload = {
            "appkey": self.config.app_key,
            "secretkey": self.config.app_secret,
            "token": self._token.access_token,
        }

        try:
            with httpx.Client(timeout=10) as client:
                client.post(url, headers=headers, json=payload)
        finally:
            self._token = None
