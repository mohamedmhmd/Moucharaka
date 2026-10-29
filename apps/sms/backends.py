"""SMS backends.

Each backend receives the provider configuration and returns the provider's
message id, or raises SMSError. Network calls use `requests` with a short
timeout so a slow gateway cannot block a web request for long.
"""
import json
import logging
import string

import requests

logger = logging.getLogger(__name__)
TIMEOUT = 10


class SMSError(Exception):
    pass


class BaseBackend:
    def __init__(self, config: dict, sender_id: str = ""):
        self.config = config or {}
        self.sender_id = sender_id

    def send(self, phone_e164: str, body: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleBackend(BaseBackend):
    """Prints the message to the server log. Default in development."""

    outbox: list = []

    def send(self, phone_e164, body):
        logger.warning("SMS to %s: %s", phone_e164, body)
        ConsoleBackend.outbox.append((phone_e164, body))
        return f"console-{len(ConsoleBackend.outbox)}"


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _render(value, ctx):
    if isinstance(value, str):
        return string.Formatter().vformat(value, (), _SafeDict(ctx))
    if isinstance(value, dict):
        return {k: _render(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_render(v, ctx) for v in value]
    return value


class HTTPBackend(BaseBackend):
    """Generic HTTP gateway, fits most local operators and aggregators.

    config example::

        {
          "url": "https://sms.example.mr/api/send",
          "method": "POST",                    # GET or POST
          "body_format": "json",               # json | form (POST only)
          "params": {"to": "{phone}", "text": "{message}", "from": "{sender}",
                      "username": "...", "password": "..."},
          "headers": {"Authorization": "Bearer ..."},
          "phone_format": "e164",              # e164 (+222...) | intl (222...) | local (8 digits)
          "success_contains": "OK",            # optional substring expected in the response
          "message_id_json_path": "data.id"    # optional
        }
    """

    def send(self, phone_e164, body):
        cfg = self.config
        url = cfg.get("url")
        if not url:
            raise SMSError("HTTP backend: missing 'url'")
        fmt = cfg.get("phone_format", "e164")
        phone = {"e164": phone_e164, "intl": phone_e164.lstrip("+"), "local": phone_e164[-8:]}.get(fmt, phone_e164)
        ctx = {"phone": phone, "message": body, "sender": self.sender_id}
        params = _render(cfg.get("params", {}), ctx)
        headers = _render(cfg.get("headers", {}), ctx)
        method = cfg.get("method", "POST").upper()
        try:
            if method == "GET":
                r = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
            elif cfg.get("body_format", "json") == "form":
                r = requests.post(url, data=params, headers=headers, timeout=TIMEOUT)
            else:
                r = requests.post(url, json=params, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise SMSError(f"network error: {exc}") from exc
        if r.status_code >= 400:
            raise SMSError(f"HTTP {r.status_code}: {r.text[:200]}")
        expected = cfg.get("success_contains")
        if expected and expected not in r.text:
            raise SMSError(f"unexpected response: {r.text[:200]}")
        path = cfg.get("message_id_json_path")
        if path:
            try:
                node = r.json()
                for part in path.split("."):
                    node = node[int(part)] if isinstance(node, list) else node[part]
                return str(node)
            except (ValueError, KeyError, IndexError, TypeError):
                pass
        return r.text[:100]


class TwilioBackend(BaseBackend):
    """config: {"account_sid": "...", "auth_token": "...", "from": "+1..." or messaging_service_sid}"""

    def send(self, phone_e164, body):
        sid, token = self.config.get("account_sid"), self.config.get("auth_token")
        if not sid or not token:
            raise SMSError("Twilio: account_sid and auth_token required")
        data = {"To": phone_e164, "Body": body}
        if self.config.get("messaging_service_sid"):
            data["MessagingServiceSid"] = self.config["messaging_service_sid"]
        else:
            data["From"] = self.config.get("from") or self.sender_id
        try:
            r = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                              data=data, auth=(sid, token), timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise SMSError(str(exc)) from exc
        if r.status_code >= 400:
            raise SMSError(f"Twilio {r.status_code}: {r.text[:200]}")
        return r.json().get("sid", "")


class InfobipBackend(BaseBackend):
    """config: {"base_url": "https://xxxx.api.infobip.com", "api_key": "..."}"""

    def send(self, phone_e164, body):
        base, key = self.config.get("base_url"), self.config.get("api_key")
        if not base or not key:
            raise SMSError("Infobip: base_url and api_key required")
        payload = {"messages": [{"destinations": [{"to": phone_e164.lstrip("+")}],
                                 "from": self.sender_id or "Moucharaka", "text": body}]}
        try:
            r = requests.post(f"{base.rstrip('/')}/sms/2/text/advanced", json=payload,
                              headers={"Authorization": f"App {key}"}, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise SMSError(str(exc)) from exc
        if r.status_code >= 400:
            raise SMSError(f"Infobip {r.status_code}: {r.text[:200]}")
        try:
            return r.json()["messages"][0]["messageId"]
        except (ValueError, KeyError, IndexError):
            return ""


class VonageBackend(BaseBackend):
    """config: {"api_key": "...", "api_secret": "..."}"""

    def send(self, phone_e164, body):
        key, secret = self.config.get("api_key"), self.config.get("api_secret")
        if not key or not secret:
            raise SMSError("Vonage: api_key and api_secret required")
        try:
            r = requests.post("https://rest.nexmo.com/sms/json", data={
                "api_key": key, "api_secret": secret, "to": phone_e164.lstrip("+"),
                "from": self.sender_id or "Moucharaka", "text": body, "type": "unicode"}, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise SMSError(str(exc)) from exc
        data = r.json() if r.content else {}
        msg = (data.get("messages") or [{}])[0]
        if r.status_code >= 400 or msg.get("status") not in (None, "0"):
            raise SMSError(f"Vonage: {json.dumps(data)[:200]}")
        return msg.get("message-id", "")


BACKENDS = {
    "console": ConsoleBackend,
    "http": HTTPBackend,
    "twilio": TwilioBackend,
    "infobip": InfobipBackend,
    "vonage": VonageBackend,
}


def get_backend(name, config=None, sender_id=""):
    try:
        return BACKENDS[name](config or {}, sender_id)
    except KeyError as exc:
        raise SMSError(f"unknown SMS backend {name!r}") from exc
