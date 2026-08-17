"""Risk-budget sizing backtest — does de-concentrating the short-vol sleeve actually help?

The live risk-budget advisory shows vol_carry (SVXY short-vol) is ~20% of capital but ~51% of the book's
RISK — ~7x its risk-parity share. This backtest A/Bs the sizing DECISION in isolation: it holds each
sleeve's own return series FIXED and only swaps the weight vector — the current %-of-equity mix vs the
inverse-vol risk-parity mix — then compares annualized return, vol, Sharpe, and (the point) MAX DRAWDOWN
and the worst-window tail, plus behavior on the market's worst days. If risk-parity cuts the drawdown/tail
without giving up much return, operationalizing it is justified; if it just kills return, it isn't.

HONEST SCOPE — deliberately conservative:
  * These are the sleeves' INSTRUMENT-BASKET buy-and-hold returns (same series the advisory vols use via
    SleeveCapitalBudgetEngine._basket_returns), NOT the sleeves' realized entry/exit P&L. The live sleeves
    have signals (trend goes flat below the 200-DMA; vol_carry is defined-risk + regime-gated) that BLUNT
    the tail the raw instrument shows. So the backtest OVERSTATES vol_carry's crash — it is an UPPER BOUND
    on how much de-concentration helps. That's the safe side to err: it can't make risk-parity look better
    than it is on the downside.
  * Both weightings deploy the SAME total (they sum to the same armed %); the book is normalized to
    fully-invested so the comparison is the MIX alone. Isolates the sizing decision, nothing else."""

from datetime import datetime

from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine


class RiskBudgetSizingBacktestEngine:

    STRESS_FRAC = 0.05        # worst 5% of book days = the "stress" tail where concentration bites

    # Long-history proxies for young SHARE CLASSES (same underlying index, decades more data). A young
    # class like QQQM (Nasdaq-100, launched 2020-10) otherwise CAPS the whole backtest at 2020 and hides
    # the Feb-2018 XIV/SVXY and Mar-2020 COVID vol spikes — the exact tails that make the short-vol
    # concentration dangerous. For a RISK backtest the older equivalent (QQQ/GLD) is the correct proxy;
    # the live sleeve still trades the cheaper young class. Only 1:1 same-index equivalents belong here.
    _HISTORY_PROXY = {"QQQM": "QQQ", "GLDM": "GLD"}

    @staticmethod
    def _metrics(rets):
        """Annualized return/vol/Sharpe + max drawdown + worst single day + worst 5-day window, from a daily
        return list. Pure python; None-safe on a short series."""
        import math
        n = len(rets)
        if n < 30:
            return None
        mean = sum(rets) / n
        var = sum((r - mean) ** 2 for r in rets) / (n - 1)
        vol_d = math.sqrt(var)
        ann_vol = vol_d * math.sqrt(252)
        # geometric annualized return
        growth = 1.0
        for r in rets:
            growth *= (1.0 + r)
        ann_return = growth ** (252.0 / n) - 1.0 if growth > 0 else -1.0
        sharpe = (ann_return / ann_vol) if ann_vol > 1e-9 else None
        # max drawdown on the cumulative curve
        peak, cum, max_dd = 1.0, 1.0, 0.0
        for r in rets:
            cum *= (1.0 + r)
            peak = max(peak, cum)
            max_dd = min(max_dd, cum / peak - 1.0)
        worst_day = min(rets)
        worst_5d = min(sum(rets[i:i + 5]) for i in range(0, n - 4)) if n >= 5 else worst_day
        return {
            "ann_return_pct": round(ann_return * 100, 2),
            "ann_vol_pct": round(ann_vol * 100, 2),
            "sharpe": round(sharpe, 2) if sharpe is not None else None,
            "max_drawdown_pct": round(max_dd * 100, 2),
            "worst_day_pct": round(worst_day * 100, 2),
            "worst_5d_pct": round(worst_5d * 100, 2),
        }

    @classmethod
    def run(cls):
        adv = SleeveCapitalBudgetEngine.risk_budget_advisory()
        sleeves = adv.get("sleeves") or {}
        if not sleeves:
            return {"status": "RISK_BUDGET_SIZING_BACKTEST", "error": "no armed sleeves in the advisory"}

        # per-sleeve basket return series (the SAME source the advisory vols use)
        series = {}
        for s in sleeves:
            syms = SleeveCapitalBudgetEngine._sleeve_instruments(s)
            syms = [cls._HISTORY_PROXY.get(sym, sym) for sym in syms]   # young class -> long-history equiv
            rows = SleeveCapitalBudgetEngine._basket_returns(syms) if syms else []
            if rows:
                series[s] = dict(rows)
        names = [s for s in sleeves if s in series]
        if len(names) < 2:
            return {"status": "RISK_BUDGET_SIZING_BACKTEST",
                    "error": "need >=2 sleeves with data; got %d" % len(names), "have": names}

        common = sorted(set.intersection(*[set(series[s].keys()) for s in names]))
        if len(common) < 60:
            return {"status": "RISK_BUDGET_SIZING_BACKTEST",
                    "error": "insufficient overlapping history (%d days)" % len(common)}

        def _norm(key):
            raw = {s: max(0.0, float(sleeves[s].get(key) or 0.0)) for s in names}
            tot = sum(raw.values()) or 1.0
            return {s: raw[s] / tot for s in names}

        w_cur = _norm("current_pct")
        w_rp = _norm("risk_parity_pct")

        cur_book = [sum(w_cur[s] * series[s][d] for s in names) for d in common]
        rp_book = [sum(w_rp[s] * series[s][d] for s in names) for d in common]

        m_cur = cls._metrics(cur_book)
        m_rp = cls._metrics(rp_book)

        # stress tail: the worst STRESS_FRAC of days ranked by the CURRENT book — where concentration bites.
        k = max(1, int(len(common) * cls.STRESS_FRAC))
        stress_idx = sorted(range(len(common)), key=lambda i: cur_book[i])[:k]
        cur_stress = sum(cur_book[i] for i in stress_idx) / k
        rp_stress = sum(rp_book[i] for i in stress_idx) / k

        dd_cur, dd_rp = m_cur["max_drawdown_pct"], m_rp["max_drawdown_pct"]
        sh_cur, sh_rp = (m_cur["sharpe"] or 0), (m_rp["sharpe"] or 0)
        dd_better = dd_rp > dd_cur                      # less negative = shallower drawdown
        sh_better = sh_rp >= sh_cur - 0.05              # within noise counts as "not worse"
        if dd_better and sh_better:
            verdict = ("RISK-PARITY WINS: shallower max drawdown (%.1f%% vs %.1f%%) without giving up "
                       "risk-adjusted return (Sharpe %.2f vs %.2f). De-concentrating short-vol is justified."
                       % (dd_rp, dd_cur, sh_rp, sh_cur))
        elif dd_better and not sh_better:
            verdict = ("TRADE-OFF: risk-parity cuts drawdown (%.1f%% vs %.1f%%) but lowers Sharpe "
                       "(%.2f vs %.2f) — a risk-vs-return choice, not a free win." % (dd_rp, dd_cur, sh_rp, sh_cur))
        else:
            verdict = ("CURRENT MIX HOLDS: risk-parity does not improve the drawdown (%.1f%% vs %.1f%%); "
                       "de-concentration isn't paying off on this data." % (dd_rp, dd_cur))

        return {
            "as_of": datetime.utcnow().isoformat(),
            "window": {"start": common[0], "end": common[-1], "days": len(common)},
            "sleeves": [{
                "sleeve": s,
                "current_weight_pct": round(w_cur[s] * 100, 1),
                "risk_parity_weight_pct": round(w_rp[s] * 100, 1),
                "ann_vol_pct": sleeves[s].get("vol_annual_pct"),
                "current_risk_share_pct": sleeves[s].get("current_risk_share_pct"),
            } for s in names],
            "current": m_cur,
            "risk_parity": m_rp,
            "delta": {
                "sharpe": round(sh_rp - sh_cur, 2),
                "max_drawdown_pct": round(dd_rp - dd_cur, 2),      # positive = shallower under risk-parity
                "ann_return_pct": round(m_rp["ann_return_pct"] - m_cur["ann_return_pct"], 2),
                "ann_vol_pct": round(m_rp["ann_vol_pct"] - m_cur["ann_vol_pct"], 2),
            },
            "stress_tail": {
                "days": k, "frac": cls.STRESS_FRAC,
                "current_mean_pct": round(cur_stress * 100, 2),
                "risk_parity_mean_pct": round(rp_stress * 100, 2),
                "improvement_pct": round((rp_stress - cur_stress) * 100, 2),
            },
            "verdict": verdict,
            "caveats": [
                "Instrument-basket buy-and-hold returns, NOT sleeve entry/exit P&L — the live signals "
                "(trend flat below 200-DMA, vol_carry defined-risk + regime-gated) blunt the raw tail, so "
                "this OVERSTATES vol_carry's crash and is an UPPER BOUND on the de-concentration benefit.",
                "Book normalized to fully-invested; both weightings deploy the same total, so the delta is "
                "the sizing MIX alone.",
                "Weights taken live from the risk-budget advisory, so this tracks the same numbers as "
                "/sleeve-budgets.",
            ],
            "status": "RISK_BUDGET_SIZING_BACKTEST",
        }
