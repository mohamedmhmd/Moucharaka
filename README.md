# Moucharaka — مشاركة

Sharia-compliant crowdfunding and share-trading platform for Mauritania, in Arabic (right-to-left) and French.

- **Three project types**: an existing boutique, a one-off trade operation (Tabaski sheep, imports, purchase orders), or a future company.
- **Two contracts, clearly labelled everywhere**: *Moucharaka* (share of real profits, with progressive buyback) and *Mourabaha* (fixed margin on goods, paid in installments).
- **Boutique model**: 12-month sales history, top products and margins, balance sheet, rent and staff, shop on a map, six health ratios, three scenarios and an investor simulator. Monthly reports are charted against the declared history.
- **Verified members**: sign-up with phone and SMS code, then NNI, ID document, selfie and financial profile. Staff approve the file, and documents are stored outside the public web root.
- **Wallet with escrow**: Bankily, Masrvi, Sedad, bank transfer or cash. Funds stay held until a campaign succeeds and are refunded automatically if it fails. Withdrawals are confirmed by SMS code.
- **Distributions**: monthly profit shares, Mourabaha installments and buybacks, paid pro rata to every holder.
- **Secondary market**: fixed-price listings with partial fills, price bounds and fees.
- **Trust score (0–1000)**: built from identity, on-time payments, report discipline, investor reviews and outcomes. Each member has a public track record page.
- **Back-office**: KYC review with documents side by side and automatic flags, project review with a checklist and risk grade, deposit/withdrawal desks, report verification, revenue and escrow reconciliation.
- **Configurable SMS providers** with priority, operator-prefix routing and automatic failover.
- **REST API** (`/api/v1/`) ready for a mobile app.
- A questionnaire of more than 60 questions (bilingual and editable in the admin) adapted to each project type.

Business model and fees: [`docs/BUSINESS_PLAN.md`](docs/BUSINESS_PLAN.md) · SMS: [`docs/SMS.md`](docs/SMS.md) · Money flows: [`docs/PAYMENTS.md`](docs/PAYMENTS.md) · API: [`docs/API.md`](docs/API.md)

## Run it locally (5 minutes)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then set DEBUG=True and ALLOWED_HOSTS=* for local use
python manage.py migrate
python manage.py seed_demo      # optional: demo users, projects and 4 months of history
python manage.py runserver
```

Open http://127.0.0.1:8000 (Arabic) or http://127.0.0.1:8000/fr/ (French).

Demo accounts created by `seed_demo` (password `Moucharaka#2026`):

| Role | Phone |
|---|---|
| Superuser (admin) | 20000000 |
| Staff (compliance + operations) | 20000001 |
| Boutique owner with 4 months of history | 22000101 |
| Investor | 33000000 |

With `DEBUG=True` and the console SMS backend, OTP codes are shown on screen and printed in the server log.

## Tests

```bash
python manage.py test apps
```

The suite covers the full money lifecycle (escrow, refunds, release, profit distribution, installments, defaults, market trades, buybacks) and checks that the ledger always balances. It also covers OTP, SMS failover, sign-up through KYC approval, private document access, the API, signed payment webhooks, and rendering of every page in both languages.

## Deploy

The project only needs Python 3.11+ and a database. Static files are served by WhiteNoise, and fonts and JS libraries are bundled, so no CDN is needed. Configuration is entirely through environment variables (see `.env.example`).

Whatever the host, do this after the first deployment:

1. `python manage.py migrate`, then `python manage.py createsuperuser` (log in with the phone number).
2. In `/admin/` set **Paramètres de la plateforme**: merchant numbers, bank details and fees.
3. Add at least one **Fournisseur SMS** and send yourself a test SMS.
4. Schedule `python manage.py run_daily` once a day. It closes campaigns, flags late installments and reports, sends reminders, expires listings and deposits, and recomputes trust scores.
5. Add staff members to the **Conformité** and/or **Opérations** groups.

### Docker / any VPS with Docker

```bash
cp .env.example .env   # set SECRET_KEY, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

This runs PostgreSQL, the web app (gunicorn on port 8000, migrations at start-up) and a scheduler for the daily jobs. Put nginx or Caddy in front for HTTPS (`deploy/nginx.conf`).

### Plain VPS (Ubuntu, Debian)

```bash
sudo apt install python3-venv postgresql nginx
git clone … /srv/moucharaka && cd /srv/moucharaka
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env    # DATABASE_URL=postgres://…, SERVE_MEDIA=False
.venv/bin/python manage.py migrate && .venv/bin/python manage.py collectstatic --noinput
sudo cp deploy/moucharaka.service /etc/systemd/system/ && sudo systemctl enable --now moucharaka
sudo cp deploy/nginx.conf /etc/nginx/sites-enabled/moucharaka && sudo systemctl reload nginx
sudo certbot --nginx -d your-domain
crontab -e   # add the line from deploy/crontab.txt
```

### cPanel / Plesk shared hosting ("Setup Python App")

1. Create a Python app (3.11+), with the application root set to the project folder and the startup file `passenger_wsgi.py` (entry point `application`).
2. In the app's virtualenv: `pip install -r requirements.txt`. For a MySQL database, replace `psycopg[binary]` with `mysqlclient` and set `DATABASE_URL=mysql://user:pass@localhost/dbname`.
3. Put the variables in `.env` (or in the panel's environment variables). Keep `SERVE_MEDIA=True` unless the panel serves `/media/`. Set `PRIVATE_MEDIA_ROOT` to a folder **outside** `public_html`.
4. Run `python manage.py migrate` and `python manage.py collectstatic --noinput` from the panel's terminal.
5. Add a cron job: `python manage.py run_daily`, daily.

### Render, Railway, Heroku-style PaaS

A `Procfile` is included (release: migrate; web: gunicorn). Add a PostgreSQL add-on (its `DATABASE_URL` is read automatically), set `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and `USE_X_FORWARDED_PROTO=True`, and use a persistent disk for `MEDIA_ROOT` and `PRIVATE_MEDIA_ROOT`. Schedule `python manage.py run_daily` with the platform's cron feature.

## Project layout

```
apps/
  accounts     phone + OTP auth, KYC (NNI, ID, selfie), approval, private documents
  sms          provider models, backends (HTTP, Twilio, Infobip, Vonage, console), failover service
  projects     projects, boutique/company/deal models, questionnaire, reports, installments, wizard, owner workspace
  wallet       ledger, deposits, withdrawals, payment gateways, webhook
  investments  escrow, release, distributions, buybacks, defaults
  market       share listings and trades
  trust        trust score engine, events, investor reviews, public profiles
  staff        back-office screens
  api          REST API (DRF)
  core         home, dashboard, portfolio, info pages, platform settings, notifications, audit log, daily jobs
templates/     server-rendered pages (one set for both languages)
locale/ar/     Arabic translation (source strings are in French)
static/        CSS (RTL-aware logical properties), JS, bundled fonts, Chart.js, Leaflet
deploy/        gunicorn, nginx, systemd, cron, Docker entrypoint
```

## Translations

UI strings are written in French in the code and translated to Arabic in `locale/ar/LC_MESSAGES/django.po`. After changing text:

```bash
pip install -r requirements-dev.txt
python scripts/i18n.py extract    # adds new strings to the .po
# translate the new entries (any PO editor, e.g. Poedit)
python scripts/i18n.py compile    # builds django.mo
```

Content managed in the admin (questionnaire, sectors, wilayas) has its own French and Arabic fields.

## Before going live

- Have the contract templates and the list of allowed activities validated by a Sharia board.
- Confirm the regulatory set-up with a Mauritanian lawyer and the Banque Centrale de Mauritanie. You may need to partner with a licensed bank that holds client funds in a segregated account (see the business plan, section 6).
- Replace the template terms of use (`templates/core/terms.html`).
- Sign merchant agreements with Bankily, Masrvi and Sedad, then connect their callbacks to the webhook (see `docs/PAYMENTS.md`).
