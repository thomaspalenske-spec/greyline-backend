class DirectionalSignalEngine:
    """
    The rebuilt directional core — evidence-based, validated before it was built.

    The old scorer blended short-term momentum *continuation* (buy what rose over
    5-20 days) into a 1,000-line composite. Backtested over 28 years / 90k independent
    samples, that signal was a coin flip (balanced accuracy 0.49, no score edge, no
    cross-sectional selection). It traded real factors with the wrong sign at the wrong
    horizon.

    This replaces it with the two most documented equity anomalies, at the horizons and
    signs the data actually supports, combined as a conviction filter:

      * 12-1 momentum   : return from ~12 months ago to ~1 month ago. BULLISH if > 0.
                          (Jegadeesh-Titman; test balanced accuracy 0.505, z 9.7)
      * 5-day reversal  : FADE the trailing 5-day move. Recent short-term moves revert.
                          (test balanced accuracy 0.510, z 2.3)

    Signal fires only when both AGREE. On that high-conviction subset, out-of-sample
    (post-2015, n~19k) balanced accuracy is 0.514 at z 8.6 — a small but real, robust
    5-day directional edge. When they conflict, there is no trade.

    HONEST SCOPE: this is validated for EQUITY direction at a 5-day horizon. The mean
    move is ~0.23%/5d — small. Whether that survives OPTIONS premium, theta and spread
    is NOT established and is doubtful for OTM options. The instrument (shares / delta-1 /
    horizon) is an open question the cost analysis must settle before this trades options.
    See research_signals.py for the full factor panel.
    """

    MOM_START = 253    # bars back for momentum window start (~12 months)
    MOM_END = 22       # bars back for momentum window end (~1 month, the skip)
    REV_LOOKBACK = 5   # trailing days for the reversal leg
    MIN_BARS = 253

    def evaluate(self, closes):
        closes = [c for c in (closes or []) if isinstance(c, (int, float)) and c > 0]
        if len(closes) < self.MIN_BARS:
            return {
                "engine": "DirectionalSignalEngine",
                "directional_bias": None,
                "conviction": "INSUFFICIENT_HISTORY",
                "bars": len(closes),
                "min_bars": self.MIN_BARS,
                "status": "DIRECTIONAL_SIGNAL_INSUFFICIENT_HISTORY",
            }

        mom = closes[-self.MOM_END] / closes[-self.MOM_START] - 1
        rev5 = closes[-1] / closes[-(self.REV_LOOKBACK + 1)] - 1

        mom_bias = "BULLISH" if mom > 0 else "BEARISH"
        rev_bias = "BEARISH" if rev5 > 0 else "BULLISH"   # fade the recent move

        agree = mom_bias == rev_bias
        return {
            "engine": "DirectionalSignalEngine",
            "directional_bias": mom_bias if agree else None,
            "conviction": "CONFIRMED" if agree else "CONFLICTED",
            "momentum_12_1_pct": round(mom * 100, 3),
            "momentum_bias": mom_bias,
            "reversal_5d_move_pct": round(rev5 * 100, 3),
            "reversal_bias": rev_bias,
            "tradeable": agree,
            "note": "Fires only when 12-1 momentum and 5-day reversal agree.",
            "status": "DIRECTIONAL_SIGNAL_READY",
        }
