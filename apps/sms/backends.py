"""Messaging backends: WhatsApp (default) and SMS (optional fallback).

Every backend implements three operations:

* ``send_otp(phone, code, lang, text)``  – one-time code. WhatsApp backends use an
  *authentication* template (with the "copy code" button); SMS backends send `text`.
* ``send_notification(phone, title, body, lang)`` – account updates. WhatsApp
  backends use a *utility* template with two parameters (title, body).
* ``send_text(phone, text, lang)`` – free text (WhatsApp only delivers it inside
  the 24 h customer-service window; used for tests and fallbacks).

Each returns the provider's message id or raises MessagingError. Network calls
use a short timeout so a slow gateway cannot block a web request for long.
"""
import json
import logging
import string

import requests

logger = logging.getLogger(__name__)
TIMEOUT = 10


class MessagingError(Exception):
    pass


SMSError = MessagingError  # backwards-compatible name


class BaseBackend:
    channel = "sms"

    def __init__(self, config: dict, sender_id: str = "", channel: str = ""):
        self.config = config or {}
        self.sender_id = sender_id
        if channel:
            self.channel = channel

    # Default behaviour: everything becomes plain text.
    def send_text(self, phone_e164: str, text: str, lang: str = "fr") -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def send_otp(self, phone_e164, code, lang, text):
        return self.send_text(phone_e164, text, lang)

    def send_notification(self, phone_e164, title, body, lang):
        return self.send_text(phone_e164, f"{title}. {body}".strip(" .") + ".", lang)

    # Old interface
    def send(self, phone_e164, body):
        return self.send_text(phone_e164, body)


class ConsoleBackend(BaseBackend):
    """Prints the message to the server log. Default in development."""

    outbox: list = []

    def send_text(self, phone_e164, text, lang="fr"):
        logger.warning("[%s] to %s: %s", self.channel, phone_e164, text)
        ConsoleBackend.outbox.append((phone_e164, text))
        return f"console-{len(ConsoleBackend.outbox)}"


def _template_language(config, lang):
    """Template language code for the user's language, e.g. {"fr": "fr", "ar": "ar"}."""
    mapping = config.get("languages") or {"fr": "fr", "ar": "ar"}
    return mapping.get(lang) or mapping.get("fr") or "fr"


def _per_language(value, lang):
    if isinstance(value, dict):
        return value.get(lang) or value.get("fr") or next(iter(value.values()), "")
    return value or ""


class WhatsAppCloudBackend(BaseBackend):
    """Meta WhatsApp Cloud API (direct, no intermediary).

    config::

        {
          "phone_number_id": "1234567890",          # WhatsApp Manager › API setup
          "access_token": "EAAG…",                  # permanent system-user token
          "api_version": "v21.0",
          "otp_template": "moucharaka_code",        # category AUTHENTICATION, copy-code button
          "notification_template": "moucharaka_update",   # category UTILITY, body {{1}} and {{2}}
          "languages": {"fr": "fr", "ar": "ar"}     # template language per user language
        }
    """

    channel = "whatsapp"

    def _post(self, payload):
        cfg = self.config
        pid, token = cfg.get("phone_number_id"), cfg.get("access_token")
        if not pid or not token:
            raise MessagingError("WhatsApp Cloud: phone_number_id and access_token required")
        url = f"https://graph.facebook.com/{cfg.get('api_version', 'v21.0')}/{pid}/messages"
        payload = {"messaging_product": "whatsapp", **payload}
        try:
            r = requests.post(url, json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise MessagingError(f"network error: {exc}") from exc
        if r.status_code >= 400:
            raise MessagingError(f"WhatsApp {r.status_code}: {r.text[:300]}")
        try:
            return r.json()["messages"][0]["id"]
        except (ValueError, KeyError, IndexError):
            return ""

    def _template(self, phone, name, lang, body_params, button_param=None):
        components = [{"type": "body", "parameters": [{"type": "text", "text": str(p)[:1000]} for p in body_params]}]
        if button_param is not None:
            components.append({"type": "button", "sub_type": "url", "index": "0",
                               "parameters": [{"type": "text", "text": str(button_param)}]})
        return self._post({"to": phone.lstrip("+"), "type": "template", "template": {
            "name": name, "language": {"code": _template_language(self.config, lang)}, "components": components}})

    def send_text(self, phone_e164, text, lang="fr"):
        return self._post({"to": phone_e164.lstrip("+"), "type": "text", "text": {"body": text[:4096]}})

    def send_otp(self, phone_e164, code, lang, text):
        # a single name ("moucharaka_code") or one per language ({"fr": "moucharaka_code_fr", "ar": "moucharaka_code_ar"})
        name = _per_language(self.config.get("otp_template"), lang)
        if not name:
            raise MessagingError("WhatsApp Cloud: 'otp_template' is required for verification codes")
        button = code if self.config.get("otp_copy_button", True) else None
        return self._template(phone_e164, name, lang, [code], button)

    def send_notification(self, phone_e164, title, body, lang):
        name = _per_language(self.config.get("notification_template"), lang)
        if not name:
            return super().send_notification(phone_e164, title, body, lang)
        # WhatsApp refuses empty or multi-line parameters
        clean = lambda s: " ".join(str(s).split()) or "-"  # noqa: E731
        return self._template(phone_e164, name, lang, [clean(title)[:200], clean(body)[:700]])


class TwilioWhatsAppBackend(BaseBackend):
    """WhatsApp through Twilio (Content API templates).

    config::

        {
          "account_sid": "AC…", "auth_token": "…",
          "from": "whatsapp:+14155238886",
          "otp_content_sid": {"fr": "HX…", "ar": "HX…"},          # authentication template, variable {{1}} = code
          "notification_content_sid": {"fr": "HX…", "ar": "HX…"}  # utility template, {{1}} title, {{2}} body
        }
    """

    channel = "whatsapp"

    def _post(self, phone, **data):
        sid, token = self.config.get("account_sid"), self.config.get("auth_token")
        sender = self.config.get("from") or self.sender_id
        if not sid or not token or not sender:
            raise MessagingError("Twilio WhatsApp: account_sid, auth_token and from required")
        if not sender.startswith("whatsapp:"):
            sender = "whatsapp:" + sender
        data.update({"To": "whatsapp:" + phone, "From": sender})
        try:
            r = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                              data=data, auth=(sid, token), timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise MessagingError(str(exc)) from exc
        if r.status_code >= 400:
            raise MessagingError(f"Twilio {r.status_code}: {r.text[:300]}")
        return r.json().get("sid", "")

    def send_text(self, phone_e164, text, lang="fr"):
        return self._post(phone_e164, Body=text[:1600])

    def send_otp(self, phone_e164, code, lang, text):
        content = _per_language(self.config.get("otp_content_sid"), lang)
        if not content:
            raise MessagingError("Twilio WhatsApp: 'otp_content_sid' is required for verification codes")
        return self._post(phone_e164, ContentSid=content, ContentVariables=json.dumps({"1": code}))

    def send_notification(self, phone_e164, title, body, lang):
        content = _per_language(self.config.get("notification_content_sid"), lang)
        if not content:
            return super().send_notification(phone_e164, title, body, lang)
        return self._post(phone_e164, ContentSid=content,
                          ContentVariables=json.dumps({"1": str(title)[:200], "2": str(body)[:700]}))


# ---------------------------------------------------------------- SMS (optional fallback)

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
    """Generic HTTP gateway (local SMS operator or aggregator, or any WhatsApp
    BSP that takes a simple HTTP request).

    config example::

        {
          "url": "https://sms.example.mr/api/send",
          "method": "POST",                    # GET or POST
          "body_format": "json",               # json | form (POST only)
          "params": {"to": "{phone}", "text": "{message}", "from": "{sender}",
                      "username": "...", "password": "..."},
          "headers": {"Authorization": "Bearer ..."},
          "phone_format": "e164",              # e164 (+222...) | intl (222...) | local (national number)
          "success_contains": "OK",            # optional substring expected in the response
          "message_id_json_path": "data.id"    # optional
        }

    Placeholders: {phone} {message} {sender} {code} {lang}.
    """

    def _request(self, phone_e164, text, code="", lang="fr"):
        cfg = self.config
        url = cfg.get("url")
        if not url:
            raise MessagingError("HTTP backend: missing 'url'")
        fmt = cfg.get("phone_format", "e164")
        if fmt == "local":
            from apps.accounts.phones import national_number

            phone = national_number(phone_e164)
        else:
            phone = {"e164": phone_e164, "intl": phone_e164.lstrip("+")}.get(fmt, phone_e164)
        ctx = {"phone": phone, "message": text, "sender": self.sender_id, "code": code, "lang": lang}
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
            raise MessagingError(f"network error: {exc}") from exc
        if r.status_code >= 400:
            raise MessagingError(f"HTTP {r.status_code}: {r.text[:200]}")
        expected = cfg.get("success_contains")
        if expected and expected not in r.text:
            raise MessagingError(f"unexpected response: {r.text[:200]}")
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

    def send_text(self, phone_e164, text, lang="fr"):
        return self._request(phone_e164, text, lang=lang)

    def send_otp(self, phone_e164, code, lang, text):
        return self._request(phone_e164, text, code=code, lang=lang)


class TwilioBackend(BaseBackend):
    """SMS via Twilio. config: {"account_sid", "auth_token", "from": "+1…"} or "messaging_service_sid"."""

    def send_text(self, phone_e164, text, lang="fr"):
        sid, token = self.config.get("account_sid"), self.config.get("auth_token")
        if not sid or not token:
            raise MessagingError("Twilio: account_sid and auth_token required")
        data = {"To": phone_e164, "Body": text}
        if self.config.get("messaging_service_sid"):
            data["MessagingServiceSid"] = self.config["messaging_service_sid"]
        else:
            data["From"] = self.config.get("from") or self.sender_id
        try:
            r = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                              data=data, auth=(sid, token), timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise MessagingError(str(exc)) from exc
        if r.status_code >= 400:
            raise MessagingError(f"Twilio {r.status_code}: {r.text[:200]}")
        return r.json().get("sid", "")


class InfobipBackend(BaseBackend):
    """SMS via Infobip. config: {"base_url": "https://xxxx.api.infobip.com", "api_key": "..."}"""

    def send_text(self, phone_e164, text, lang="fr"):
        base, key = self.config.get("base_url"), self.config.get("api_key")
        if not base or not key:
            raise MessagingError("Infobip: base_url and api_key required")
        payload = {"messages": [{"destinations": [{"to": phone_e164.lstrip("+")}],
                                 "from": self.sender_id or "Moucharaka", "text": text}]}
        try:
            r = requests.post(f"{base.rstrip('/')}/sms/2/text/advanced", json=payload,
                              headers={"Authorization": f"App {key}"}, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise MessagingError(str(exc)) from exc
        if r.status_code >= 400:
            raise MessagingError(f"Infobip {r.status_code}: {r.text[:200]}")
        try:
            return r.json()["messages"][0]["messageId"]
        except (ValueError, KeyError, IndexError):
            return ""


class VonageBackend(BaseBackend):
    """SMS via Vonage. config: {"api_key": "...", "api_secret": "..."}"""

    def send_text(self, phone_e164, text, lang="fr"):
        key, secret = self.config.get("api_key"), self.config.get("api_secret")
        if not key or not secret:
            raise MessagingError("Vonage: api_key and api_secret required")
        try:
            r = requests.post("https://rest.nexmo.com/sms/json", data={
                "api_key": key, "api_secret": secret, "to": phone_e164.lstrip("+"),
                "from": self.sender_id or "Moucharaka", "text": text, "type": "unicode"}, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise MessagingError(str(exc)) from exc
        data = r.json() if r.content else {}
        msg = (data.get("messages") or [{}])[0]
        if r.status_code >= 400 or msg.get("status") not in (None, "0"):
            raise MessagingError(f"Vonage: {json.dumps(data)[:200]}")
        return msg.get("message-id", "")


BACKENDS = {
    "console": ConsoleBackend,
    "whatsapp_cloud": WhatsAppCloudBackend,
    "twilio_whatsapp": TwilioWhatsAppBackend,
    "http": HTTPBackend,
    "twilio": TwilioBackend,
    "infobip": InfobipBackend,
    "vonage": VonageBackend,
}
WHATSAPP_BACKENDS = {"whatsapp_cloud", "twilio_whatsapp"}


def get_backend(name, config=None, sender_id="", channel=""):
    try:
        return BACKENDS[name](config or {}, sender_id, channel)
    except KeyError as exc:
        raise MessagingError(f"unknown messaging backend {name!r}") from exc
