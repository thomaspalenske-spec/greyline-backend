"""FOMC-cycle equity-timing SHADOW — a ZERO-CAPITAL forward-test of Cieslak, Morse & Vissing-Jorgensen
(Stock Returns over the FOMC Cycle, Journal of Finance 2019).

THE EDGE: since 1994 the U.S. equity premium has been earned almost entirely in the EVEN weeks of the FOMC
cycle — weeks 0, 2, 4, 6 counting from the most recent FOMC meeting — while odd weeks are ~flat. The tradeable
rule is a calendar overlay: hold the broad index in even cycle-weeks, stay flat in odd weeks.

WHY IT'S A GOOD NEXT TEST (elite-OS literature survey 2026-08-20): it is orthogonal to GreyLine's confirmed
VRP edge (a macro-calendar TIMING effect on the index, not a vol premium), it is CHEAP EQUITY (hold SPY, ~1-2bps)
so it sidesteps the option round-trip cost that killed the directional edges, and it is LOW-TURNOVER (~biweekly)
which is the class of anomaly that survives costs (Novy-Marx & Velikov). Prefer the CYCLE (Cieslak et al.) over
the pre-FOMC *drift* (Lucca-Moench), which the literature shows decayed after 2015.

THE SHADOW: each trading day it records SPY's daily return and its FOMC cycle-week, forward-only from deploy.
The rule's return series (even-week days, cost-charged on each re-entry) is judged on the live edge court's
rigorous bar (verdict_from_returns: cost-net, 95% CI, min-N). The odd-week series is reported as a falsification
check (it should be ~0). NO orders, NO budget.

HONEST CAVEATS the test must survive: the independent sample is limited (~8 cycles/yr since 1994), the effect is
a timing overlay not standalone alpha, and — like every calendar effect — it may be arbitraged down out-of-sample,
which is exactly what the forward series measures."""

import csv
from datetime import datetime, date
from os import getenv
from pathlib import Path

from app.services.persistence.json_store import append_jsonl, read_jsonl

STATE = Path("app/data/fomc_cycle_shadow")
BARS = Path("app/data/historical")


class FomcCycleShadowEngine:

    LEDGER = STATE / "fomc_cycle_returns.jsonl"
    MIN_DAYS = 20                       # court gate: ~20 independent even-week trading days before a verdict
    INSTRUMENT = "SPY"
    COST_GRID_BPS = [0, 1, 2, 5]        # round-trip cost per even-week re-entry, swept in the report

    # FOMC announcement dates = the FINAL day of each scheduled two-day meeting (statement at 2pm ET). 2027 is
    # the Fed's tentative calendar. REFRESH ANNUALLY; extend at runtime via GREYLINE_FOMC_DATES_EXTRA (comma-sep).
    FOMC_DATES = [
        "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19", "2019-07-31", "2019-09-18", "2019-10-30", "2019-12-11",
        "2020-01-29", "2020-03-18", "2020-04-29", "2020-06-10", "2020-07-29", "2020-09-16", "2020-11-05", "2020-12-16",
        "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16", "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
        "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15", "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
        "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14", "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
        "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
        "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
        "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
        "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-16", "2027-07-28", "2027-09-22", "2027-11-03", "2027-12-15",
    ]

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_FOMC_CYCLE_SHADOW", "true") or "true").strip().lower() == "true"

    @classmethod
    def _cost(cls):
        try:
            return max(0.0, float(getenv("GREYLINE_FOMC_COST_BPS", "2"))) / 10000.0
        except (TypeError, ValueError):
            return 0.0002

    @classmethod
    def _fomc_dates(cls):
        dates = list(cls.FOMC_DATES)
        extra = (getenv("GREYLINE_FOMC_DATES_EXTRA", "") or "").strip()
        if extra:
            dates += [d.strip() for d in extra.split(",") if d.strip()]
        return sorted(set(dates))

    @classmethod
    def _cycle(cls, d_iso):
        """(cycle_day, cycle_week, even_week) for a date, relative to the most recent FOMC meeting on/before it.
        cycle_week = calendar days since that meeting // 7; even weeks (0,2,4,6...) are the high-return weeks.
        None if the date precedes the first known meeting."""
        prior = [x for x in cls._fomc_dates() if x <= d_iso]
        if not prior:
            return None
        try:
            days = (date.fromisoformat(d_iso) - date.fromisoformat(prior[-1])).days
        except (ValueError, TypeError):
            return None
        wk = days // 7
        return days, wk, (wk % 2 == 0)

    @classmethod
    def _returns(cls):
        """Sorted [(date, daily_return)] for the instrument from the daily bars (close/prev_close - 1)."""
        rows = []
        try:
            with open(BARS / f"{cls.INSTRUMENT}_daily.csv") as f:
                for r in csv.DictReader(f):
                    try:
                        c = float(r["close"])
                    except (TypeError, ValueError, KeyError):
                        continue
                    if c > 0:
                        rows.append((str(r["date"])[:10], c))
        except Exception:
            return []
        rows.sort()
        return [(rows[i][0], rows[i][1] / rows[i - 1][1] - 1.0)
                for i in range(1, len(rows)) if rows[i - 1][1] > 0]

    # ---- forward accrual (scheduler) ------------------------------------------------------------
    def run_if_due(self):
        """Append each not-yet-recorded trading day's return + its cycle-week. Forward-only: on first deploy
        record ONLY the latest observation (never backfill the decades of history — that would be in-sample).
        No orders. Best-effort."""
        if not self.enabled():
            return {"status": "FOMC_CYCLE_SHADOW_DISABLED", "ran": False}
        rets = self._returns()
        if not rets:
            return {"status": "FOMC_CYCLE_SHADOW_NO_DATA", "ran": False}
        led = read_jsonl(self.LEDGER) or []
        if not led:
            new = [rets[-1]]
        else:
            last = max(str(r.get("date")) for r in led)
            new = [(d, x) for d, x in rets if d > last]
        added = 0
        for d, x in new:
            cyc = self._cycle(d)
            if not cyc:
                continue
            append_jsonl(self.LEDGER, {"date": d, "ret": round(x, 6), "cycle_day": cyc[0],
                                       "cycle_week": cyc[1], "even_week": cyc[2],
                                       "recorded_at": datetime.utcnow().isoformat()})
            added += 1
        return {"status": "FOMC_CYCLE_SHADOW_RAN", "ran": True,
                "observations_added": added, "total_observations": len(led) + added}

    # ---- report / verdict -----------------------------------------------------------------------
    @staticmethod
    def _stats(rets):
        import math
        n = len(rets)
        if n < 2:
            return None
        mean = sum(rets) / n
        sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (n - 1))
        ann = (1 + mean) ** 252 - 1 if mean > -1 else -1.0
        return {"n": n, "mean_bps_per_day": round(mean * 10000, 3), "annualized_pct": round(ann * 100, 2),
                "sharpe_annualized": round((mean / sd) * math.sqrt(252), 2) if sd > 1e-12 else None,
                "hit_rate": round(sum(1 for r in rets if r > 0) / n, 3)}

    @classmethod
    def _even_net(cls, rows, cost):
        """Net even-week return series: each even-week day's return, minus a round-trip cost on RE-ENTRY days
        (the first even-week day after an odd week / gap) since that is where the strategy actually trades."""
        rows = sorted(rows, key=lambda r: str(r.get("date")))
        out, prev_even = [], False
        for r in rows:
            if not r.get("even_week"):
                prev_even = False
                continue
            ret = float(r.get("ret") or 0.0)
            if not prev_even:                 # re-entering the market this day -> charge the round-trip
                ret -= cost
            out.append(ret)
            prev_even = True
        return out

    def _cost_sweep(self, rows):
        out = []
        for bps in self.COST_GRID_BPS:
            net = self._even_net(rows, bps / 10000.0)
            m = sum(net) / len(net) if net else 0.0
            out.append({"cost_bps": bps, "net_mean_bps_per_day": round(m * 10000, 3),
                        "net_annualized_pct": round(((1 + m) ** 252 - 1) * 100, 2) if m > -1 else None})
        return out

    def report(self):
        from app.services.edge_persistence_engine import EdgePersistenceEngine as EP
        cost = self._cost()

        led = read_jsonl(self.LEDGER) or []
        even_net = self._even_net(led, cost)
        odd = [float(r.get("ret") or 0.0) for r in led if not r.get("even_week")]
        verdict = EP.verdict_from_returns(even_net, min_n=self.MIN_DAYS)
        verdict.update({"track": "FORWARD_SHADOW (out-of-sample, zero-capital) — the verdict",
                        "cost_bps_assumed": round(cost * 10000, 1),
                        "first_obs": led[0].get("date") if led else None,
                        "last_obs": led[-1].get("date") if led else None})

        # historical context — in-sample; for immediate insight, NOT the verdict
        hist = [{"date": d, "ret": x, **dict(zip(("cycle_day", "cycle_week", "even_week"),
                                                 self._cycle(d) or (None, None, None)))}
                for d, x in self._returns()]
        hist = [h for h in hist if h["cycle_week"] is not None]
        hist_even_net = self._even_net(hist, cost)
        hist_even_gross = [float(h["ret"]) for h in hist if h["even_week"]]
        hist_odd = [float(h["ret"]) for h in hist if not h["even_week"]]

        return {
            "as_of": datetime.utcnow().isoformat(),
            "shadow_enabled": self.enabled(),
            "engine": "FomcCycleShadowEngine",
            "instrument": self.INSTRUMENT,
            "signal": "long index in EVEN FOMC-cycle weeks (0,2,4,6), flat in odd weeks",
            "cost_assumption_bps": round(cost * 10000, 1),
            "min_days": self.MIN_DAYS,
            "forward_shadow": verdict,
            "forward_falsification": {
                "even_week": self._stats(even_net), "odd_week": self._stats(odd),
                "note": "the edge requires even-week net > 0 AND odd-week ~0 (the premium concentrates in even weeks)",
            },
            "historical_context": {
                "label": "IN-SAMPLE — NOT the verdict. SPY since bar history; cost-net even-week vs odd-week.",
                "even_week_net_at_assumed_cost": self._stats(hist_even_net),
                "even_week_gross": self._stats(hist_even_gross),
                "odd_week_gross": self._stats(hist_odd),
                "recent_5y_even_net": self._stats(hist_even_net[-650:]),
                "cost_sweep": self._cost_sweep(hist),
            },
            "note": ("FOMC-cycle equity timing (Cieslak-Morse-Vissing-Jorgensen 2019): the equity premium "
                     "concentrates in even cycle-weeks. Orthogonal to VRP, traded as cheap equity, low turnover. "
                     "The FORWARD_SHADOW earns the verdict; the historical context is in-sample. Calendar effects "
                     "can arbitrage down, so the net-of-cost forward series is the honest test."),
            "status": "FOMC_CYCLE_SHADOW",
        }
