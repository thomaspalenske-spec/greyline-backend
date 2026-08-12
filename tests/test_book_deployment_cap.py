"""Hard book-level deployment cap — the backstop that makes the 2026-08-06 12x over-deployment
($122k of positions on a $10k mission book) impossible. An equity BUY is blocked before it reaches the
broker if the book's committed long-equity value (filled + resting buys) + the order would exceed
MAX_DEPLOY_FRAC x the mission base. Sells/options never gated; fail CLOSED on a degraded read. No network."""

from app.services.book_deployment_cap_engine import BookDeploymentCapEngine as CAP


class _Book:
    def __init__(self, positions, orders=None, pos_ok=True, ord_ok=True):
        self._p, self._o, self._pok, self._ook = positions, orders or [], pos_ok, ord_ok

    def positions(self):
        return {"ok": self._pok, "response_json": {"Positions": self._p}}

    def orders(self):
        return {"ok": self._ook, "response_json": {"Orders": self._o}}


def _pos(sym, qty, last, asset="STOCK"):
    return {"Symbol": sym, "Quantity": str(qty), "Last": str(last), "AssetType": asset}


def _working_buy(sym, qty, limit):
    return {"StatusDescription": "Received", "LimitPrice": str(limit),
            "Legs": [{"Symbol": sym, "BuyOrSell": "Buy", "QuantityRemaining": str(qty)}]}


def _env(monkeypatch, base="10000", frac=None, enabled="true"):
    monkeypatch.setenv("GREYLINE_ACCOUNT_CAPITAL_BASE", base)
    monkeypatch.setenv("GREYLINE_BOOK_DEPLOY_CAP", enabled)
    if frac is not None:
        monkeypatch.setenv("GREYLINE_BOOK_DEPLOY_CAP_FRAC", frac)


def test_cap_usd_is_frac_of_mission_base(monkeypatch):
    _env(monkeypatch)                                       # 10000 x 1.15 default
    assert abs(CAP.cap_usd() - 11500.0) < 1e-6


def test_the_disaster_is_blocked(monkeypatch):
    # 1,406 DBC @ $28.70 = $40,352 already held -> ANY further buy is blocked
    _env(monkeypatch)
    book = _Book([_pos("DBC", 1406, 28.70)])
    chk = CAP.check_equity_buy("DBC", 100, 28.70, book)
    assert chk["allowed"] is False and "book deployment cap" in chk["reason"]
    assert chk["deployed_usd"] > 40000


def test_buy_within_cap_allowed(monkeypatch):
    _env(monkeypatch)
    book = _Book([_pos("USMV", 30, 100.0)])                 # $3,000 held
    chk = CAP.check_equity_buy("SPLV", 20, 100.0, book)     # + $2,000 = $5,000 < $11,500
    assert chk["allowed"] is True


def test_buy_that_would_exceed_cap_blocked(monkeypatch):
    _env(monkeypatch)
    book = _Book([_pos("USMV", 100, 100.0)])                # $10,000 held
    chk = CAP.check_equity_buy("SPLV", 30, 100.0, book)     # + $3,000 = $13,000 > $11,500
    assert chk["allowed"] is False


def test_resting_buys_count_toward_deployment(monkeypatch):
    # filled $5,000 + a resting BUY worth $5,000 = $10,000 committed; a new $2,000 buy -> $12,000 > cap.
    # Without counting resting buys this would wrongly pass (the within-cycle stacking gap).
    _env(monkeypatch)
    book = _Book([_pos("USMV", 50, 100.0)], orders=[_working_buy("SPLV", 50, 100.0)])
    chk = CAP.check_equity_buy("EFAV", 20, 100.0, book)
    assert chk["deployed_usd"] == 10000.0 and chk["allowed"] is False


def test_degraded_positions_read_fails_closed(monkeypatch):
    _env(monkeypatch)
    book = _Book([_pos("USMV", 30, 100.0)], pos_ok=False)
    chk = CAP.check_equity_buy("SPLV", 1, 100.0, book)
    assert chk["allowed"] is False and "fail-closed" in chk["reason"]


def test_degraded_orders_read_fails_closed(monkeypatch):
    _env(monkeypatch)
    book = _Book([_pos("USMV", 30, 100.0)], ord_ok=False)
    chk = CAP.check_equity_buy("SPLV", 1, 100.0, book)
    assert chk["allowed"] is False


def test_buy_with_no_price_is_blocked(monkeypatch):
    _env(monkeypatch)
    book = _Book([_pos("USMV", 1, 100.0)])
    chk = CAP.check_equity_buy("SPLV", 10, None, book)
    assert chk["allowed"] is False and "no usable price" in chk["reason"]


def test_disabled_flag_allows_everything(monkeypatch):
    _env(monkeypatch, enabled="false")
    book = _Book([_pos("DBC", 1406, 28.70)])
    assert CAP.check_equity_buy("DBC", 100, 28.70, book)["allowed"] is True


def test_place_order_gates_only_equity_buys(monkeypatch):
    """Replicates the branch in place_order that decides WHETHER to run the cap: only a non-stop equity
    BUY/BUYTOOPEN is gated. A SELL, an option (symbol has a space), and a stop order are never gated —
    so the book can always unwind and defined-risk option premium isn't blocked."""
    def gated(symbol, action, order_type="Limit"):
        a = str(action or "").upper()
        is_equity = " " not in str(symbol or "")
        return is_equity and a in ("BUY", "BUYTOOPEN") and str(order_type or "").lower() != "stopmarket"
    assert gated("DBC", "BUY") is True
    assert gated("DBC", "SELL") is False                    # unwind never blocked
    assert gated("NRG 260807C152.5", "BUYTOOPEN") is False  # option premium never blocked
    assert gated("DBC", "BUY", order_type="StopMarket") is False  # protective stop never blocked


# --- SGOV cash-sweep is NOT risk deployment: net it out of the cap (2026-08-11) ---

def _sgov(monkeypatch):
    monkeypatch.setattr(CAP, "_tbill_symbol", staticmethod(lambda: "SGOV"))


def test_sgov_held_excluded_from_committed(monkeypatch):
    _env(monkeypatch); _sgov(monkeypatch)
    book = _Book([_pos("SGOV", 30, 100.0), _pos("USMV", 30, 100.0)])   # $3k SGOV + $3k USMV
    dep, ok = CAP.committed_long_equity_usd(book)
    assert ok and abs(dep - 3000.0) < 1e-6                              # only the at-risk USMV counts


def test_sgov_resting_buy_excluded_from_committed(monkeypatch):
    _env(monkeypatch); _sgov(monkeypatch)
    book = _Book([_pos("USMV", 30, 100.0)], orders=[_working_buy("SGOV", 50, 100.0)])
    dep, ok = CAP.committed_long_equity_usd(book)
    assert ok and abs(dep - 3000.0) < 1e-6                              # SGOV resting buy not counted


def test_sgov_buy_is_exempt_even_near_cap(monkeypatch):
    _env(monkeypatch); _sgov(monkeypatch)
    book = _Book([_pos("USMV", 110, 100.0)])                            # $11k risk, near the $11.5k cap
    chk = CAP.check_equity_buy("SGOV", 20, 100.0, book)                 # a cash-park buy
    assert chk["allowed"] is True and "cash sweep" in chk["reason"]


def test_risk_buy_still_gated_and_sgov_not_in_committed(monkeypatch):
    _env(monkeypatch); _sgov(monkeypatch)
    # $3k SGOV (excluded) + $9k USMV risk; a +$3k risk buy would breach $11.5k -> still blocked
    book = _Book([_pos("SGOV", 30, 100.0), _pos("USMV", 90, 100.0)])
    chk = CAP.check_equity_buy("SPLV", 30, 100.0, book)
    assert chk["allowed"] is False and chk["deployed_usd"] == 9000.0    # SGOV out of the reported committed
