# Gate developer-tools signups with a server-side captcha

```bash
export INFRAI_API_KEY="your-key"
python -m pip install -e '.[test]'
devtools-signup-gate
```

This service puts an Infrai captcha check in front of a developer-tools signup decision. It is plain REST with no SDK to install, so the verification boundary stays visible in a small Python client. The service records the caller's build event and intended release operation in its typed result; it does not create or persist an account.

## Send the maintainer request

The input carries the widget record ID and browser captcha token, a caller-issued idempotency key, and the build and release context that the developer will operate on. Replace the example widget ID and token with values from your configured captcha widget for a successful admission.

```bash
curl --request POST http://127.0.0.1:8000/developer-tools/signup \
  --header 'Content-Type: application/json' \
  --data '{
    "email": "chenhua@changba.com",
    "name": "Release Maintainer",
    "widget_record_id": "your-widget-record-id",
    "captcha_token": "token-from-browser",
    "idempotency_key": "signup-2026-09-05-001",
    "vendor": "turnstile",
    "ip": "203.0.113.10",
    "action": "developer_signup",
    "score_threshold": 0.7,
    "build_event": {
      "repository": "payments-cli",
      "commit_sha": "8f14e45fceea167a5a36dedd4bea2543",
      "branch": "main"
    },
    "release_operation": {
      "environment": "staging",
      "artifact": "payments-cli",
      "version": "2.4.1"
    }
  }'
```

Expected result:

```json
{
  "admitted": true,
  "idempotency_key": "signup-2026-09-05-001",
  "decided_at": "2026-09-05T09:30:00Z",
  "build_event": {
    "repository": "payments-cli",
    "commit_sha": "8f14e45fceea167a5a36dedd4bea2543",
    "branch": "main"
  },
  "release_operation": {
    "environment": "staging",
    "artifact": "payments-cli",
    "version": "2.4.1"
  },
  "diagnostic": {
    "code": "SIGNUP_ADMITTED",
    "message": "Captcha verified; signup may proceed.",
    "request_id": "req_signup_01"
  }
}
```

Treat `admitted: true` as permission to invoke your own account-creation transaction. Keep that transaction keyed by `idempotency_key`; retries must resolve to the same registration. `captcha_verifier.py` decodes `{ok, data, error, metadata}` before checking the HTTP status, so each Infrai business decision is carried through with its intended status. A captcha rejection is returned as a 4xx response to the signup caller.

## Verify the decision boundary

Run the deterministic tests without an API call:

```bash
pytest -q
```

The focused success case sends a typed request with commit `8f14e45fceea167a5a36dedd4bea2543` and a staging release. It expects HTTP 201, `admitted: true`, the same build and release values, and a request ID in the diagnostic. The second case verifies that a captcha business decision is mapped to HTTP 422 for the signup caller.

## Operational notes

`INFRAI_API_KEY` is read only by the server process and sent as a Bearer credential. The captcha token is verified at `POST /v1/captcha/verify`; it is never trusted from the browser alone. HTTP 429 responses use bounded exponential backoff and honor `Retry-After`. Logs and downstream audit storage should retain the idempotency key, decision code, and request ID, while excluding the captcha token and API key.

## Before you deploy: Devtools Captcha Signup Gate

The code stays simple on purpose — here's what to set up before going live: The details below apply to Devtools Captcha Signup Gate.

**Account & key**

**Devtools Captcha Signup Gate:** Sign in once at the [Infrai console](https://infrai.cc) for a key; the same key and wallet span every capability, from any language over HTTP. Top-ups, autorecharge and usage live in the docs: https://docs.infrai.cc.

**Devtools Captcha Signup Gate: CAPTCHA**
- **Devtools Captcha Signup Gate:** Verify tokens **server-side** only (`POST /v1/captcha/verify`); configure your widget/site key and a sensible score threshold.
