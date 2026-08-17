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

import hashlib
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
    RISK_TRIM_MARKER = Path("app/data/state/.sleeve_risk_trim_last")

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

        token = self._plan_token(new_overrides, moves, rec.get("basis"))
        return {"moves": moves, "skipped": skipped, "new_overrides": new_overrides,
                "resulting_total_pct": round(sum(
                    new_overrides.get(s, SleeveCapitalBudgetEngine.pct(s))
                    for s in SleeveCapitalBudgetEngine.DEFAULT_PCT), 2),
                "book_clamped_to_100": clamped, "allocator_basis": rec.get("basis"),
                "plan_token": token, "enabled": self.enabled()}

    @staticmethod
    def _plan_token(new_overrides, moves, allocator_basis):
        """A stable fingerprint of THE MATERIAL DECISION (which sleeves move to which %, and on what
        allocator basis) — deterministic, no timestamps. An operator approval carries this token; apply()
        refuses if the live plan's token no longer matches, so evidence that shifted between review and
        click can't cause a DIFFERENT allocation to be applied than the one the operator saw."""
        material = {
            "new_overrides": {str(k): round(float(v), 2) for k, v in sorted(new_overrides.items())},
            "moves": sorted((str(m["sleeve"]), round(float(m["to_pct"]), 2)) for m in moves),
            "allocator_basis": str(allocator_basis or ""),
        }
        blob = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:12]

    def apply(self, force=False, plan_token=None):
        """Write the stepped override file (evidence-driven only). GATED: no-op unless enabled, or force
        (deliberate operator apply), or a matching plan_token (operator APPROVED this exact plan). Dedupes
        an identical override map. Never places an order. Reversible via revert().

        plan_token binds the approval to what was reviewed: if it doesn't match the live plan (evidence
        shifted between review and click), apply REFUSES rather than silently applying a different
        allocation — the discipline a capital-moving action needs."""
        p = self.plan()
        approved = False
        if plan_token is not None:
            if plan_token != p["plan_token"]:
                return {"status": "AUTOAPPLY_PLAN_CHANGED", "applied": False,
                        "reason": ("the plan changed since you reviewed it — re-review "
                                   "/sleeve-budget-autoapply and re-approve the current plan"),
                        "reviewed_token": plan_token, "current_token": p["plan_token"], "plan": p}
            approved = True                        # a matching token IS the operator's approval of this plan
        if not (self.enabled() or force or approved):
            return {"status": "AUTOAPPLY_DISABLED", "applied": False,
                    "note": "GREYLINE_ALLOC_AUTOAPPLY_ENABLED is not true (pass a matching plan_token to approve)"}
        if not p["moves"]:
            return {"status": "AUTOAPPLY_NO_MOVES", "applied": False, "plan": p}
        existing = self._existing_overrides()
        if existing == {k: v for k, v in p["new_overrides"].items()}:
            return {"status": "AUTOAPPLY_UNCHANGED", "applied": False, "plan": p}
        source = ("operator_approved" if approved
                  else "operator_forced" if (force and not self.enabled()) else "auto_apply")
        payload = {"applied_at": datetime.utcnow().isoformat(), "source": source,
                   "plan_token": p["plan_token"], "pct": p["new_overrides"], "moves": p["moves"]}
        try:
            self.OVERRIDE_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.OVERRIDE_FILE.write_text(json.dumps(payload, indent=2))
            with open(self.HISTORY, "a") as f:
                f.write(json.dumps(payload) + "\n")
        except Exception as e:
            return {"status": "AUTOAPPLY_WRITE_FAILED", "applied": False, "error": str(e)[:120], "plan": p}
        return {"status": "AUTOAPPLY_APPLIED", "applied": True, "source": source,
                "plan_token": p["plan_token"], "moves": p["moves"],
                "new_overrides": p["new_overrides"], "resulting_total_pct": p["resulting_total_pct"]}

    # ---- RISK-PARITY de-concentration (operationalizes the risk-budget sizing backtest) ----------------
    # Down-only glide that pulls an over-concentrated sleeve (e.g. vol_carry: 20% of capital, 51% of book
    # RISK) toward its FLOORED risk-parity share. Gated by GREYLINE_SLEEVE_RISK_BUDGET; pct() honors the
    # written risk_trim only under that flag, and never above the pin (pin = ceiling). Fully reversible.

    def _existing_risk_trim(self):
        try:
            d = json.loads(self.OVERRIDE_FILE.read_text())
            return {str(k): float(v) for k, v in (d.get("risk_trim") or {}).items()}
        except Exception:
            return {}

    def risk_trim_plan(self):
        """The next stepped, DOWN-ONLY move toward each armed sleeve's FLOORED risk-parity target. READ-ONLY.
        Active only when GREYLINE_SLEEVE_RISK_BUDGET is on. Caps the step per apply (MAX_STEP_PCT); floors a
        crisis diversifier so it isn't zeroed; glides over days (steps from the current trimmed level, not
        the pin) and stops once at target."""
        on = SleeveCapitalBudgetEngine._risk_budget_on()
        sleeves = (SleeveCapitalBudgetEngine.risk_budget_advisory() or {}).get("sleeves") or {}
        existing = self._existing_risk_trim()
        moves, at_target = [], []
        for s, row in sleeves.items():
            rp = self._f(row.get("risk_parity_pct"))
            target = round(max(rp, SleeveCapitalBudgetEngine._risk_floor(s)), 2)
            base = SleeveCapitalBudgetEngine._static_pct(s)        # pin/override/default = the ceiling
            cur = existing.get(s, base)
            drop = cur - target
            if drop <= self.MIN_MOVE_PCT:                         # only de-risk a meaningful over-concentration
                if s in existing:
                    at_target.append({"sleeve": s, "pct": round(cur, 2), "target_pct": target})
                continue
            step = min(self.MAX_STEP_PCT, drop)
            moves.append({"sleeve": s, "from_pct": round(cur, 2), "to_pct": round(cur - step, 2),
                          "target_pct": target, "step_pct": round(-step, 2), "ceiling_pct": round(base, 2)})
        new_trim = dict(existing)
        for m in moves:
            new_trim[m["sleeve"]] = m["to_pct"]
        return {"active": on, "moves": moves, "at_target": at_target, "new_risk_trim": new_trim,
                "max_step_pct": self.MAX_STEP_PCT,
                "note": ("Down-only glide to floored risk-parity; pct() honors it only when "
                         "GREYLINE_SLEEVE_RISK_BUDGET=true, never above the pin. Reversible via revert().")}

    def apply_risk_trim(self, force=False):
        """Write the next stepped risk-trim into the override file, PRESERVING the allocator 'pct' overrides.
        GATED by GREYLINE_SLEEVE_RISK_BUDGET (or force). Never places an order. Reversible via revert()."""
        if not (SleeveCapitalBudgetEngine._risk_budget_on() or force):
            return {"status": "RISK_TRIM_DISABLED", "applied": False,
                    "note": "GREYLINE_SLEEVE_RISK_BUDGET is not true (pass force=true to preview-apply)"}
        p = self.risk_trim_plan()
        if not p["moves"]:
            return {"status": "RISK_TRIM_NO_MOVES", "applied": False, "plan": p}
        try:
            d = json.loads(self.OVERRIDE_FILE.read_text()) if self.OVERRIDE_FILE.exists() else {}
        except Exception:
            d = {}
        d["risk_trim"] = p["new_risk_trim"]
        d.setdefault("pct", d.get("pct") or {})               # keep any allocator overrides intact
        d["risk_trim_applied_at"] = datetime.utcnow().isoformat()
        try:
            self.OVERRIDE_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.OVERRIDE_FILE.write_text(json.dumps(d, indent=2))
            with open(self.HISTORY, "a") as f:
                f.write(json.dumps({"applied_at": d["risk_trim_applied_at"], "source": "risk_trim",
                                    "risk_trim": p["new_risk_trim"], "moves": p["moves"]}) + "\n")
        except Exception as e:
            return {"status": "RISK_TRIM_WRITE_FAILED", "applied": False, "error": str(e)[:120], "plan": p}
        return {"status": "RISK_TRIM_APPLIED", "applied": True, "moves": p["moves"],
                "new_risk_trim": p["new_risk_trim"]}

    def run_risk_trim_if_due(self, market_open):
        """Scheduler hook: advance the risk-trim glide at most ONCE per trading day, market CLOSED only.
        Gated by GREYLINE_SLEEVE_RISK_BUDGET. Best-effort."""
        if not SleeveCapitalBudgetEngine._risk_budget_on():
            return {"status": "RISK_TRIM_DISABLED", "ran": False}
        if market_open:
            return {"status": "RISK_TRIM_DEFERRED_MARKET_OPEN", "ran": False}
        today = self._today()
        try:
            if today and self.RISK_TRIM_MARKER.read_text().strip() == today:
                return {"status": "RISK_TRIM_ALREADY_RAN_TODAY", "ran": False, "date": today}
        except Exception:
            pass
        res = self.apply_risk_trim()
        try:
            self.RISK_TRIM_MARKER.parent.mkdir(parents=True, exist_ok=True)
            self.RISK_TRIM_MARKER.write_text(today or "")
        except Exception:
            pass
        res["ran"] = True
        return res

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
                "active_risk_trim": self._existing_risk_trim(),
                "plan_preview": self.plan(),
                "risk_trim_plan": self.risk_trim_plan(),
                "risk_budget_mode": SleeveCapitalBudgetEngine._risk_budget_on(),
                "note": ("GATED OFF by default. Steps the sleeve %-of-equity budgets toward the measured "
                         "allocation, evidence-only, capped per apply, reversible (revert clears the "
                         "override file). An explicit GREYLINE_<SLEEVE>_ALLOC_PCT env pin always wins — except "
                         "a DOWN-only risk-trim (GREYLINE_SLEEVE_RISK_BUDGET) may de-risk a pinned "
                         "concentration hog toward floored risk-parity.")}
