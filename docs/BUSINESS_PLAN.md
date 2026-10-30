# Moucharaka business plan

Moucharaka is a Sharia-compliant marketplace where Mauritanians finance shops, trade operations and new companies, then trade their shares. This document explains how each use case makes money, why the prices are set where they are, and what volume is needed to break even. Every number lives in the admin (**Projets › Grilles tarifaires** and **Core › Paramètres de la plateforme**), so prices can change without code.

> All amounts in MRU (new ouguiya). Assumed rate ≈ 40 MRU per USD, to be updated.

## 1. Principles behind the pricing

1. **Earn when investors earn.** Most revenue is a share of what is actually raised or distributed. A failed campaign costs the owner only the review fee, and the investor nothing.
2. **Never touch principal.** Management fees apply to profits (Moucharaka) or to the margin (Mourabaha), never to capital returned to investors. This keeps the platform clear of anything resembling interest and makes the investor pitch simple.
3. **Free to come in, small fee to go out.** Registration, deposits and subscriptions are free so that money enters the platform. Withdrawals carry a small fee that covers mobile-money payout costs.
4. **Price by risk and effort.** A future company needs more due diligence than a 9-year-old hardware store, so its review and success fees are higher.

## 2. Use cases and their commercial model

| Use case | Contract | Review fee | Success fee | Management fee | Typical size | Duration |
|---|---|---|---|---|---|---|
| Boutique / existing shop | Moucharaka (profit share, often *moutanaqisa*) | 1 500 | 5 % of funds raised | 10 % of profits distributed | 200k – 1M | 24 – 36 months |
| Boutique stock financing | Mourabaha | 1 000 | 3 % | 12 % of the margin | 100k – 600k | 3 – 12 months |
| One-off operation (Tabaski sheep, import, purchase order) | Mourabaha (recommended) | 1 000 | 2.5 % | 12 % of the margin | 300k – 3M | 2 – 6 months |
| One-off operation with uncertain price | Moucharaka | 1 000 | 3 % | 10 % of profits | 300k – 3M | 2 – 6 months |
| Future company | Moucharaka only (blocked from Mourabaha) | 3 000 | 7 % | 8 % of distributions | 500k – 10M | 36 – 60 months |

**Platform-wide revenue**

| Source | Price | Why |
|---|---|---|
| Secondary market | 1 % buyer + 1 % seller | Liquidity is the main reason investors accept multi-year projects; the fee scales with trading volume. |
| Withdrawal | 20 MRU + 0.5 % | Covers the cost of paying out by Bankily, Masrvi, Sedad or bank transfer. |
| Featured campaign | 1 500 MRU / 7 days | Optional visibility for owners who want to close faster. |

### 2.1 Boutique (the core product)

**Why it works.** Neighbourhood shops in Nouakchott sell steadily but are permanently short of working capital: money is stuck in stock and in the customer credit notebook (*le carnet*). Banks rarely lend to them, and microfinance is expensive and interest-based. A Moucharaka lets them buy in bulk (2–3 points of extra margin), add a freezer or solar panels, and pay investors only out of real profit.

**What the platform provides to make it trustworthy.**
- a 12-month sales history, top products with margins, a balance sheet, rent and staffing, the shop pinned on a map, and photos;
- six automatic health ratios (break-even sales, safety margin, rent burden, stock cover, customer-credit exposure, consistency between foot traffic and declared sales);
- three scenarios (−20 %, plan, +15 %) and a simulator showing the investor's monthly payout;
- monthly reports compared with the declared history on one chart.

**Unit economics** (shop raising 500 000 MRU over 36 months, 45 % profit share, 18 %/year to investors):

| Item | MRU |
|---|---|
| Review fee | 1 500 |
| Success fee (5 %) | 25 000 |
| Management fee (10 % of ~270 000 distributed over 3 years) | 27 000 |
| **Revenue per shop** | **≈ 53 500** |
| Cost: KYC + file review (4 h) + field visit | − 4 000 |
| Cost: 36 monthly report checks (20 min each) | − 6 000 |
| Cost: WhatsApp messages, payment collection | − 2 000 |
| **Contribution** | **≈ 41 500 (~1 040 USD)** |

**Exit.** By default the owner progressively buys back the shares (*Moucharaka moutanaqisa*) after year 1. Investors see their capital come back on top of their profit share, and the owner ends up sole owner. Shares can also be resold on the market at any time.

### 2.2 One-off operations (Mourabaha)

**Why it works.** Mauritanian trade is seasonal: Tabaski sheep, Ramadan stock, the start of the school year, date harvests (*guetna*), fishing campaigns, public procurement orders. These are short, cash-intensive cycles with a known resale price. A Mourabaha (investors buy the goods and resell them to the trader at cost plus a fixed margin) fits them exactly, and the margin is known in advance.

**Why it is the most profitable segment.** Capital turns 2–4 times a year. A trader raising 900 000 MRU three times a year generates about 100 000 MRU of revenue for the platform per year:

| Per cycle (900 000 MRU, 9 % margin, 4 months) | MRU |
|---|---|
| Review fee | 1 000 |
| Success fee (2.5 %) | 22 500 |
| Management fee (12 % of the 81 000 margin) | 9 720 |
| **Per cycle** | **≈ 33 200** |
| **Per year (3 cycles)** | **≈ 100 000** |

**Risk controls built in.** A debt-coverage ratio (expected resale ÷ amount owed) is shown on every deal, along with collateral and its value, whether a buyer or purchase order already exists, and the trader's previous cycles. Installments are tracked daily: an overdue installment costs trust points, and after 90 days the project is flagged as defaulted, trading is suspended and investors are notified. There are no late-payment penalties paid to investors (riba); recovery goes through the guarantees.

**Recommended policy.** Once a trader has repaid two cycles on time with a score ≥ 750, waive the review fee (set it per case in the admin). This rewards loyalty and makes repeat cycles near-automatic.

### 2.3 Future companies

**Why it is different.** There is no sales history, so investors buy into a team, a market and a plan. The risk is higher and returns come later.

**Choices made in the product.**
- Mourabaha is blocked: a company with no revenue cannot honour a fixed margin.
- A longer questionnaire: market validation, pre-orders, founders' own investment, governance.
- A 3–5 year projection table, milestones, and a team section.
- The secondary market is essential: investors who cannot wait five years can sell.

**Pricing.** Review fee 3 000 MRU (two founder interviews plus a business-plan review), success fee 7 % (in line with regional equity crowdfunding), management fee 8 % of distributions. For a 1 500 000 MRU raise: 105 000 MRU of success fee, plus distributions later.

### 2.4 Secondary market

Fixed-price listings with partial fills. Prices are bounded between 10 % and 150 % of nominal value (configurable) to prevent manipulation. The owner cannot buy on the market (they use the formal buyback). Trading is only open on active projects and is suspended on default.

Revenue: with 10 % of outstanding shares changing hands each year, 2 % of that volume goes to the platform. More importantly, liquidity lets you sell 3-year projects to investors who are used to short-term tontines.

## 3. Who the investors are

1. **Diaspora** (France, Spain, Gulf countries, USA). They send money home every month and want to invest it transparently in something they can check. Passports and residence cards are accepted in KYC, and the site is in Arabic and French.
2. **Salaried workers in Nouakchott and Nouadhibou** with savings in tontines or livestock.
3. **Traders** who already lend informally to other traders and want a framework and guarantees.

Acquisition: neighbourhood launches (Arafat, El Mina, Toujounine, Dar Naïm, Ksar), mosque and association networks, WhatsApp-shareable project pages, and diaspora associations. Every funded shop becomes a billboard: its owner shares the page with their own customers.

## 4. Three-year projection (illustrative)

Assumptions: 1.6 applications per funded project (review fees), investors earn 18 %/year on boutiques, Mourabaha margin 9 %, 10 % of outstanding shares traded per year, no buybacks counted.

| | Year 1 | Year 2 | Year 3 |
|---|---|---|---|
| Boutiques funded (avg 400k) | 60 | 180 | 400 |
| Mourabaha cycles (avg 600k) | 40 | 150 | 360 |
| Companies funded (avg 1.5M) | 5 | 12 | 25 |
| **Volume raised (M MRU)** | **55.5** | **180** | **413.5** |
| Success fees | 2.3M | 7.1M | 16.0M |
| Review fees | 0.25M | 0.7M | 1.7M |
| Management fees | 0.5M | 2.1M | 5.5M |
| Market, withdrawals, featured | 0.25M | 0.9M | 2.3M |
| **Revenue (M MRU)** | **3.3** | **10.8** | **25.5** |
| Team, office, IT, messaging | 2.8M | 5.5M | 9.0M |
| Marketing | 0.6M | 1.5M | 3.0M |
| Legal, Sharia board, audit | 0.4M | 0.6M | 0.8M |
| **Operating result (M MRU)** | **−0.5** | **+3.2** | **+12.7** |

Revenue is about 6 % of the volume raised. With the year-1 cost base (3.8 M MRU) break-even needs about 5.5 M MRU raised per month; with the year-2 team (7.6 M MRU) about 10.5 M MRU per month, which the plan reaches early in year 2. The lever that matters most is the number of repeat Mourabaha traders: they generate revenue three times a year for a single onboarding.

## 5. Risks and safeguards

| Risk | Safeguard in the platform |
|---|---|
| Fraudulent owner | Phone OTP, NNI, ID and selfie reviewed by staff with automatic flags (duplicate name and date of birth, expired ID, PEP); documents and photos required; risk grade A–E; field visit. |
| Optimistic projections | Declared history vs. traffic × basket check, three scenarios, monthly actual-vs-plan chart, reviews from investors. |
| Late or missing reports | Daily job flags missed reports, sends WhatsApp reminders, and lowers the public trust score. |
| Default | 90-day rule, trading suspension, guarantees, public record on the owner's profile (deterrent). |
| Concentration | One investor can hold at most 40 % of a campaign. |
| Liquidity | Secondary market, diminishing-Moucharaka buybacks. |
| Fees perceived as riba | Fees are service fees on amounts raised, profits or margins, never on time or on principal. |

## 6. Regulatory path (to validate with a Mauritanian lawyer)

- Client money should sit in a segregated account at a licensed bank (preferably an Islamic bank or Islamic window). The platform's wallet is a ledger of that account; the staff dashboard shows the total that must match the bank balance. Any return on that float should not be taken as interest.
- Collecting public savings and holding e-money may require an approval from, or a partnership with, the Banque Centrale de Mauritanie (BCM). Start in partnership with a licensed institution that holds the funds.
- Appoint a Sharia board to validate the contract templates (Moucharaka, Moutanaqisa, Mourabaha) and the list of allowed activities.
- KYC data is kept for the legal retention period; staff access to identity documents is logged.

## 7. Roadmap that improves the economics

1. **Mobile-money APIs** (Bankily, Masrvi, Sedad) to confirm deposits instantly through the signed webhook that already exists.
2. **"Caisse" app for shop owners**: a simple sales log that fills the monthly report automatically. Reports become cheaper to check and more reliable, so financing gets cheaper.
3. **Supplier programme**: wholesalers give financed shops better prices and pay the platform a referral fee on purchases made with financed funds.
4. **Takaful partnership**: optional cooperative insurance on stock and livestock, sold with each campaign, with a commission to the platform.
5. **Mobile app** on top of the REST API that already exists (`/api/v1/`).
