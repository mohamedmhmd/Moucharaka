# WhatsApp verification and notifications

Members sign up and log in with their **WhatsApp number, from any country**. A 6-digit code is sent to WhatsApp to:
- confirm the number at sign-up;
- log in without a password;
- reset a password;
- confirm every withdrawal.

Members who opted in also receive important account updates on WhatsApp: account approved, deposit confirmed, payouts, installment reminders, late reports, and campaigns opening for projects they follow. Everything also appears in the in-app notifications.

SMS is kept only as an optional backup channel.

## 1. Choose a provider

| Option | Good for | What you need |
|---|---|---|
| **Meta WhatsApp Cloud API** (`whatsapp_cloud`) | Lowest cost, no intermediary | A Meta Business account, a WhatsApp Business phone number, a permanent access token |
| **Twilio WhatsApp** (`twilio_whatsapp`) | Simplest onboarding, one bill, Twilio support | A Twilio account with a WhatsApp sender |
| **Generic HTTP** (`http`) | Any WhatsApp provider (360dialog, Infobip, a local aggregator) that takes an HTTP call | Its API URL and keys; placeholders `{phone}`, `{code}`, `{message}`, `{lang}` |

Add the provider in the admin: **Messagerie › Fournisseurs de messagerie**, then run the action **"Envoyer un code de test à mon numéro"**.

Several providers can be active. They are tried by **priority** (lowest number first), and the next one is used automatically if a provider fails. **Préfixes desservis** limits a provider to some country codes, for example `222` for Mauritania, or `33,34` for France and Spain. Leave it empty to serve every country.

## 2. Create the two message templates

WhatsApp only lets a business start a conversation with a **pre-approved template**. You need two, each in **French (`fr`) and Arabic (`ar`)**. Meta usually approves them within minutes to a few hours.

### `moucharaka_code`: category **Authentication**

Meta generates the text ("*{{1}} est votre code de vérification.*") and adds a **Copy code** button. When you create it:
- choose **Copy code** as the button type;
- tick "Add security recommendation";
- set the expiry to 5 minutes, to match `OTP_TTL_SECONDS`.

### `moucharaka_update`: category **Utility**, two body variables

- French: `Moucharaka – {{1}} : {{2}}`
- Arabic: `مشاركة – {{1}}: {{2}}`

`{{1}}` is the notification title (for example "Dépôt confirmé"), and `{{2}}` its text. The platform fills both in the member's language.

## 3. Provider configuration (`config` field)

### Meta WhatsApp Cloud API

```json
{
  "phone_number_id": "123456789012345",
  "access_token": "EAAG…",
  "api_version": "v21.0",
  "otp_template": "moucharaka_code",
  "notification_template": "moucharaka_update",
  "languages": {"fr": "fr", "ar": "ar"}
}
```

- **`phone_number_id`:** in WhatsApp Manager › API Setup.
- **`access_token`:** create a *System user* in Meta Business Settings, give it the WhatsApp app, then generate a token with `whatsapp_business_messaging`. Temporary tokens expire after 24 h.
- **`languages`:** maps each member's language to the template language code. Change it if you created a template as, for example, `fr_FR`.

### Twilio WhatsApp

```json
{
  "account_sid": "AC…",
  "auth_token": "…",
  "from": "whatsapp:+14155238886",
  "otp_content_sid": {"fr": "HX…", "ar": "HX…"},
  "notification_content_sid": {"fr": "HX…", "ar": "HX…"}
}
```

Create both templates in Twilio's **Content Template Builder**. Use `{{1}}` for the code in the authentication template, and `{{1}}`/`{{2}}` for the title and text in the utility template. Copy the `HX…` identifiers here.

### Optional SMS fallback

Add a provider with an SMS backend (Twilio, Infobip, Vonage, or `http` with **canal = SMS**). Codes are then sent by SMS only when every WhatsApp provider failed. The order comes from:

| Variable | Default | Meaning |
|---|---|---|
| `OTP_CHANNELS` | `whatsapp,sms` | Channels tried for codes. Set `whatsapp` to never use SMS. |
| `NOTIFICATION_CHANNELS` | `whatsapp` | Channels for account notifications |
| `MESSAGING_FALLBACK_BACKEND` | `console` | Used only when no provider exists, for development: codes are printed in the server log and shown on screen when `DEBUG=True`. |

## 4. Who can sign up

Numbers are stored in international format (`+22222123456`, `+33612345678`). A number typed without `+` is read as Mauritanian (`PHONE_DEFAULT_REGION=MR`).

`PHONE_ALLOWED_COUNTRIES` defaults to `*` (the whole world). If you enable SMS fallback, consider restricting it, for example to `MR,FR,ES,BE,IT,DE,US,CA,AE,SA,QA,MA,SN,ML`. Bots abuse SMS codes to premium-rate numbers ("SMS pumping"), and you pay for every SMS they trigger. WhatsApp codes don't have this problem.

## 5. Opt-in and the 24-hour rule

- At sign-up, members accept WhatsApp notifications with a checkbox (checked by default). They can turn it off in **Paramètres**. Codes are always sent, because they are requested by the member.
- Template messages can be sent at any time. Free-text messages (`send_text`) are only delivered within 24 h of the member's last message to your WhatsApp number, so the platform uses templates for everything it sends.

## 6. Security

- Codes are 6 digits, valid 5 minutes and single-use. They are stored only as HMAC-SHA256 hashes, and are masked in the message log.
- Limits: 5 codes per number per hour, 20 per IP address, 5 wrong attempts per code.
- With several web servers, set `CACHE_URL` to Redis so these limits are shared.
