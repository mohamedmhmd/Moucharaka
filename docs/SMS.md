# SMS providers

SMS is used for sign-up and login codes (OTP), withdrawal confirmation, KYC decisions, funding events, payment reminders and late-report alerts. Providers are configured in the admin: **SMS › Fournisseurs SMS**. No code change or restart is needed.

## How routing works

1. Active providers are tried by **priority** (lowest number first).
2. If a provider has **préfixes desservis** (e.g. `3`), it only receives numbers starting with those digits. Mauritanian numbers start with 2 (Chinguitel), 3 (Mattel) or 4 (Mauritel), so you can route each operator to its own gateway and keep an international provider as fallback.
3. If a provider fails (network error, HTTP ≥ 400, unexpected response), the next one is tried automatically.
4. Every attempt is logged in **SMS › Journal SMS** with its status. OTP codes are masked in the log.
5. If no provider is active, `SMS_FALLBACK_BACKEND` from the environment is used (`console` writes the message to the server log, for development).

Use the admin action **"Envoyer un SMS de test à mon numéro"** after configuring a provider.

## Backends and their `config` JSON

### Generic HTTP (local operators, aggregators)

Fits almost any gateway that takes an HTTP request. Placeholders `{phone}`, `{message}` and `{sender}` are replaced in `params` and `headers`.

```json
{
  "url": "https://sms.example.mr/api/send",
  "method": "POST",
  "body_format": "json",
  "params": {"to": "{phone}", "text": "{message}", "from": "{sender}", "username": "moucharaka", "password": "••••"},
  "headers": {"Authorization": "Bearer ••••"},
  "phone_format": "intl",
  "success_contains": "OK",
  "message_id_json_path": "data.id"
}
```

| Key | Values |
|---|---|
| `method` | `GET` or `POST` |
| `body_format` | `json` or `form` (POST only) |
| `phone_format` | `e164` → `+22222123456`, `intl` → `22222123456`, `local` → `22123456` |
| `success_contains` | optional text that must appear in the response body |
| `message_id_json_path` | optional dotted path to the provider's message id |

### Twilio

```json
{"account_sid": "AC…", "auth_token": "…", "from": "+1…"}
```
or `"messaging_service_sid": "MG…"` instead of `from`.

### Infobip

```json
{"base_url": "https://xxxxx.api.infobip.com", "api_key": "…"}
```

### Vonage (Nexmo)

```json
{"api_key": "…", "api_secret": "…"}
```

## Adding another provider in code

Create a class in `apps/sms/backends.py` with a `send(self, phone_e164, body)` method that returns the provider's message id or raises `SMSError`, add it to `BACKENDS` and to `SMSProvider.BACKENDS`. That is all.

## OTP security settings

| Variable | Default | Meaning |
|---|---|---|
| `OTP_TTL_SECONDS` | 300 | Code validity |
| `OTP_MAX_PER_HOUR` | 5 | Codes per phone per hour (×4 per IP) |
| — | 5 | Wrong attempts before the code is burned |

Codes are stored as HMAC-SHA256 hashes and are single use. With several web servers, set `CACHE_URL` to Redis so the per-hour limits are shared.
