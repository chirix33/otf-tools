"""Constants (opening stock, plant capacity) and the scopes: one per plant x 14-day period."""
from __future__ import annotations

from .data import DISPATCH_PLANTS, Records
from .sim import Scope

PERIOD_DAYS = 14
ORDER_BOOK_DAYS = 7
OPENING_COVER_DAYS = 3        # opening stock = 3 x mean daily order over the first 14 days
OPENING_WINDOW = 14
# plant capacity = 80th percentile of daily ordered weight (nearest rank). The spec draft said 90th; with it 24 of
# 60 scopes never reach capacity, with 80th 12 do (mean 3.8 capacity days per 14-day scope).
CAPACITY_PERCENTILE = 80
CAPACITY_ROUND_KG = 50        # rounded to the nearest 50 kg, so 80% of it is a whole number of kg


def opening_stock(rec: Records) -> dict[str, int]:
    return {p: int(OPENING_COVER_DAYS * sum(rec.orders[d][p] for d in range(1, OPENING_WINDOW + 1))
                   / OPENING_WINDOW + 0.5) for p in rec.products}


def capacity(rec: Records) -> dict[str, int]:
    out = {}
    for plant in DISPATCH_PLANTS:
        prods = rec.plant_products(plant)
        daily = sorted(sum(rec.orders[d][p] * rec.products[p].grams_per_unit for p in prods) / 1000
                       for d in range(1, rec.n_days + 1))
        k = -(-CAPACITY_PERCENTILE * len(daily) // 100) - 1          # nearest-rank percentile
        out[plant] = int(round(daily[k] / CAPACITY_ROUND_KG)) * CAPACITY_ROUND_KG
    return out


def n_periods(rec: Records) -> int:
    return (rec.n_days - ORDER_BOOK_DAYS) // PERIOD_DAYS


def make_scope(rec: Records, plant: str, period: int, opening: dict, caps: dict) -> Scope:
    first = (period - 1) * PERIOD_DAYS + 1
    last = first + PERIOD_DAYS - 1
    horizon = last + ORDER_BOOK_DAYS
    prods = rec.plant_products(plant)
    days = range(first, horizon + 1)
    return Scope(plant, period, first, last, horizon, prods,
                 {p: rec.products[p].grams_per_unit for p in prods}, {p: opening[p] for p in prods},
                 caps[plant], {d: {p: rec.production[d][p] for p in prods} for d in days},
                 {d: {p: rec.orders[d][p] for p in prods} for d in days})


def all_scopes(rec: Records) -> list[Scope]:
    opening, caps = opening_stock(rec), capacity(rec)
    return [make_scope(rec, plant, k, opening, caps)
            for k in range(1, n_periods(rec) + 1) for plant in DISPATCH_PLANTS]
