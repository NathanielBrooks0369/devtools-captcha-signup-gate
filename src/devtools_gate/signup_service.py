from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, AsyncIterator, Literal

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .captcha_verifier import CaptchaCheck, CaptchaVerifier, InfraiError


class BuildEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str
    commit_sha: str = Field(min_length=7, max_length=64)
    branch: str


class ReleaseOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: Literal["sandbox", "staging", "production"]
    artifact: str
    version: str


class DeveloperSignup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    name: str
    widget_record_id: str
    captcha_token: str
    idempotency_key: str = Field(min_length=8, max_length=128)
    vendor: str | None = None
    ip: str | None = None
    action: str = "developer_signup"
    score_threshold: float | None = Field(default=None, ge=0, le=1)
    build_event: BuildEvent
    release_operation: ReleaseOperation


class Diagnostic(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class SignupAdmission(BaseModel):
    admitted: bool
    idempotency_key: str
    decided_at: datetime
    build_event: BuildEvent
    release_operation: ReleaseOperation
    diagnostic: Diagnostic


def get_verifier(request: Request) -> CaptchaVerifier:
    return request.app.state.captcha_verifier


def create_app(verifier: CaptchaVerifier | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configured = verifier
        if configured is None:
            api_key = os.environ.get("INFRAI_API_KEY")
            if not api_key:
                raise RuntimeError("INFRAI_API_KEY is required")
            configured = CaptchaVerifier(api_key)
        app.state.captcha_verifier = configured
        yield
        await configured.close()

    app = FastAPI(title="Developer Tools Signup Gate", lifespan=lifespan)

    @app.post(
        "/developer-tools/signup",
        response_model=SignupAdmission,
        status_code=status.HTTP_201_CREATED,
    )
    async def admit_signup(
        signup: DeveloperSignup,
        captcha: Annotated[CaptchaVerifier, Depends(get_verifier)],
    ) -> SignupAdmission:
        try:
            decision = await captcha.verify(
                CaptchaCheck(
                    widget_record_id=signup.widget_record_id,
                    token=signup.captcha_token,
                    vendor=signup.vendor,
                    ip=signup.ip,
                    action=signup.action,
                    score_threshold=signup.score_threshold,
                )
            )
        except InfraiError as exc:
            client_status = exc.status_code if 400 <= exc.status_code < 500 else 502
            raise HTTPException(
                status_code=client_status,
                detail={
                    "code": exc.code,
                    "message": str(exc.detail.get("message", "Captcha verification rejected")),
                },
            ) from exc

        return SignupAdmission(
            admitted=decision.accepted,
            idempotency_key=signup.idempotency_key,
            decided_at=datetime.now(timezone.utc),
            build_event=signup.build_event,
            release_operation=signup.release_operation,
            diagnostic=Diagnostic(
                code="SIGNUP_ADMITTED",
                message="Captcha verified; signup may proceed.",
                request_id=decision.request_id,
            ),
        )

    return app


app = create_app()


def run() -> None:
    uvicorn.run("devtools_gate.signup_service:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    run()
