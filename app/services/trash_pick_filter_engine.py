"""Trash-pick failsafe — discard junk candidates and never execute on them.

The momentum signal periodically surfaces garbage: penny stocks and data artifacts with absurd
"momentum" (a 9,445% 12-month move is a split/reverse-split/pump, not a tradeable uptrend) or a
"pullback" that is really a -50% collapse. Those aren't opportunities; they're how a signal that
looks alive loses 41%. This is the single source of truth for what counts as trash — used by BOTH
the display (only show confirmed-clean picks) AND the execution path (never buy a trash pick, just
discard it).

A pick is TRASH if any of:
  * price below MIN_PRICE (penny stocks are illiquid and manipulable)
  * |12-1 momentum| above MAX_MOMENTUM_PCT (no genuine tradeable trend runs that far — it's an
    artifact/pump)
  * |5-day move| above MAX_REVERSAL_PCT (the signal wants a short pullback in an uptrend; a >30%
    move in a week is a crash/spike, not a dip)
Thresholds are env-tunable so the failsafe can be loosened/tightened without a code change.
"""

from os import getenv


class TrashPickFilterEngine:

    @staticmethod
    def _f(v, d):
        try:
            return float(v)
        except (TypeError, ValueError):
            return d

    @classmethod
    def _min_price(cls):
        return abs(cls._f(getenv("GREYLINE_TRASH_MIN_PRICE"), 10.0))

    @classmethod
    def _max_momentum(cls):
        return abs(cls._f(getenv("GREYLINE_TRASH_MAX_MOMENTUM_PCT"), 300.0))

    @classmethod
    def _max_reversal(cls):
        return abs(cls._f(getenv("GREYLINE_TRASH_MAX_REVERSAL_PCT"), 30.0))

    @classmethod
    def is_trash(cls, candidate):
        """(is_trash: bool, reason: str|None) for one candidate dict."""
        price = cls._f(candidate.get("last_close"), None) if candidate.get("last_close") is not None else None
        mom = candidate.get("momentum_12_1_pct")
        rev = candidate.get("reversal_5d_move_pct")
        if price is None or price <= 0:
            return True, "no/invalid price"
        if price < cls._min_price():
            return True, f"penny stock (${round(price, 2)} < ${cls._min_price():.0f} floor)"
        if mom is not None and abs(cls._f(mom, 0)) > cls._max_momentum():
            return True, f"absurd momentum ({cls._f(mom, 0):.0f}% > {cls._max_momentum():.0f}% — split/pump/artifact)"
        if rev is not None and abs(cls._f(rev, 0)) > cls._max_reversal():
            return True, f"not a pullback ({cls._f(rev, 0):.0f}% 5-day move > {cls._max_reversal():.0f}% — crash/spike)"
        return False, None

    @classmethod
    def partition(cls, candidates):
        """Split a candidate list into (clean, discarded-with-reason)."""
        clean, discarded = [], []
        for c in (candidates or []):
            trash, reason = cls.is_trash(c)
            if trash:
                discarded.append({**c, "discard_reason": reason})
            else:
                clean.append(c)
        return clean, discarded
