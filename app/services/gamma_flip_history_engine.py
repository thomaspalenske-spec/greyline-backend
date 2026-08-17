"""Daily gamma_flip-vs-spot recorder for the index-condor factor proxies.

WHY: UW serves `gamma_flip` only as a LIVE snapshot (no history), so GATE 2 of the index-condor sleeves
(spot > gamma_flip ⇒ dealers long gamma ⇒ condor-friendly) can't be TRENDED — we can see a name is below
its flip today, but not whether that gap is CONVERGING (regime warming) or DIVERGING. This stamps flip/spot
each cycle (one row per symbol per UTC day, last wins) so the gap accrues a forward history. It records
EXACTLY what the gate sees by reusing IndexCondorPlanEngine._gex_map (same UW gex-levels call, 900s-cached),
and never fabricates a regime from a missing read. Read-only; places no orders.
"""

import json
from datetime import datetime
from pathlib import Path


class GammaFlipHistoryEngine:

    DIR = Path("app/data/gex_strategy")
    LEDGER = DIR / "gamma_flip_history.jsonl"

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _read(self):
        try:
            return [json.loads(l) for l in self.LEDGER.read_text().splitlines() if l.strip()]
        except Exception:
            return []

    def record(self):
        """Stamp today's flip/spot for every condor proxy with a usable UW read (one row/symbol/UTC day)."""
        try:
            from app.services.index_condor_plan_engine import IndexCondorPlanEngine
            gex = IndexCondorPlanEngine()._gex_map()      # {proxy: {gamma_flip, spot, long_gamma}}
        except Exception as e:
            return {"status": "GAMMA_FLIP_RECORD_DEGRADED", "error": repr(e)[:100]}
        today = datetime.utcnow().date().isoformat()
        rows = [r for r in self._read() if r.get("date") != today]
        recorded = {}
        for sym, g in (gex or {}).items():
            flip, spot = self._f(g.get("gamma_flip")), self._f(g.get("spot"))
            if not (flip and spot and spot > 0):
                continue                                  # missing read -> skip, never fabricate a regime
            gap_pct = round((flip - spot) / spot * 100, 2)
            rows.append({"date": today, "symbol": sym, "spot": round(spot, 2), "gamma_flip": round(flip, 2),
                         "gap_pct": gap_pct, "long_gamma": bool(g.get("long_gamma")),
                         "ts": datetime.utcnow().isoformat()})
            recorded[sym] = gap_pct
        try:
            self.DIR.mkdir(parents=True, exist_ok=True)
            with open(self.LEDGER, "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
        except Exception as e:
            return {"status": "GAMMA_FLIP_WRITE_FAILED", "error": repr(e)[:100]}
        return {"status": "GAMMA_FLIP_RECORDED", "date": today, "gap_pct": recorded}

    def trend(self, symbol=None, days=20):
        """Per-symbol gap history + a direction read: gap_pct = (gamma_flip - spot)/spot. Gap > 0 = below flip
        (short-gamma, condor-hostile); shrinking toward 0 = regime WARMING; gap <= 0 = long-gamma (GATE 2 opens)."""
        by = {}
        for r in self._read():
            by.setdefault(r.get("symbol"), []).append(r)
        out = {}
        for sym, rs in by.items():
            if symbol and sym != symbol:
                continue
            rs = sorted(rs, key=lambda x: x.get("date", ""))[-int(days):]
            if not rs:
                continue
            first, last = rs[0], rs[-1]
            fg, lg = self._f(first.get("gap_pct")), self._f(last.get("gap_pct"))
            direction = "ACCUMULATING (need ≥2 sessions)"
            if fg is not None and lg is not None and len(rs) >= 2:
                if lg <= 0:
                    direction = "CROSSED — long-gamma (GATE 2 open)"
                elif lg < fg - 0.25:
                    direction = "CONVERGING toward flip (regime warming)"
                elif lg > fg + 0.25:
                    direction = "DIVERGING (regime cooling)"
                else:
                    direction = "FLAT (no clear drift)"
            out[sym] = {"sessions": len(rs), "first_date": first.get("date"), "last_date": last.get("date"),
                        "first_gap_pct": fg, "last_gap_pct": lg,
                        "last_spot": self._f(last.get("spot")), "last_flip": self._f(last.get("gamma_flip")),
                        "long_gamma": bool(last.get("long_gamma")), "direction": direction,
                        "series": [{"date": r.get("date"), "gap_pct": r.get("gap_pct")} for r in rs]}
        return {"timestamp": datetime.utcnow().isoformat(), "days": days, "symbols": out,
                "note": ("gap_pct = (gamma_flip - spot)/spot. Below-flip (gap>0) = short-gamma (condor-hostile); "
                         "shrinking toward 0 = warming; gap<=0 = long-gamma (GATE 2 opens). UW serves flip "
                         "LIVE-only, so this trend accrues FORWARD from the first record."),
                "status": "GAMMA_FLIP_TREND"}
