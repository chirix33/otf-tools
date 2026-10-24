# Domain spec: Manufacturing (SupplyGraph)

Status: BUILT 2026-10-23 (code `domains/manufacturing/`, runs `runs/mfg_d01..05`, `runs/mfg_dev`, report
`domains/manufacturing/VALIDATION.md`). The decisions taken while building, including deviations from the draft
below, are in "As built" at the end. Paper name: "manufacturing" (body: "manufacturing supply chain").

## Source

SupplyGraph (Wasi, Islam, Akib; arXiv 2401.15299), LGPL-2.1. Real records from the central database of a
fast-moving consumer goods manufacturer in Bangladesh: 40 products (41 columns; `POP001L12P.1` is a second
column for one product, to be checked and merged or dropped), 221 daily time points, 2023-01-01 to 2023-08-09.
Daily series per product, in units and in weight: `Production`, `Sales Order`, `Delivery To distributor`,
`Factory Issue`. Node files give each product's group, sub-group, plant and storage location.

## What is real and what is simulated

- **Real (exogenous inputs, used exactly as recorded):** daily production per product, daily sales orders per
  product, product to plant and storage-location assignment, product weights (units vs weight files give
  weight per unit).
- **Simulated (endogenous, by the written policy below):** stock on hand, dispatches, backorders, stock-outs.
  The real `Delivery` and `Factory Issue` series are not used as outcomes (they follow the company's unknown
  policy); they may calibrate the dispatch capacity.

Paper wording: "real production and demand records; simulated stock and dispatch policy".

## The policy (goes into each document's front matter, in prose)

Per storage location, per day, in this order:
1. **Production arrives**: the day's production of each product is added to its stock at its storage location.
2. **Orders join the queue**: the day's sales order of each product becomes one order (id, product, quantity,
   day). Unfilled earlier orders stay in the queue (backorders).
3. **Dispatch**: each plant has a daily dispatch capacity in kilograms (one truck fleet shared by all its
   products). Orders are served oldest first (ties: smaller quantity first, then product code); an order
   ships as much as stock allows and as capacity allows; the rest stays backordered. Capacity used by one
   product is not available to others the same day (this is what couples products).
4. **Records**: end-of-day stock, shipped and backordered quantity per product.

Constants (stated in the front matter): opening stock per product = its mean daily order over the first 14 days
x 3; plant capacity = 90th percentile of that plant's daily ordered weight. Both computed once from the data and
written into the document, so a reader has everything needed.

## Document layout

- Front matter: what the records are, the policy above, the constants, units.
- One **scope** per plant x 4-week period, titled e.g. `Plant 2120, Period 03` (scope name appears in every
  question). Each scope has sections:
  - **Products** (table: code, group, storage location, kg per unit, opening stock)
  - **Daily ledger** (table: day, product, produced, ordered, shipped, backordered, stock)
  - **Events** (list, time-ordered: stock-outs, orders fully backordered, backlog cleared, capacity reached)
  - **Order book** (table, last scope day only: orders and planned production for the next 7 days; real values
    from the following days). This is what makes predictive questions answerable.
- 3 test documents (periods split across them, ~15-20 scopes each) + 1 dev document.

## Question templates and gold

All gold from the reference simulator (`domains/manufacturing/sim.py`, to be written, independent of `otf/`).

- **Descriptive** (open-ended, one word/number): stock of X at end of day D; units backordered for X on day D;
  first stock-out day of X; how many products hit capacity limits in the scope.
- **Explanatory** (MC, multi-correct): "Why was the order for X on day D not fully shipped?" Candidate causes:
  stock of X ran out; plant capacity was used by product Y's orders; an earlier backorder of X took priority;
  production of X on day D-k was below its order. A choice is correct iff removing/neutralising that cause in
  the simulator makes the shortfall disappear (CLEVRER's definition of responsibility).
- **Predictive** (MC or yes/no): using the order book, "Will X be backordered at the end of day D+k?", "Which
  of these products will stock out first in the next 7 days?" Gold: simulate the next 7 days with the real
  future inputs listed in the order book.
- **Counterfactual** (MC, multi-correct, CLEVRER-style "which of the following would happen"), interventions mixed
  roughly equally:
  - removal: "If the order for Y on day D had not been placed ..."
  - changed value: "If production of X on day D had been zero (a line stoppage) ..."
  - delay: "If the production of X on day D had arrived 3 days later ..."
  - capacity: "If the plant's dispatch capacity had been 20% lower from day D ..."
  Gold: re-run from the scope's start with the change, all other inputs as recorded.

Balance: per template, keep a mix of true and false choices; drop templates whose answer is constant.

## Size and checks

~300 test questions (~75 per type), dev document ~40 questions. Checks: simulator reproduces its own ledger
exactly (determinism); conservation (stock change = produced - shipped) on every row; 20 hand-checked questions.

## Open items (resolved, see below)

- Confirm the duplicate product column and units/weight consistency.
- Choose period length so each scope has some stock-outs and capacity hits (target: most scopes have at least 2).

## As built (2026-10-23)

Rebuild: `python -m domains.manufacturing.build` then `python -m domains.manufacturing.validate` (from
`implementation-1/`, project Python; needs reportlab and pypdfium2, no LLM, no GPU). Deterministic (seed 2027).

**Data decisions**

- **Duplicate column.** The node list has the code `POP001L12P` twice (NodeIndex 12 and 20); the temporal
  files call the second column `POP001L12P.1`. The two series differ (production agrees on only 47 of 221 days,
  mostly days where both are 0), with the same group and the same 10.92 kg per unit. Treated as two distinct
  products sharing a code, named `POP001L12P-A` (index 12) and `POP001L12P-B` (index 20). Neither is dropped.
- **Units and weight.** Weight files are in tonnes; kg per unit = 1000 x weight / units, constant per product
  (largest spread 1.5e-14). Units are cases. Quantities are rounded half-up to whole units (some order cells carry
  float noise such as 342.0000000000001).
- **Plants.** The records are company-wide per product, but the node file lists every plant that stores a product
  (up to 13 each). Each product gets one dispatch plant: of 2103 and 2114 (the two 21xx plants with the most
  storage records) and 1914 and 1912 (same for 19xx; 1912 ties 1915 and the lower code wins), the one where the
  product has the most storage records. Result: Plant 2103 has 13 products, 2114 has 5, 1914 has 7, 1912 has 3.
  Storage location is the one recorded for the product at that plant.
- **Products left out (13):** 10 with no recorded production in the whole series (POP015K, SO0005L04P,
  SO0002L09P, SO0001L12P, SO0500M24P, ATPPCH5X5K, ATPA1K24P, MAPA1K24P, EEA500G12P, EEA200G24P; all have
  tiny orders and would only ever be backordered) and 3 with no storage record at any of the four plants
  (ATWWP002K12P, MAP1K25P, MAC1K25P). 28 products remain.

**Policy and constants** (exactly as in the draft, plus these choices)

- Period = **14 days** (draft said 4 weeks): 15 periods with a full 7-day order book after each (days 1-210,
  order books to day 217 of 221), so 60 scopes; 4-week periods would give only 28.
- Every period is an **independent run**: opening stock, no open orders. This keeps every scope self-contained
  and makes the counterfactual re-run "from the scope's start".
- Opening stock = 3 x mean daily order over days 1-14, rounded (as drafted).
- **Capacity = 80th percentile** (nearest rank) of the plant's daily ordered weight over all 221 days, rounded to
  50 kg (so 80% of it is whole kg). **Deviation:** the draft said 90th; with it 24 of 60 scopes never reached
  capacity; with the 80th, 12 never do and the mean is 3.8 capacity days per 14-day scope. Values: 1912 34,500 kg,
  1914 192,950 kg, 2103 407,700 kg, 2114 300,000 kg.
- Dispatch tie-break uses the order's *remaining* quantity (smaller first), then product code; whole units only;
  an order that cannot fit does not block later orders.
- "Runs out of stock" on a day = end-of-day stock 0 while units are backordered. "Capacity reached" = some order
  shipped less than stock allowed because capacity was too small. Both defined in the front matter.
- Order book section also lists the **open orders at the end of the period** (product, day placed, units still
  open), because dispatch priority depends on each order's day; without it a reader would have to reconstruct the
  queue.

**Document split.** Period 01 (4 scopes) = dev document `mfg_dev` (40 questions, 10 per type). Periods 02-15
(56 scopes) shuffled with seed 2027 and dealt into **5 test documents** (12, 11, 11, 11, 11 scopes; 42-62 pages)
of 60 questions each (15 per type): **300 test questions, 75 per type**. (The draft said 3 documents; 5 were
asked for when the build was commissioned.)

**Questions** (all gold from `sim.py`, re-derived by a second runner in `validate.py`)

- Descriptive (open-ended, 7 templates, cycled): stock / backordered / shipped of a product on a day; first
  stock-out day of a product; number of capacity days; number of products that ran out of stock; product with the
  most units backordered on a day.
- Explanatory (MC): "the order for X placed on day D did not ship in full on day D; which are responsible?"
  Causes: not enough stock (but-for: unlimited stock that day), capacity reached (unlimited capacity that day),
  orders for another product Y used capacity (Y's shipments that day use no capacity), older backorders of X
  served first (they are skipped that day), production on day D or D-1 below that day's order (raised to the
  order). Correct iff the but-for run ships the order in full on day D. The question text states this definition.
- Predictive (MC): statements about the 7 order-book days (backordered at end of a day, runs out of stock in the
  window, capacity reached on a day, an order ships in full), and "which product runs out of stock first".
- Counterfactual (MC): the four change kinds in equal shares (19/19/19/18 in test), re-run from the period start
  with that change only. Statements as for predictive plus "stock at end of day E would be higher/lower than the
  recorded N". Each question has at least one choice whose truth differs from the record (so copying the ledger
  never gets a question right) and no choice about the changed product's own stock on the day of the change.
- Balance: each MC question has 4 choices (first-stockout: 3-4), with 1-3 true (random per question); every
  explanatory cause kind ends up ~50% true; per-template true share 0.33-0.53; no constant-answer template.

**Output layout** (per run folder): `document.pdf`, `manifest.json` (`scopes` plus a CLEVRER-shaped `videos`
list whose `scene_index` is the scope title), `items.jsonl` (CLEVRER `QAItem` fields, `scene_index` = scope
title; loads with `clevrer_bench.data.load_items` and scores with `clevrer_bench.scoring.score`),
`items_all.jsonl` (identical, nothing subsampled), `build_config.json`, `questions.jsonl` (no type, no gold;
field `scope` instead of `video`; `prompt` = scope title, question, choices, as for CLEVRER), `gold.jsonl`, and
`gold_meta.jsonl` (interventions and statement arguments behind each gold label; scoring/validation only, never
for a system).

**Not built here (needs the harness/OTF sessions):** `navmap.json` (built by `otf/navmap.py`, which this
benchmark must not import); a domain-neutral `ANSWER_INSTRUCTIONS` (the current one names CLEVRER) with digits
for numbers and product codes for names; harness support for `scope` titles in `build_question_prompt` (it
hard-codes "Video <n>"; using `questions.jsonl`'s `prompt` field avoids it).
