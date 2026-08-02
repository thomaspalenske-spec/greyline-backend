"""Gated auto-apply of the evidence-based capital allocation.

CapitalAllocatorEngine.recommend() has always been RECOMMENDATION-ONLY — applying it meant a manual
after-hours edit of the sleeve %-of-equity knobs. This engine closes that loop SAFELY: it steps the live
sleeve budgets toward the allocator's recommendation, but only:

  * for EVIDENCE-driven sleeves (a measured court verdict or the pre-proven tilt) — never on a static
    prior, so it can't churn the book on narrative;
  * by a capped step per apply (MAX_STEP_PCT points of equity), so measured edge moves capital gradually,
    never in one lurch;
  * through the SleeveCapitalBudgetEngine OVERRIDE FILE (not .env) — so it's fully REVERSIBLE (revert()
    clears it) and can't trip the env-precedence trap; an explicit operator env pin still wins;
  * GATED OFF by default (GREYLINE_ALLOC_AUTOAPPLY_ENABLED). While off, plan() still shows exactly what it
    WOULD do.

It places no orders and holds no edge opinion of its own — it only moves the budget knobs the sizing
engines read, toward what the court already measured. Right now (all sleeves basis 'prior', tilt off) it
is a complete no-op.
"""

import json
from datetime import datetime
from os import getenv
from pathlib import Path

from app.services.capital_allocator_engine import CapitalAllocatorEngine
from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine


class SleeveBudgetAutoApplyEngine:

    MAX_STEP_PCT = 2.0          # a single apply moves a sleeve at most this many points of equity
    MIN_MOVE_PCT = 0.5          # ignore sub-this drift — not worth churning the knob
    # only these bases are evidence-driven; a static 'prior' is never auto-moved
    _EVIDENCE_BASES = ("measured_proven", "measured_decayed", "measured_unproven", "prior+tilt")
    # allocator sleeve name -> budget sleeve name (carry is vol_carry in the budget engine)
    _MAP = {"trend": "trend", "carry": "vol_carry", "vrp": "vrp", "earnings": "earnings",
            "momentum": "momentum"}

    OVERRIDE_FILE = SleeveCapitalBudgetEngine.OVERRIDE_FILE
    HISTORY = Path("app/data/state/sleeve_pct_autoapply_history.jsonl")
    MARKER = Path("app/data/state/.sleeve_autoapply_last")

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_ALLOC_AUTOAPPLY_ENABLED", "") or "").strip().lower() == "true"

    @staticmethod
    def _f(v, d=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return d

    def _existing_overrides(self):
        try:
            d = json.loads(self.OVERRIDE_FILE.read_text())
            return {str(k): float(v) for k, v in (d.get("pct") or {}).items()}
        except Exception:
            return {}

    def plan(self):
        """Compute the capped, evidence-only step toward the recommendation. READ-ONLY. Returns the moves
        and the resulting override map — what apply() would write. Never moves a static-prior sleeve; caps
        each move at MAX_STEP_PCT; clamps the resulting book to <= 100% of equity."""
        rec = CapitalAllocatorEngine().recommend()
        rec_sleeves = rec.get("sleeves") or {}
        existing = self._existing_overrides()
        moves, skipped = [], []
        for a, budget_name in self._MAP.items():
            row = rec_sleeves.get(a) or {}
            basis = str(row.get("basis") or "")
            current = SleeveCapitalBudgetEngine.pct(budget_name)          # honors env > override > default
            target = self._f(row.get("recommended_pct"), current)
            if basis not in self._EVIDENCE_BASES:                         # static prior -> never auto-move
                skipped.append({"sleeve": budget_name, "basis": basis, "reason": "not evidence-driven"})
                continue
            delta = target - current
            if abs(delta) < self.MIN_MOVE_PCT:
                skipped.append({"sleeve": budget_name, "basis": basis, "reason": "within MIN_MOVE deadband"})
                continue
            step = max(-self.MAX_STEP_PCT, min(self.MAX_STEP_PCT, delta))  # cap the per-apply move
            new_pct = round(max(0.0, min(100.0, current + step)), 2)
            moves.append({"sleeve": budget_name, "basis": basis, "from_pct": round(current, 2),
                          "to_pct": new_pct, "target_pct": round(target, 2), "step_pct": round(step, 2)})

        # resulting override map = prior overrides + this apply's moves
        new_overrides = dict(existing)
        for m in moves:
            new_overrides[m["sleeve"]] = m["to_pct"]

        # book-level clamp: the live sum of ALL sleeve pcts must stay <= 100. If the moves would breach it
        # (only possible on net increases), scale the positive steps down proportionally so the sum == 100.
        projected = {s: new_overrides.get(s, SleeveCapitalBudgetEngine.pct(s))
                     for s in SleeveCapitalBudgetEngine.DEFAULT_PCT}
        total = round(sum(projected.values()), 4)
        clamped = False
        if total > 100.0 + 1e-6:
            ups = [m for m in moves if m["step_pct"] > 0]
            excess = total - 100.0
            up_sum = sum(m["step_pct"] for m in ups) or 1.0
            for m in ups:
                trim = excess * (m["step_pct"] / up_sum)
                m["to_pct"] = round(max(0.0, m["from_pct"] + m["step_pct"] - trim), 2)
                m["step_pct"] = round(m["to_pct"] - m["from_pct"], 2)
                new_overrides[m["sleeve"]] = m["to_pct"]
            clamped = True

        return {"moves": moves, "skipped": skipped, "new_overrides": new_overrides,
                "resulting_total_pct": round(sum(
                    new_overrides.get(s, SleeveCapitalBudgetEngine.pct(s))
                    for s in SleeveCapitalBudgetEngine.DEFAULT_PCT), 2),
                "book_clamped_to_100": clamped, "allocator_basis": rec.get("basis"),
                "enabled": self.enabled()}

    def apply(self, force=False):
        """Write the stepped override file (evidence-driven only). GATED: no-op unless enabled (or force
        for an operator route). Dedupes an identical override map. Never places an order. Reversible via
        revert()."""
        if not (self.enabled() or force):
            return {"status": "AUTOAPPLY_DISABLED", "applied": False,
                    "note": "GREYLINE_ALLOC_AUTOAPPLY_ENABLED is not true"}
        p = self.plan()
        if not p["moves"]:
            return {"status": "AUTOAPPLY_NO_MOVES", "applied": False, "plan": p}
        existing = self._existing_overrides()
        if existing == {k: v for k, v in p["new_overrides"].items()}:
            return {"status": "AUTOAPPLY_UNCHANGED", "applied": False, "plan": p}
        payload = {"applied_at": datetime.utcnow().isoformat(), "source": "auto_apply",
                   "pct": p["new_overrides"], "moves": p["moves"]}
        try:
            self.OVERRIDE_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.OVERRIDE_FILE.write_text(json.dumps(payload, indent=2))
            with open(self.HISTORY, "a") as f:
                f.write(json.dumps(payload) + "\n")
        except Exception as e:
            return {"status": "AUTOAPPLY_WRITE_FAILED", "applied": False, "error": str(e)[:120], "plan": p}
        return {"status": "AUTOAPPLY_APPLIED", "applied": True, "moves": p["moves"],
                "new_overrides": p["new_overrides"], "resulting_total_pct": p["resulting_total_pct"]}

    def revert(self):
        """Full revert: remove the override file so every sleeve falls back to its env/default pct."""
        try:
            existed = self.OVERRIDE_FILE.exists()
            if existed:
                self.OVERRIDE_FILE.unlink()
            return {"status": "AUTOAPPLY_REVERTED" if existed else "AUTOAPPLY_NOTHING_TO_REVERT",
                    "reverted": existed}
        except Exception as e:
            return {"status": "AUTOAPPLY_REVERT_FAILED", "reverted": False, "error": str(e)[:120]}

    def _today(self):
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        except Exception:
            return None

    def run_if_due(self, market_open):
        """Scheduler hook: apply at most ONCE per trading day, and only while the market is CLOSED (never
        re-budget mid-session under live sizing). No-op unless enabled. Best-effort."""
        if not self.enabled():
            return {"status": "AUTOAPPLY_DISABLED", "ran": False}
        if market_open:
            return {"status": "AUTOAPPLY_DEFERRED_MARKET_OPEN", "ran": False}
        today = self._today()
        try:
            if today and self.MARKER.read_text().strip() == today:
                return {"status": "AUTOAPPLY_ALREADY_RAN_TODAY", "ran": False, "date": today}
        except Exception:
            pass
        res = self.apply()
        try:
            self.MARKER.parent.mkdir(parents=True, exist_ok=True)
            self.MARKER.write_text(today or "")
        except Exception:
            pass
        res["ran"] = True
        return res

    def status(self):
        return {"timestamp": datetime.utcnow().isoformat(), "enabled": self.enabled(),
                "max_step_pct": self.MAX_STEP_PCT, "min_move_pct": self.MIN_MOVE_PCT,
                "active_overrides": self._existing_overrides(),
                "plan_preview": self.plan(),
                "note": ("GATED OFF by default. Steps the sleeve %-of-equity budgets toward the measured "
                         "allocation, evidence-only, capped per apply, reversible (revert clears the "
                         "override file). An explicit GREYLINE_<SLEEVE>_ALLOC_PCT env pin always wins.")}
