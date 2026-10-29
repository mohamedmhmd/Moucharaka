# Money on the platform

## Ledger

Every user has a wallet with two balances: **available** (spendable) and **held** (escrow for open campaigns and pending withdrawals). The platform's own revenue sits in one wallet of kind `platform`.

All movements go through `apps.wallet.services.post()`, which locks the wallet row, refuses any negative balance, and writes an immutable `Transaction` line. Multi-step operations (release of funds, distributions, trades) run inside a single database transaction, so they are all-or-nothing. The test suite checks after every flow that the sum of all wallets equals deposits minus withdrawals.

**The total of all user wallets (available + held) must always equal the balance of the segregated bank account.** The staff dashboard shows both numbers for daily reconciliation.

## Deposits

1. The user chooses an amount and a method (Bankily, Masrvi, Sedad, bank transfer, cash at a partner agency). A deposit request with a reference such as `DEP-3FA9C1D2` is created.
2. The user sees step-by-step instructions with the merchant numbers set in **Paramètres de la plateforme**.
3. After paying, the user enters the transaction id from their bank SMS and attaches a screenshot.
4. Staff confirm it in **Back-office › Dépôts**, or a payment provider confirms it automatically through the webhook. The wallet is credited and the user gets an SMS.

A transaction id cannot be used twice for the same method.

### Automatic confirmation (webhook)

When you sign a merchant API agreement with Bankily, Masrvi, Sedad or an aggregator, have them call:

```
POST https://<your-domain>/wallet/webhook/<method>/      method = bankily | masrvi | sedad | bank | cash
Content-Type: application/json
X-Signature: <hex HMAC-SHA256 of the raw body with PAYMENT_WEBHOOK_SECRET>

{"reference": "DEP-3FA9C1D2", "amount": 5000, "transaction_id": "BK123456", "status": "success"}
```

The webhook checks the signature and that the amount matches the request, and it is idempotent (a replay does nothing). If the provider offers a redirect-to-pay flow instead, subclass `Gateway` in `apps/wallet/gateways.py` and return the payment URL from `initiate()`.

## Withdrawals

The user requests an amount and a destination (mobile wallet number or bank account), then confirms with an SMS code. The amount plus fee is moved to *held*. Staff pay it out and mark it as paid in **Back-office › Retraits** (with the payment reference), or reject it, which releases the funds.

## Campaign escrow → release

| Step | Investor wallet | Owner wallet | Platform |
|---|---|---|---|
| Invest | available → held | | |
| Cancel within 48 h / campaign fails | held → available | | |
| Release (after contract signature) | held → out; shares credited | + amount raised − success fee | + success fee |

## Distributions

- **Moucharaka**: the owner publishes a monthly report. The investors' share (`net profit × profit-share %`) is paid from the owner's wallet. The platform takes the management fee from it and the rest is split pro rata to shares (rounding cents go to the largest holder).
- **Mourabaha**: the owner pays each installment (principal + margin). The management fee applies to the margin part only.
- **Buyback (Moucharaka moutanaqisa)**: the owner buys N shares at a price. Shares are retired from every holder in proportion (largest-remainder allocation). The fee applies only to the gain above nominal value.
