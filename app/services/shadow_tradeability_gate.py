"""THE RULE (2026-08-17, operator): a zero-capital shadow / forward-test may only record an OPEN or a
SETTLE when that transaction could ACTUALLY have been executed on TradeStation at that moment — even
though NO capital is at risk. A hypothetical fill at a stale weekend/overnight quote is not a fill you
could ever have gotten, so recording it corrupts the measurement (and mislabels the entry "live"). Gate
every live-quote open and settle on the instrument's REAL trading session, and FAIL-CLOSED (do NOT
record) whenever the session can't be confirmed.

Class-aware, because the sessions differ:
  - EQUITY / ETF / equity-index option / iron condor -> the regular US equity/options session
    (Mon-Fri 09:30-16:00 ET). Outside it the quote API just echoes the last close.
  - FUTURES / FX -> trade nearly 24h; the real non-tradeable window is the weekend/holiday close, so
    gate on a normal trading weekday (conservative: also skips Sun-evening reopen, which is fine for a
    measurement — it simply records at the next weekday).

One definition, imported everywhere, so the rule can never drift between shadows.
"""


def _market_status():
    from app.services.market_hours_engine import MarketHoursEngine
    return MarketHoursEngine().status()


def equity_session_open():
    """True only during the regular US equity/options session. FAIL-CLOSED (False) on any error."""
    try:
        return bool(_market_status().get("is_regular_session"))
    except Exception:
        return False


def futures_fx_session_open():
    """True on a normal trading weekday (futures/FX trade ~24h; only the weekend/holiday close is a hard
    non-tradeable window). FAIL-CLOSED (False) on any error."""
    try:
        st = _market_status()
        return bool(st.get("is_weekday")) and not bool(st.get("is_holiday"))
    except Exception:
        return False


def transactable_now(asset_class="equity"):
    """The single rule, class-aware. asset_class in {equity,etf,option,condor,futures,future,fx,forex}."""
    ac = (asset_class or "equity").strip().lower()
    if ac in ("futures", "future", "fx", "forex"):
        return futures_fx_session_open()
    return equity_session_open()
