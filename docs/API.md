# REST API v1

Base URL: `/api/v1/`. JSON in and out. Authenticate with `Authorization: Token <token>`.

## Authentication

| Call | Body | Result |
|---|---|---|
| `POST auth/otp/request` | `{"phone": "+33612345678", "purpose": "register" \| "login" \| "reset"}`. The code is sent on WhatsApp; numbers without `+` are read as Mauritanian. | `{"sent": true}` |
| `POST auth/otp/verify` | `{"phone", "purpose", "code"}` | register/reset: `{"verification": "<signed, 15 min>"}` · login: `{"token"}` |
| `POST auth/register` | `{"verification", "full_name", "password", "language": "ar"}` | `{"token", "user"}` |
| `POST auth/reset` | `{"verification", "password"}` | `{"ok": true}` |
| `POST auth/token` | `{"phone", "password"}` | `{"token", "user"}` |
| `GET/POST auth/kyc` | multipart: KYC fields (`full_name`, `nni`…) + `id_front`, `id_back` (photo or PDF) | the KYC file and its status |
| `GET/PATCH me` | `{"email", "preferred_language"}` | the current user |

Accounts are usable for investing only after the compliance team approves the KYC file (`status: "approved"`). Until then money endpoints return 403.

## Public data

| Call | Notes |
|---|---|
| `GET reference` | wilayas, moughataas, sectors, project kinds, financing models |
| `GET projects` | filters: `kind`, `financing_model`, `status`, `wilaya`, `sector`; `search` (name, ID, shop, neighbourhood, owner); `ordering` |
| `GET projects/<slug>` | full detail: terms, uses of funds, boutique profile, products, reports, installments, distributions, and `model` (scenarios + health indicators) |
| `GET projects/<slug>/trades` | price history |
| `GET users/<public_id>` | public track record and trust score |
| `GET market/listings?project__slug=<slug>` | active offers |

## Investor actions (approved accounts)

| Call | Body |
|---|---|
| `GET wallet` | balance, held, last 50 transactions |
| `GET/POST wallet/accounts` | payment accounts: `{"method": "bankily" \| "masrvi" \| "sedad" \| "bank", "number", "holder_name", "bank_name"?, "label"?, "is_default"?}` |
| `DELETE wallet/accounts/<id>` | remove an account |
| `GET/POST wallet/deposits` | `{"amount", "account": <id> or null for cash, "external_ref"?}` → includes payment instructions |
| `POST wallet/withdraw/otp` | sends the confirmation code on WhatsApp |
| `POST wallet/withdraw` | `{"amount", "account": <id>, "code"}` |
| `POST projects/<slug>/invest` | `{"shares": 10, "risk_acknowledged": true}` |
| `GET portfolio` | holdings and subscriptions |
| `POST market/listings` | `{"project": "<slug>", "shares", "price_per_share", "allow_partial", "note"}` |
| `POST market/listings/<id>/buy` | `{"shares"}` |
| `DELETE market/listings/<id>` | withdraw your own listing |

Rate limits: 60 requests/min anonymous, 240/min authenticated, plus OTP limits per phone and per IP.
