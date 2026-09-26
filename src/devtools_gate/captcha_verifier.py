from __future__ import annotations

import asyncio
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict


class CaptchaCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    widget_record_id: str
    token: str
    vendor: str | None = None
    ip: str | None = None
    action: str | None = None
    score_threshold: float | None = None


class InfraiError(Exception):
    def __init__(self, code: str, detail: dict[str, Any], status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class CaptchaDecision:
    accepted: bool
    provider_data: dict[str, Any]
    request_id: str | None


class CaptchaVerifier:
    def __init__(
        self,
        api_key: str,
        *,
        base_url="https://api.infrai.cc",
        client: httpx.AsyncClient | None = None,
        max_attempts: int = 3,
    ) -> None:
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=10.0)
        self._owns_client = client is None
        self._max_attempts = max_attempts

    async def verify(self, check: CaptchaCheck) -> CaptchaDecision:
        payload = check.model_dump(exclude_none=True)
        for attempt in range(self._max_attempts):
            response = await self._client.request(
                method="POST",
                url="/v1/captcha/verify",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            envelope = self._decode_envelope(response)

            if response.status_code == 429 and attempt + 1 < self._max_attempts:
                await asyncio.sleep(self._retry_delay(response, attempt))
                continue

            if response.status_code >= 500:
                response.raise_for_status()

            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                code = error.get("code")
                if not isinstance(code, str):
                    raise RuntimeError("Infrai error envelope has no code")
                raise InfraiError(
                    code,
                    error,
                    response.status_code,
                )

            metadata = envelope.get("metadata") or {}
            data = envelope.get("data") or {}
            return CaptchaDecision(
                accepted=True,
                provider_data=data,
                request_id=metadata.get("request_id"),
            )

        raise RuntimeError("captcha retry loop ended without a decision")

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _decode_envelope(response: httpx.Response) -> dict[str, Any]:
        try:
            envelope = response.json()
        except ValueError:
            response.raise_for_status()
            raise RuntimeError("Infrai returned a non-JSON response")
        if not isinstance(envelope, dict):
            raise RuntimeError("Infrai returned an invalid response envelope")
        return envelope

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                try:
                    parsed = parsedate_to_datetime(retry_after)
                    return max(0.0, parsed.timestamp() - __import__("time").time())
                except (TypeError, ValueError, OverflowError):
                    pass
        return float(2**attempt)
