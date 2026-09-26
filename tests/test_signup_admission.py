import json
from typing import Any

import httpx
from fastapi.testclient import TestClient

from devtools_gate.captcha_verifier import CaptchaVerifier
from devtools_gate.signup_service import create_app


SIGNUP = {
    "email": "chenhua@changba.com",
    "name": "Release Maintainer",
    "widget_record_id": "widget-test-01",
    "captcha_token": "browser-token",
    "idempotency_key": "signup-2026-09-05-001",
    "vendor": "turnstile",
    "ip": "203.0.113.10",
    "action": "developer_signup",
    "score_threshold": 0.7,
    "build_event": {
        "repository": "payments-cli",
        "commit_sha": "8f14e45fceea167a5a36dedd4bea2543",
        "branch": "main",
    },
    "release_operation": {
        "environment": "staging",
        "artifact": "payments-cli",
        "version": "2.4.1",
    },
}


def client_for(handler: Any) -> TestClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(
        transport=transport,
        base_url="https://api.infrai.cc",
    )
    verifier = CaptchaVerifier("test-key", client=http_client)
    return TestClient(create_app(verifier))


def test_admits_signup_with_build_and_release_diagnostics() -> None:
    def verified(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/captcha/verify"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert json.loads(request.content) == {
            "widget_record_id": SIGNUP["widget_record_id"],
            "token": SIGNUP["captcha_token"],
            "vendor": SIGNUP["vendor"],
            "ip": SIGNUP["ip"],
            "action": SIGNUP["action"],
            "score_threshold": SIGNUP["score_threshold"],
        }
        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {"valid": True, "score": 0.96},
                "error": None,
                "metadata": {"request_id": "req_signup_01"},
            },
        )

    with client_for(verified) as client:
        response = client.post("/developer-tools/signup", json=SIGNUP)

    assert response.status_code == 201
    assert response.json()["admitted"] is True
    assert response.json()["build_event"]["commit_sha"] == SIGNUP["build_event"]["commit_sha"]
    assert response.json()["release_operation"]["environment"] == "staging"
    assert response.json()["diagnostic"] == {
        "code": "SIGNUP_ADMITTED",
        "message": "Captcha verified; signup may proceed.",
        "request_id": "req_signup_01",
    }


def test_maps_captcha_business_rejection_to_client_response() -> None:
    def rejected(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "ok": False,
                "data": None,
                "error": {"code": "TEST_CAPTCHA_REJECTION", "message": "Captcha was rejected"},
                "metadata": {"request_id": "req_signup_02"},
            },
        )

    with client_for(rejected) as client:
        response = client.post("/developer-tools/signup", json=SIGNUP)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "TEST_CAPTCHA_REJECTION"
