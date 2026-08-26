"""Real-vs-with-shadows unrealized P/L — a side-by-side snapshot.

The real book marks off the broker; the zero-capital shadows carry only a HYPOTHETICAL P/L (equity shadows use
100-share illustration lots, the condor shadow uses real contract multipliers). This engine reads each existing
shadow's own report (the single source of truth — it never re-derives a shadow's P/L) and the broker view, and
presents: the real book alone, the hypothetical shadow book, and the two combined.

HONEST FRAMING baked into the output: combining a real broker-marked book with hypothetical zero-capital shadows
is apples-to-oranges — the % is expressed as return on the (real + hypothetical) capital that WOULD be at work,
never as a loss on the $10k base (the shadows imply capital the book doesn't actually hold). Long-only,
beta-laden shadows (their P/L is mostly equity beta, not the edge under test) are tagged and also netted out so
you can see the market-neutral-only combination."""

from datetime import datetime
from os import getenv


class ShadowInclusivePnlEngine:

    # (label, module, class, style). style: long_only_beta = mostly equity beta (tagged + netted out for the
    # "market-neutral only" view); market_neutral = the edge under test; long_only = directional but small book.
    SHADOWS = [
        ("Momentum-equity",     "momentum_reversal_shadow_engine", "MomentumReversalShadowEngine", "long_only"),
        ("Extended-ETF (long)", "extended_etf_shadow_engine",      "ExtendedEtfShadowEngine",      "long_only_beta"),
        ("FX-trend",            "fx_trend_shadow_engine",          "FxTrendShadowEngine",          "market_neutral"),
        ("Vol-ETP",             "vol_etp_shadow_engine",           "VolEtpShadowEngine",           "long_only"),
        ("GEX mean-rev",        "gex_mean_reversion_shadow_engine","GexMeanReversionShadowEngine", "market_neutral"),
        ("IV-skew",             "iv_skew_shadow_engine",           "IvSkewShadowEngine",           "market_neutral"),
    ]

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _sum_open(cls, rows):
        """(hypothetical unrealized $, #open with $, hypothetical notional) for an equity-style shadow's rows."""
        tot, n, notion = 0.0, 0, 0.0
        for r in (rows or []):
            d = r.get("pnl_dollars")
            if d is None:
                continue
            tot += cls._f(d)
            n += 1
            notion += abs(cls._f(r.get("entry_close"))) * 100 * int(r.get("contracts") or 1)
        return round(tot, 2), n, round(notion, 2)

    def _real(self):
        """Real broker-marked unrealized $ + deployed cost basis. Degraded-read safe."""
        try:
            from app.services.broker_account_view_engine import BrokerAccountViewEngine
            snap = BrokerAccountViewEngine().snapshot()
        except Exception as e:
            return {"ok": False, "error": repr(e)[:80]}
        if not snap.get("reads_ok"):
            return {"ok": False, "status": snap.get("status"), "note": "broker read degraded — real book unknown"}
        pos = snap.get("positions") or []
        unreal = round(sum(self._f(p.get("unrealized_pnl")) for p in pos), 2)
        deployed = round(sum(self._f(p.get("entry_price")) * self._f(p.get("quantity")) for p in pos), 2)
        return {"ok": True, "unrealized_usd": unreal, "deployed_usd": deployed,
                "unrealized_pct": round(unreal / deployed * 100, 2) if deployed else None,
                "positions": len(pos)}

    def _shadow_rows(self):
        rows = []
        for label, mod, cls, style in self.SHADOWS:
            try:
                m = __import__("app.services." + mod, fromlist=[cls])
                rep = getattr(m, cls)().report()
                tot, n, notion = self._sum_open(rep.get("open_positions"))
                rows.append({"shadow": label, "style": style, "unrealized_usd": tot,
                             "open_positions": n, "hypothetical_notional_usd": notion})
            except Exception as e:
                rows.append({"shadow": label, "style": style, "error": repr(e)[:60]})
        # Extended-ETF long/short twin (market-neutral) — the real edge test
        try:
            from app.services.extended_etf_shadow_engine import ExtendedEtfShadowEngine as X
            ls = (X().report().get("long_short") or {}).get("open_positions")
            tot, n, notion = self._sum_open(ls)
            rows.append({"shadow": "Extended-ETF (L/S)", "style": "market_neutral", "unrealized_usd": tot,
                         "open_positions": n, "hypothetical_notional_usd": notion})
        except Exception as e:
            rows.append({"shadow": "Extended-ETF (L/S)", "style": "market_neutral", "error": repr(e)[:60]})
        # Condor shadow (VRP + earnings) — real contract multiplier, not a 100-share lot
        try:
            from app.services.condor_shadow_engine import CondorShadowEngine as CS
            rep = CS().report()
            rows.append({"shadow": "Condor (VRP+Earn)", "style": "market_neutral",
                         "unrealized_usd": round(self._f(rep.get("unrealized_pnl")), 2),
                         "open_positions": len(rep.get("open_positions") or []),
                         "hypothetical_notional_usd": 0.0, "basis": "real contract multiplier"})
        except Exception as e:
            rows.append({"shadow": "Condor (VRP+Earn)", "style": "market_neutral", "error": repr(e)[:60]})
        # Futures TSMOM (long/short) — MATCHED-NOTIONAL (operator decision 2026-08-25). A raw sum of its per-
        # contract $ would swamp the aggregate: 1 futures contract carries $100k-$800k notional, so the book's
        # 1-contract unrealized $ runs ±$19k on a $10k mental base. Instead each leg is sized to a fixed, small
        # allocation (default $1,000, GREYLINE_SHADOW_MATCHED_NOTIONAL) and its $ is notional × signed %-return,
        # so it lands on the same scale as the equity 100-share-lot shadows and is honestly summable.
        try:
            from app.services.futures_tsmom_shadow_engine import FuturesTsmomShadowEngine as FT
            notl = float(getenv("GREYLINE_SHADOW_MATCHED_NOTIONAL", "1000") or 1000)
            tot, n = 0.0, 0
            for r in (FT().report().get("open_positions") or []):
                ec, ll = self._f(r.get("entry_close")), self._f(r.get("live_last"))
                if ec <= 0 or ll <= 0:
                    continue
                raw = ll / ec - 1.0
                signed = raw if str(r.get("side") or "").upper() in ("BUY", "LONG") else -raw
                tot += notl * signed
                n += 1
            rows.append({"shadow": "Futures TSMOM", "style": "market_neutral",
                         "unrealized_usd": round(tot, 2), "open_positions": n,
                         "hypothetical_notional_usd": round(notl * n, 2),
                         "basis": f"matched notional ${notl:,.0f}/leg"})
        except Exception as e:
            rows.append({"shadow": "Futures TSMOM", "style": "market_neutral", "error": repr(e)[:60]})
        return rows

    def snapshot(self):
        real = self._real()
        shadows = self._shadow_rows()
        priced = [s for s in shadows if "unrealized_usd" in s]

        shadow_unreal = round(sum(s["unrealized_usd"] for s in priced), 2)
        shadow_notion = round(sum(s.get("hypothetical_notional_usd") or 0 for s in priced), 2)
        # market-neutral only = exclude the beta-laden long-only shadows (their P/L is mostly equity beta)
        mn = [s for s in priced if s["style"] != "long_only_beta"]
        mn_unreal = round(sum(s["unrealized_usd"] for s in mn), 2)
        mn_notion = round(sum(s.get("hypothetical_notional_usd") or 0 for s in mn), 2)

        out = {"timestamp": datetime.utcnow().isoformat(),
               "real_book": real, "shadows": shadows,
               "shadow_total": {"unrealized_usd": shadow_unreal, "hypothetical_notional_usd": shadow_notion},
               "status": "SHADOW_INCLUSIVE_PNL"}

        if real.get("ok"):
            rd, ru = real["deployed_usd"], real["unrealized_usd"]

            def _combo(sh_unreal, sh_notion):
                cap = rd + sh_notion
                comb = round(ru + sh_unreal, 2)
                return {"unrealized_usd": comb,
                        "pct_of_capital_at_work": round(comb / cap * 100, 2) if cap else None,
                        "capital_at_work_usd": round(cap, 2)}

            out["combined_all_shadows"] = _combo(shadow_unreal, shadow_notion)
            out["combined_market_neutral_only"] = _combo(mn_unreal, mn_notion)
            out["note"] = (
                "Real book marks off the broker; shadows are ZERO-CAPITAL hypotheticals — combining them is a "
                "thought experiment. The % is return on the (real + hypothetical) capital that WOULD be at work, "
                "NOT a loss on the $10k base. 'market_neutral_only' nets out the long-only beta-laden shadows "
                "(chiefly the Extended-ETF long basket, whose P/L is mostly equity beta, not the edge under test).")
        else:
            out["note"] = "Real book read is degraded — showing the hypothetical shadow book only."
        return out
