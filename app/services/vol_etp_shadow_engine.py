"""Long-vol ETP SHADOW — the regime-conditioned long-vol leg, measured with ZERO capital.

The alt-asset scan added VXX/VIXY (long-vol ETPs). Held unconditionally they BLEED — that bleed IS the
variance-risk premium the SVXY carry sleeve harvests on the SHORT side. So the only meaningful thing to
measure is a REGIME-CONDITIONED long-vol rule: go long VXX ONLY in BACKWARDATION (VIX >= VIX3M), where the
VIX-futures roll works FOR a long-vol holder; stand flat in contango (the carry sleeve's regime). This is
the LONG leg that complements VolTermStructureCarryEngine's short leg — together, the full term structure.

Reuses the carry sleeve's EXACT term-structure signal (VIX/VIX3M) so both legs read the same regime. Weekly
non-overlapping cohorts, settled at live quotes, net of cost, judged on the live edge court's bar
(small-sample-t 95% CI + min-N). NO orders, NO budget — how the long-vol leg earns its way toward a verdict.

NOTE: backwardation is RARE (term structure is in contango most of the time), so cohorts accrue SLOWLY and
in clusters around stress — that's the honest cadence of a tail-leg signal, not a bug.
"""

import json
import math
from datetime import datetime, date, timedelta
from os import getenv
from pathlib import Path


def _rigorous_verdict(rets, min_n):
    try:
        from app.services.edge_persistence_engine import EdgePersistenceEngine
        return EdgePersistenceEngine.verdict_from_returns(rets, min_n=min_n)
    except Exception:
        return None


class VolEtpShadowEngine:

    STATE = Path("app/data/vol_etp_shadow")
    OPEN = STATE / "open_cohort.json"
    CLOSED = STATE / "closed_cohorts.jsonl"

    INSTRUMENT = "VXX"            # representative front-month long-vol ETP (most liquid)
    HOLD_DAYS = 5                 # non-overlapping weekly hold, settle at live quotes
    MIN_COHORTS = 8
    PERIODS_PER_YEAR = 252 / 5

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_VOL_ETP_SHADOW", "true") or "true").strip().lower() == "true"

    @staticmethod
    def _cost_roundtrip():
        try:
            return float(getenv("GREYLINE_COST_BPS_ROUND_TRIP", "10")) / 10000.0
        except (TypeError, ValueError):
            return 10 / 10000.0

    @staticmethod
    def _f2(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _today():
        return datetime.utcnow().date()

    @classmethod
    def _biz_days_elapsed(cls, start_iso):
        try:
            start = date.fromisoformat(str(start_iso)[:10])
        except (ValueError, TypeError):
            return 0
        today = cls._today()
        if today <= start:
            return 0
        n, d = 0, start
        while d < today:
            d = d + timedelta(days=1)
            if d.weekday() < 5:
                n += 1
        return n

    # ---- signal (reuse the carry sleeve's term-structure read) ---------------------------------
    def _signal(self):
        """The VIX/VIX3M term-structure signal, from the carry sleeve so both legs read one regime.
        Long-vol is favorable when NOT contango (backwardation). Fails soft to ok=False."""
        try:
            from app.services.vol_term_structure_carry_engine import VolTermStructureCarryEngine
            from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
            return VolTermStructureCarryEngine().signal(TradeStationQuoteLiveEngine()) or {"ok": False}
        except Exception as e:
            return {"ok": False, "reason": repr(e)[:80]}

    def _live_price(self, sym):
        try:
            from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
            q = TradeStationQuoteLiveEngine().get_quote(sym) or {}
            row = (((q.get("response_json") or {}).get("Quotes") or [{}]) or [{}])[0]
            return self._f2(row.get("Last")) or self._f2(row.get("Close"))
        except Exception:
            return None

    # ---- state ---------------------------------------------------------------------------------
    def _load_open(self):
        try:
            return json.loads(self.OPEN.read_text())
        except Exception:
            return []

    def _save_open(self, cohorts):
        try:
            self.STATE.mkdir(parents=True, exist_ok=True)
            self.OPEN.write_text(json.dumps(cohorts))
        except Exception:
            pass

    def _append_closed(self, rec):
        self.STATE.mkdir(parents=True, exist_ok=True)
        with open(self.CLOSED, "a") as f:
            f.write(json.dumps(rec) + "\n")

    def _closed(self):
        out = []
        try:
            for ln in self.CLOSED.read_text().splitlines():
                if ln.strip():
                    out.append(json.loads(ln))
        except Exception:
            pass
        return out

    # ---- mark ----------------------------------------------------------------------------------
    def mark(self):
        """Settle a matured cohort at live quotes, then open a NON-OVERLAPPING long-VXX cohort ONLY when the
        term structure is in backwardation (long-vol favorable). NO orders, NO budget."""
        if not self.enabled():
            return {"status": "VOL_ETP_SHADOW_DISABLED", "acted": False}
        cost = self._cost_roundtrip()
        cohorts = self._load_open()
        closed_now, still_open = [], []

        for co in cohorts:
            if self._biz_days_elapsed(co.get("opened")) < self.HOLD_DAYS:
                still_open.append(co)
                continue
            px = self._live_price(co["symbol"])
            ec = self._f2(co.get("entry_close"))
            if not (px and ec and ec > 0):
                still_open.append(co)                     # quote gap — settle when it returns, never partial
                continue
            gross = px / ec - 1.0                          # long-vol
            rec = {"opened": co.get("opened"), "settled_at": datetime.utcnow().isoformat(),
                   "symbol": co["symbol"], "entry_close": round(ec, 4), "exit_close": round(px, 4),
                   "cost_roundtrip_bps": round(cost * 10000, 2),
                   "gross_return": round(gross, 6), "net_return": round(gross - cost, 6),
                   "entry_ratio": co.get("entry_ratio")}
            self._append_closed(rec)
            closed_now.append(rec)

        opened, skip = None, None
        sig = self._signal()
        if not still_open:
            if not sig.get("ok"):
                skip = "no term-structure quote (VIX/VIX3M) — not opening"
            elif sig.get("contango"):
                skip = (f"CONTANGO (VIX/VIX3M {sig.get('ratio')}) — long-vol UNFAVORABLE, standing flat "
                        "(this is the SVXY carry sleeve's regime, not the long leg's)")
            else:
                px = self._live_price(self.INSTRUMENT)
                if px:
                    opened = {"opened": self._today().isoformat(), "opened_at": datetime.utcnow().isoformat(),
                              "symbol": self.INSTRUMENT, "side": "BUY", "entry_close": round(px, 4),
                              "entry_ratio": sig.get("ratio"), "regime": sig.get("state")}
                    still_open.append(opened)

        self._save_open(still_open)
        out = {"status": "VOL_ETP_SHADOW_MARKED", "acted": bool(closed_now or opened),
               "cohorts_closed": len(closed_now), "cohort_opened": bool(opened),
               "open_cohorts": len(still_open), "regime": sig.get("state")}
        if skip:
            out["open_skipped"] = skip
        return out

    # ---- positions + report --------------------------------------------------------------------
    def open_positions(self):
        rows = []
        for co in self._load_open():
            ec = self._f2(co.get("entry_close")) or 0.0
            cur = self._live_price(co["symbol"])
            pct = round(100 * (cur / ec - 1.0), 2) if (cur and ec > 0) else None
            held = self._biz_days_elapsed(co.get("opened"))
            rows.append({"symbol": co["symbol"], "side": "BUY", "entry_date": co.get("opened"),
                         "entry_close": round(ec, 4) if ec else None,
                         "live_last": round(cur, 4) if cur else None, "unrealized_pct": pct,
                         "live_dir": (None if pct is None else ("up" if pct > 0 else ("down" if pct < 0 else "flat"))),
                         "entry_regime": co.get("regime"), "days_held": held,
                         "days_to_settle": max(0, self.HOLD_DAYS - held)})
        return rows

    @staticmethod
    def _stdev(xs):
        n = len(xs)
        if n < 2:
            return 0.0
        m = sum(xs) / n
        return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))

    def report(self):
        closed = self._closed()
        rets = [c["net_return"] for c in closed if c.get("net_return") is not None]
        n = len(rets)
        sig = self._signal()
        base = {"timestamp": datetime.utcnow().isoformat(), "shadow_enabled": self.enabled(),
                "engine": "VolEtpShadowEngine", "instrument": self.INSTRUMENT,
                "cohorts_closed": n, "min_cohorts": self.MIN_COHORTS,
                "rigorous_verdict": _rigorous_verdict(rets, self.MIN_COHORTS),
                "open_cohorts": len(self._load_open()), "open_positions": self.open_positions(),
                "current_regime": (sig.get("state") if sig.get("ok") else "UNKNOWN"),
                "term_structure_ratio": sig.get("ratio"),
                "signal": "long VXX ONLY in backwardation (VIX>=VIX3M); flat in contango",
                "hold_days": self.HOLD_DAYS, "cost_roundtrip_bps": round(self._cost_roundtrip() * 10000, 2),
                "note": ("ZERO-capital forward-test of the regime-conditioned LONG-vol leg (complements the "
                         "SVXY short-vol carry sleeve). Opens ONLY in backwardation — rare, so cohorts accrue "
                         "slowly in stress clusters. NO orders/budget.")}
        if n == 0:
            waiting = (sig.get("ok") and sig.get("contango"))
            return {**base, "status": "VOL_ETP_SHADOW_NO_DATA",
                    "verdict": (f"{len(base['open_positions'])} open — settles in ~{self.HOLD_DAYS} biz days"
                                if base["open_positions"] else
                                ("in CONTANGO — long-vol leg stands flat until backwardation (a stress signal)"
                                 if waiting else
                                 "no cohorts yet — opens on the first backwardation week"))}
        eq = 1.0
        for r in rets:
            eq *= (1 + r)
        sd = self._stdev(rets)
        mean = sum(rets) / n
        sharpe = round(mean / sd * math.sqrt(self.PERIODS_PER_YEAR), 2) if sd else 0.0
        wins = sum(1 for r in rets if r > 0)
        accumulating = n < self.MIN_COHORTS
        return {**base,
                "status": "VOL_ETP_SHADOW_ACCUMULATING" if accumulating else "VOL_ETP_SHADOW_MEASURING",
                "cumulative_return_pct": round(100 * (eq - 1), 2),
                "avg_net_return_per_week_bps": round(mean * 10000, 2),
                "annualized_sharpe": sharpe, "win_rate_pct": round(100 * wins / n, 1),
                "verdict": (f"accumulating ({n}/{self.MIN_COHORTS} backwardation cohorts) — not enough yet"
                            if accumulating else
                            f"measuring: long-vol-in-backwardation net Sharpe {sharpe}, win rate "
                            f"{round(100 * wins / n, 1)}% over {n} cohorts")}
