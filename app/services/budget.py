"""Budget allocation: fit a diminishing-returns response curve per channel from daily
history, then reallocate budget to equalise marginal return, within guard-rails.

This is a fast, directional recommender. For large budgets, feed the same data into a
proper marketing-mix model (Google Meridian / Meta Robyn) — see README."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from .. import db
from ..connectors import label


def _fit(spend: np.ndarray, value: np.ndarray) -> tuple[float, float, float]:
    """value ≈ a · spend^b. Returns (a, b, r2) from log-log OLS with b clamped to (0.2, 0.95)."""
    m = (spend > 1) & (value > 0)
    if m.sum() < 14:
        tot_s, tot_v = spend.sum(), value.sum()
        b = 0.7
        a = (tot_v / len(spend)) / max(1e-9, (tot_s / len(spend)) ** b) if tot_s else 0
        return a, b, 0.0
    x, y = np.log(spend[m]), np.log(value[m])
    b, ln_a = np.polyfit(x, y, 1)
    pred = ln_a + b * x
    r2 = 1 - ((y - pred) ** 2).sum() / max(1e-9, ((y - y.mean()) ** 2).sum())
    b = float(min(0.95, max(0.2, b)))
    # re-solve a with clamped b so the curve passes through observed averages
    a = float(np.exp(np.mean(y - b * x)))
    return a, b, float(r2)


def recommend(client_id: int, monthly_budget: float | None = None, objective: str = "revenue", max_shift: float = 0.3,
              history_days: int = 90) -> dict:
    col = "revenue" if objective == "revenue" else "conversions"
    since = str(date.today() - timedelta(days=history_days))
    plats = [r["platform"] for r in db.rows("SELECT DISTINCT platform FROM ad_metrics WHERE client_id=? AND date>=?", (client_id, since))]
    chans = []
    for p in plats:
        rs = db.rows(f"SELECT date, SUM(spend) s, SUM({col}) v FROM ad_metrics WHERE client_id=? AND platform=? AND date>=? GROUP BY date",
                     (client_id, p, since))
        s = np.array([r["s"] or 0 for r in rs], dtype=float)
        v = np.array([r["v"] or 0 for r in rs], dtype=float)
        if s.sum() <= 0:
            continue
        a, b, r2 = _fit(s, v)
        recent = db.one("SELECT SUM(spend) s FROM ad_metrics WHERE client_id=? AND platform=? AND date>=?",
                        (client_id, p, str(date.today() - timedelta(days=29))))["s"] or 0
        chans.append({"platform": p, "label": label(p), "a": a, "b": b, "r2": round(r2, 2), "daily_now": recent / 30})
    if not chans:
        return {"channels": [], "note": "Not enough paid media history yet."}

    cur_total = sum(c["daily_now"] for c in chans)
    total = (monthly_budget / 30.4) if monthly_budget else cur_total

    def resp(c, d):
        return c["a"] * d ** c["b"] if d > 0 else 0.0

    def marginal(c, d):
        return c["a"] * c["b"] * max(d, 1) ** (c["b"] - 1)

    # scale everyone to the target total first, then shift in small steps toward highest marginal return
    k = total / cur_total if cur_total else 1
    alloc = {c["platform"]: c["daily_now"] * k for c in chans}
    lo = {c["platform"]: c["daily_now"] * k * (1 - max_shift) for c in chans}
    hi = {c["platform"]: c["daily_now"] * k * (1 + max_shift) for c in chans}
    step = total * 0.005
    for _ in range(2000):
        best = max((c for c in chans if alloc[c["platform"]] + step <= hi[c["platform"]]), key=lambda c: marginal(c, alloc[c["platform"]]), default=None)
        worst = min((c for c in chans if alloc[c["platform"]] - step >= lo[c["platform"]]), key=lambda c: marginal(c, alloc[c["platform"]]), default=None)
        if not best or not worst or best is worst:
            break
        if marginal(best, alloc[best["platform"]] + step) <= marginal(worst, alloc[worst["platform"]]) * 1.01:
            break
        alloc[best["platform"]] += step
        alloc[worst["platform"]] -= step

    rows = []
    for c in chans:
        now_d, new_d = c["daily_now"], alloc[c["platform"]]
        rows.append({
            "platform": c["platform"], "label": c["label"],
            "current_monthly": round(now_d * 30.4, 2), "recommended_monthly": round(new_d * 30.4, 2),
            "change_pct": round(new_d / now_d - 1, 3) if now_d else None,
            "expected_now": round(resp(c, now_d) * 30.4, 2), "expected_new": round(resp(c, new_d) * 30.4, 2),
            "marginal_return": round(marginal(c, new_d), 3), "saturation": round(1 - c["b"], 2), "fit_r2": c["r2"],
            "confidence": "high" if c["r2"] >= 0.5 else "medium" if c["r2"] >= 0.2 else "low",
        })
    rows.sort(key=lambda r: -r["recommended_monthly"])
    base_scaled = sum(resp(c, c["daily_now"] * k) for c in chans) * 30.4
    new = sum(r["expected_new"] for r in rows)
    return {"objective": objective, "monthly_budget": round(total * 30.4, 2), "channels": rows,
            "expected_total": round(new, 2), "expected_at_current_mix": round(base_scaled, 2),
            "uplift_pct": round(new / base_scaled - 1, 4) if base_scaled else None, "max_shift": max_shift,
            "note": "Directional recommendation from 90-day response curves, capped at ±{:.0%} per channel after scaling the current mix to the new total. Test changes over 2–4 weeks.".format(max_shift)}

