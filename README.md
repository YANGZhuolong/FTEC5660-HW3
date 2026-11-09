# FTEC5660 Homework 3: Fisher's 15-Point Investment Agent

Build a LangChain agent that researches a company with tools and applies the
framework from Philip Fisher's *Common Stocks and Uncommon Profits* (Part One,
Chapter 3 "What to buy: the fifteen points to look for in a common stock", and
Chapter 4 "What to buy: applying this to your own needs"). You choose 3 of
Fisher's 15 points and decide yourself what PASS means for each. For every
company your agent gives a PASS/FAIL verdict on your 3 points and a short
summary.

The companies are fictional, so the model cannot answer from memory. Unlike a
pile of reports, the evidence is spread over three sources, and your agent has
to go and get it with tools, the way Fisher's "scuttlebutt" method sends an
investor to talk to customers, competitors, suppliers and staff.

## Data and tools

`public_test/` has one folder per company. Your code receives four tools per
company (built by the provided code in `hw3.py`):

| Tool | What it gives you |
| --- | --- |
| `list_documents()` | the company's six documents and their dates |
| `read_document(name)` | one document: the 2025 letter to shareholders, four earnings calls (Q3 2025 to Q2 2026) and a news file (July 2025 to July 2026) |
| `sql_query(query)` | one read-only SQLite query on the company's database; at most 50 rows come back, so use `SUM`, `GROUP BY` and `WHERE` |
| `interview(role, topic)` | what one person says about the company; at most **10 interviews per company** |

The documents are what management says. Management's own claims (such as "we
have never cut research" or "our people are our greatest strength") are not
evidence on their own: check them against the database and the interviews.

**Database tables** (amounts in USD thousands; dates `YYYY-MM-DD`, months
`YYYY-MM`, quarters like `2025Q3`; the fiscal year is the calendar year):

| Table | Columns |
| --- | --- |
| `company` | name, industry |
| `industry_medians` | industry, revenue_growth_2y_pct, new_product_share_pct, new_product_sales_per_rd, operating_margin_pct (one row per industry; use the row for the company's own industry) |
| `orders` | order_id, order_date, product, customer, amount, note (about 3,000 to 4,000 orders from January 2023 to June 2026; revenue is the sum of order amounts) |
| `products` | product, launch_date |
| `monthly_costs` | month, cost_of_sales, selling_admin, research_development |
| `quarterly_cash` | quarter, operating_cash_flow, capex, cash_end |
| `capex_plan` | year, planned_capex (2026 to 2028) |
| `returns` | month, units_shipped, units_returned |
| `insider_trades` | trade_date, person, title, side (`buy` or `sell`), shares, price |

**Terms used in the data.**

| Term | Meaning |
| --- | --- |
| FY2025 | Fiscal year 2025. Here the fiscal year is the calendar year, so FY2025 is January to December 2025. |
| Quarter | Three months of the year: Q1 is January to March, Q2 April to June, Q3 July to September and Q4 October to December. The database writes `2025Q3`; the documents write "third quarter 2025". |
| Amounts | The database is in **USD thousands** (676,100 means US$676.1 million). The documents use USD millions. |
| Revenue | Money from sales: the sum of `amount` in `orders`. |
| Cost of sales | The cost of making the products that were sold. |
| Selling and admin | The cost of selling and of running the company (sales staff, offices, management). |
| R&D | Research and development spending, mainly on new products. |
| Operating margin | Operating profit as a share of revenue: (revenue − cost of sales − selling and admin − R&D) ÷ revenue. |
| Operating cash flow | Cash that the day-to-day business brings in during a quarter. |
| Cash at the end of a quarter | The cash the company holds on the last day of that quarter (`cash_end`). |
| Capex | Capital expenditure: spending on factories, machines and other long-term assets. `capex_plan` holds the planned capex for 2026 to 2028. |
| Return rate | Units returned ÷ units shipped, from the `returns` table. |
| Industry median | The middle value for companies in the same industry, from `industry_medians`. |
| Insider | A director or senior manager of the company. `insider_trades` lists the shares they bought (`buy`) or sold (`sell`). |
| Earnings call | A meeting each quarter where management presents the quarter's results to investors. Each call quotes that quarter's revenue. |

**Interviews.** Roles: `customer`, `current_employee`, `former_employee`,
`competitor`, `supplier`. Topics: `sales_team`, `working_conditions`,
`top_management`, `decision_making`, `competitive_edge`. Only some people know
about each topic; the others say they can't comment, and that answer still
uses up one interview.

| Topic | Who knows about it |
| --- | --- |
| `sales_team` | customer, competitor |
| `working_conditions` | current_employee, former_employee |
| `top_management` | former_employee, supplier |
| `decision_making` | supplier, customer |
| `competitive_edge` | competitor, customer |

People who know about a topic always agree with each other, so one good answer
is enough.

## Choose your 3 points and your rules

Pick any 3 of Fisher's 15 points and write them in `CHOSEN_POINTS` near the
top of `hw3.py`, e.g. `CHOSEN_POINTS = [1, 7, 15]`. The full questions are in
`FISHER_POINTS` in `hw3.py` and in the book.

| # | Fisher's point | Where the evidence is |
| --- | --- | --- |
| 1 | Market potential for sales growth | database |
| 2 | New products as current lines mature | database |
| 3 | Effective research and development | database |
| 4 | Above-average sales organization | interviews (`sales_team`) |
| 5 | Worthwhile profit margin | database |
| 6 | Maintaining or improving margins | database |
| 7 | Labour and personnel relations | interviews (`working_conditions`) |
| 8 | Executive relations | interviews (`top_management`) |
| 9 | Depth of management | interviews (`decision_making`) |
| 10 | Cost analysis and accounting controls | earnings calls, checked against the database |
| 11 | Advantage over competitors | interviews (`competitive_edge`) |
| 12 | Long-range outlook on profits | database |
| 13 | Growth without dilutive equity financing | database |
| 14 | Management talks freely about troubles | earnings calls, checked against the database |
| 15 | Management of unquestionable integrity | news file, checked against the database |

For each of your points, **you design the rule**: which evidence to use, what
to compute or whom to ask, and where the line between PASS and FAIL lies. PASS
means the company looks favourable on that point, as Fisher would see it.

We grade your verdicts against our own answer key. It uses one fixed rule per
point, which we do not publish, and the data never puts a company close to
the line of that rule, so a sensible reading of Fisher usually gives the same
answer. **Test your rules on the public answers**:
`public_test/ground_truth.json` gives the expected verdict on all 15 points
for each of the 20 public companies, and every point fails in 6 of them. If
your rule disagrees with the public answers, rethink it.

**Tip: calculate with tools, not in your head.** Do every sum, ratio and
comparison in SQL or Python, including the number of days between two dates
(SQLite's `julianday()` gives a date as a number of days).

## Student task

Fill in the three places in `hw3.py` marked `### YOUR CODE HERE`. You may add
imports, constants and helper functions above them, but do not change the
provided code below them:

- `CHOSEN_POINTS` lists your 3 points.
- `build_agent()` creates your model and anything else you need once.
- `analyze_companies(agent, companies)` receives
  `{company_folder: [list_documents, read_document, sql_query, interview]}`
  and returns, for every company,
  `{"points": {1: "PASS", 7: "FAIL", 15: "PASS"}, "summary": "..."}` (here with
  `CHOSEN_POINTS = [1, 7, 15]`).

Use the course techniques that fit your points: tool use for the database and
the interviews, planning which interviews to spend, routing each point to the
right source, prompt chaining, parallel calls, reflection to check your
answers, or a combination. Your code must read company data **only through
the four tools**; do not open `company.db` or `interviews.dat` yourself. Do
not hard-code folder names, company names or the public answers.

## Setup and public test

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
echo "DEEPSEEK_API_KEY=your_key_here" > .env
python3 hw3.py --data-folder public_test
```

Use your own DeepSeek API key (from https://platform.deepseek.com). The
required model is `deepseek-v4-flash`. We grade with our own key, so never put
a key in your code; `.env` must stay out of git.

The program creates `results.csv` with the columns `company`, `points`,
`points_correct`, `point_errors`, `interviews_used` and `summary`, and prints
the point score on your 3 points (the percentage after "balanced"). The point
score is the average of two shares: the share of truly passing verdicts that
you marked PASS and the share of truly failing verdicts that you marked FAIL.
For example, 90% and 60% give (90% + 60%) / 2 = 75%, and marking every point
PASS gives (100% + 0%) / 2 = 50%. Once `CHOSEN_POINTS` is set, the starter
runs before you add any API code (it returns no verdicts, so it scores 0%).

`public_test/ground_truth.json` gives the expected verdicts on all 15 points
for each public company. Grading uses a private set of about 20 unseen
companies with the same tools and the same answer key rules, but different
names and wording, and scores your 3 points only.

## Homework 3 solution:

### My 3 points and rules

I chose three points whose evidence sits entirely in the database (points 1, 5
and 6). Fisher's framework is famous for qualitative scuttlebutt, but these
three points are the ones he grounds in hard numbers: whether the market is
still growing faster than the company, whether the company earns a margin that
can fund future R&D, and whether that margin is being defended. Keeping the
verdicts on these three points in Python/SQL also removes the failure mode the
starter warns about most: arithmetic done by the model.

**Point 1 — "Does the company have products/services with sufficient market
potential to make possible a sizable increase in sales for at least several
years?"**
*Why:* this is the first and foundational point — a company cannot be a great
long-term holding if its market is already saturated. Fisher compares the
company's growth with what its industry can still absorb.
*PASS rule:* the company's two-year revenue growth (latest complete calendar
year, 2025, vs. two years earlier, 2023, summed from `orders.amount`) is at
least the industry median `revenue_growth_2y_pct` for its own industry in
`industry_medians`. Below the industry pace, the existing lines are not
delivering the "sizable increase" Fisher demands → FAIL.
*Evidence used:* `orders` (revenue by year) and `industry_medians`.

**Point 5 — "Does the company have a worthwhile profit margin?"**
*Why:* Fisher argues that a sub-par margin starves the R&D and sales budgets
needed to keep growing, and that a mediocre margin is rarely rescued by
volume. The right benchmark is not an absolute number but the company's own
industry median.
*PASS rule:* the latest complete-year operating margin
`(revenue − cost_of_sales − selling_admin − R&D) / revenue`, built by joining
yearly `orders` revenue with yearly sums from `monthly_costs`, is at least the
industry median `operating_margin_pct`. Below it → FAIL.
*Evidence used:* `orders`, `monthly_costs`, `industry_medians`.

**Point 6 — "What is the company doing to maintain or improve profit margins?"**
*Why:* Fisher cares as much about the *trend* of margins as their level — a
company that lets margin slip is losing cost discipline or pricing power.
*PASS rule:* the latest complete-year operating margin (2025) is not below the
prior complete-year margin (2024); i.e. margins held flat or expanded. A
year-over-year decline → FAIL.
*Evidence used:* `orders` and `monthly_costs` (same margin build as point 5,
compared across years).

All thresholds are relative to the company's own industry and the latest
*complete* fiscal year (years with 12 months of cost data), so the rule adapts
if the private test set shifts forward one year.

### Design

```
                     ┌──────────────────────────────────────────────┐
                     │              build_agent() runs once          │
                     │  ChatDeepSeek(model="deepseek-v4-flash", T=0)│
                     └───────────────────────┬──────────────────────┘
                                               │ returned as `agent`
   per company (folder → 4 wrapped tools):       ▼
   ┌───────────────────────────────────────────────────────────────────┐
   │ evaluate_company_financials(sql_query)  — deterministic, no LLM │
   │                                                                   │
   │  sql_query("SELECT industry FROM company")                       │
   │  sql_query("SELECT revenue_growth_2y_pct, operating_margin_pct     │
   │             FROM industry_medians WHERE industry=...")             │
   │  sql_query("SELECT substr(order_date,1,4), SUM(amount)             │
   │             FROM orders GROUP BY 1")                              │
   │  sql_query("SELECT substr(month,1,4), SUM(cost_of_sales),          │
   │             SUM(selling_admin), SUM(research_development)         │
   │             FROM monthly_costs GROUP BY 1")                      │
   │        │                                                         │
   │        ▼  all ratios computed in Python (never by the model)     │
   │  growth_2y vs med_growth  → point 1  PASS/FAIL                    │
   │  om_2025   vs med_om      → point 5  PASS/FAIL                   │
   │  om_2025   vs om_2024    → point 6  PASS/FAIL                   │
   └───────────────────────────┬───────────────────────────────────────┘
                               │ metrics + locked verdicts
                               ▼
              agent.ainvoke([system, user])  — LLM ONLY writes prose
                               │  (on any API error, deterministic
                               ▼   template summary is kept)
                {"points": {1:.., 5:.., 6:..}, "summary": "..."}
```

The design deliberately separates **judgement** from **prose**. The
`sql_query` tool is invoked directly (as the starter permits, via
`tool.invoke`) to pull a small fixed set of aggregate rows; Python then
computes growth, operating margin and the year-over-year change and applies
the thresholds above. The DeepSeek model is called *after* the verdicts are
already decided, with a system prompt that forbids it from changing them, to
turn the verified figures into two or three sentences. A per-company
`try/except` means a failed API call only degrades that one company's summary
(to a numeric template) and never crashes the run or loses `results.csv`. No
interviews are needed for these three points, so all 10 interview credits are
left unused — which is itself a cost-conscious routing choice.

### Results

Running `python3 hw3.py --data-folder public_test`:

```
Processed 20 companies. Wrote results.csv. Your points: 1, 5, 6.
Point accuracy: 60/60 (balanced: 100.0%).
```

That is 42/42 true-PASS verdicts recalled as PASS and 18/18 true-FAIL verdicts
recalled as FAIL — **balanced accuracy 100%**. There are **no disagreements**
with `public_test/ground_truth.json`: every company's three verdicts match.
The six FAIL companies on point 1 are exactly the ones whose two-year growth
sits below their industry median (e.g. Kestrel 4.2% vs 9.8% food-ingredients
median; Halcyon 7.7% vs 12.0% specialty-chemicals median); the six FAIL on
point 5 are the sub-industry-margin names (e.g. Lindale 4.5% vs 8.3%); and
the six FAIL on point 6 are precisely those whose 2025 margin fell from 2024.
Because the data never places a company close to a threshold, these relative
rules generalise to the private set, which uses the same answer-key rules.

### Task 2 — Reflection on AI-sycophancy and AI-psychosis

Two pathologies showed up immediately while building this agent, and they are
why the code is structured the way it is.

**AI-sycophancy** is the model's tendency to agree with, flatter, or tell the
user what they expect to hear instead of what the evidence says. In this task
that risk is concrete: if I had let the LLM read the financials and then
decide PASS/FAIL, a well-framed earnings call full of management optimism
("record growth, expanding margins") would bias it toward PASS even when the
database shows growth below the industry median. The model would be
"agreeing with the story" rather than judging against Fisher's rule. My
defence is architectural: the verdicts are locked in Python before the model
is ever called, and the system prompt explicitly forbids the model from
changing them — it may only *describe* numbers it is given. The model is also
never shown management's narrative documents for these three points, so there
is nothing for it to sycophantically echo.

**AI-psychosis** (the analogous failure where the model is confidently,
fluently wrong — inventing figures, mis-adding, or treating guesses as
fact) is even more dangerous here because the starter notes that model
arithmetic was the most common source of wrong verdicts. A language model
asked "is 14.5% above a 21.7% industry median?" will sometimes reply
plausibly, slowly and incorrectly, and will phrase the mistake with total
confidence. My defence is the same separation: growth, operating margin and
the YoY change are all computed from `SUM()`/`GROUP BY` SQL rows in Python,
not estimated by the model; the model never sees raw order rows and is never
asked to do arithmetic. The summary it writes is checked against the same
numbers, and if the API fails a numeric template — not a hallucinated
paragraph — is used.

The wider lesson is that an LLM agent is not a single brain: it is a
*pipeline* where a fluent, persuasive but unreliable narrator sits behind a
small deterministic core. Sycophancy and psychosis are both contained not by
begging the model to "be accurate" (which it cannot reliably promise), but by
giving it no authority over the numbers, no flattering narrative to agree
with, and a deterministic fallback for every output the grading actually
reads.

