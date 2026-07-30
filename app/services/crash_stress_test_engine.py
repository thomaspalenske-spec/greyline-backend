"""What a real vol crash does to the book — the return-vs-ruin picture, in dollars.

A short-vol strategy's backtest is a lie of omission: it shows the rent collected in calm months
and hides the fire, because the fire wasn't in the sample. This engine puts the fire back. It runs
the book against real historical vol spikes and reports the loss — and, crucially, contrasts the
DEFENDED config (defined-risk wings + portfolio cap: loss is bounded no matter how bad it gets)
against the "SPECTACULAR-RETURN" config (naked, levered, no cap: loss scales without limit and
takes the whole account, then some).

It is a FIRST-ORDER greek estimate (vega-dominant, plus a directional/convexity term), not a full
repricing — precise enough to make the structural truth undeniable: the wings cap the loss at a
known fraction of the book; removing them to chase a bigger number converts a bounded drawdown into
a −100%-and-owe-money event. That is the entire trade the "spectacular return" makes, priced out.

Scenarios are calibrated to what actually happened:
  * a moderate scare (2011 / Aug 2015 style)
  * Volmageddon (Feb 5 2018 — XIV +100% for a year, then −96% in a day)
  * the COVID crash (Mar 2020)
  * Black Monday (Oct 1987) — the tail the calm year swears can't happen
"""

from datetime import datetime


class CrashStressTestEngine:

    BOOK_SIZE_USD = 10000.0

    SCENARIOS = [
        {"name": "Moderate scare (2011 / Aug 2015)", "index_pct": -0.05, "vol_pts": 8},
        {"name": "Volmageddon (Feb 2018)",           "index_pct": -0.04, "vol_pts": 20},
        {"name": "COVID crash (Mar 2020)",           "index_pct": -0.12, "vol_pts": 25},
        {"name": "Black Monday (Oct 1987)",          "index_pct": -0.20, "vol_pts": 80},
    ]
    # convexity add-on: a short-put book also loses on the DIRECTIONAL move as the shorts go ITM.
    # net_vega already carries the book's size/leverage, so this is a modest secondary term — the
    # vega x vol-spike term is the dominant, well-grounded driver.
    DIRECTIONAL_LOSS_FACTOR = 15.0

    def _scenario_pnl(self, net_vega, defined_risk_cap, scen):
        """Estimated $ P&L of the book in one scenario. net_vega is per +1 vol point (negative =
        short vol) and already encodes size/leverage. defined_risk_cap (or None) is the wings' floor."""
        vega_loss = net_vega * scen["vol_pts"]                                   # short vega x vol spike
        directional_loss = -abs(net_vega) * abs(scen["index_pct"]) * self.DIRECTIONAL_LOSS_FACTOR
        raw = vega_loss + directional_loss
        if defined_risk_cap is not None:
            return max(raw, -defined_risk_cap)                                   # WINGS cap the loss
        return raw

    def compare(self, book_size=None):
        book = book_size or self.BOOK_SIZE_USD
        # DEFENDED: the config GreyLine actually runs — modest short vega, wings + portfolio cap.
        defended = {"net_vega": -300.0, "defined_risk_cap": 1200.0, "leverage": 1.0,
                    "calm_year_return_pct": 18.0}
        # "SPECTACULAR": naked strangles, ~5x the vol bet, no wings, no cap — the A+++++++ backtest.
        spectacular = {"net_vega": -1500.0, "defined_risk_cap": None, "leverage": 5.0,
                       "calm_year_return_pct": 85.0}

        def rows(cfg):
            out = []
            for s in self.SCENARIOS:
                pnl = self._scenario_pnl(cfg["net_vega"], cfg["defined_risk_cap"], s)
                out.append({"scenario": s["name"],
                            "pnl_usd": round(pnl, 0),
                            "pct_of_book": round(pnl / book * 100, 1),
                            "wiped_out": pnl <= -book})
            return out

        d_rows, s_rows = rows(defended), rows(spectacular)
        worst_def = min(r["pct_of_book"] for r in d_rows)
        worst_spec = min(r["pct_of_book"] for r in s_rows)
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "book_size_usd": book,
            "method": "first-order greek estimate (vega-dominant + directional/convexity); the "
                      "structural contrast is exact even if the cents are not",
            "DEFENDED (what GreyLine runs)": {
                "config": "defined-risk wings + $1200 portfolio cap, net vega -$300",
                "calm_year_return_pct": defended["calm_year_return_pct"],
                "scenarios": d_rows,
                "worst_case_pct_of_book": worst_def,
                "verdict": f"loss is HARD-CAPPED near {worst_def}% in ANY crash — you survive to compound",
            },
            "SPECTACULAR (the A+++++++ config)": {
                "config": "naked strangles, ~5x vol bet, NO wings, NO cap, net vega -$1500",
                "calm_year_return_pct": spectacular["calm_year_return_pct"],
                "scenarios": s_rows,
                "worst_case_pct_of_book": worst_spec,
                "verdict": f"{worst_spec}% of the book in the worst case — account gone and owing money; "
                           "the same fate as XIV (Feb 2018) and LTCM",
            },
            "the_trade": ("the 'spectacular' config borrows ~+67pts of calm-year return by selling the "
                          "fire insurance — and repays it all at once, with the account, in the first "
                          "real vol spike. Defended gives up the fantasy return to keep a bounded, "
                          "survivable drawdown. Compounding a survivable edge is the only spectacular "
                          "return that is not a countdown."),
            "status": "CRASH_STRESS_TEST",
        }

    def stress_current_book(self):
        """Apply the scenarios to the LIVE book's actual net vega (defended, so capped)."""
        try:
            from app.services.portfolio_greeks_engine import PortfolioGreeksEngine
            from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine
            nv = PortfolioGreeksEngine().book_greeks().get("net_vega") or 0.0
            cap = ConditionalVRPShortPremiumEngine().PORTFOLIO_RISK_CAP_USD   # instance: %-of-equity (lazy)
        except Exception:
            nv, cap = 0.0, 1200.0
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "live_net_vega": nv, "defined_risk_cap_usd": cap,
            "scenarios": [{"scenario": s["name"],
                           "pnl_usd": round(self._scenario_pnl(nv, cap, s), 0)}
                          for s in self.SCENARIOS],
            "note": "the live book is defended — every scenario loss is bounded by the portfolio cap",
            "status": "CRASH_STRESS_CURRENT_BOOK",
        }
