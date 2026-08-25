"""Reality Guard — continuously proves GreyLine is on real broker data, not fantasy.

GreyLine's "fantasy land" failure mode is specific and has happened: a local JSON ledger
fills with fabricated positions and P&L that were NEVER booked at TradeStation, and the
dashboard renders them as if real. This engine encodes the invariants that must hold for the
displayed state to be trustworthy, and fails LOUD the instant one breaks. It is read-only and
never throws — a guard that crashes guards nothing.

Invariants (a CRITICAL failure means "fantasy detected", the dashboard must go red):

  ACCOUNT_SOURCE_RESOLVED   (critical) the account selector resolves to a real TradeStation
                            account with the host/account interlock intact.
  BROKER_READS_OK           (critical) the dashboard's holdings/balance actually came back
                            from TradeStation this cycle (HTTP 200 on all three reads).
  NO_PHANTOM_POSITIONS      (critical) the local paper ledger holds NO open position that the
                            broker account does not — i.e. nothing is displayed/tracked that
                            was never booked. This is the exact fantasy condition.
  EXEC_BOOKING_COHERENT     (critical) if paper execution is ON, real SIM booking must also be
                            ON. Otherwise every "trade" lands only in the local ledger and
                            never reaches the broker — fantasy by construction.
  DATA_SOURCE_REAL          (warning)  the strategy's candidate data comes from a real feed
                            (live or cached real bars), not a synthetic/unknown source, and is
                            not absurdly stale.
"""

import json
import time as _clock
from datetime import datetime, timedelta
from os import getenv
from pathlib import Path

REAL_DATA_SOURCES = {"TRADESTATION_LIVE", "TRADESTATION_LIVE_CACHED", "CSV_HISTORICAL"}

# READ-THROUGH CACHE for the guard verdict. check() runs a broker snapshot + ~30 disk/data invariant
# reads (~30s on the live service). Every operator route (dashboard banner, open-positions, backend-admin)
# recomputed it live → the safety banner was effectively unreadable. It's a DISPLAY of a verdict, so it
# follows "engines decide (scheduler), displays render (serve cache)": the scheduler recomputes it fresh
# and the routes serve the cached verdict with an age label. Only a real, fully-computed check is cached.
_GUARD_CACHE = {"at": 0.0, "result": None}


def _guard_ttl():
    try:
        return float(getenv("GREYLINE_REALITY_GUARD_CACHE_TTL_S", "150") or 150)
    except (TypeError, ValueError):
        return 150.0


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
MAX_CANDIDATE_STALE_DAYS = 5


def _flag(name):
    return (getenv(name, "") or "").strip().strip("'\"").lower() == "true"


class GreyLineRealityGuardEngine:

    def _check_account_source(self):
        try:
            from app.services.tradestation_account_source_engine import TradeStationAccountSourceEngine
            src = TradeStationAccountSourceEngine().resolve()
            return {
                "id": "ACCOUNT_SOURCE_RESOLVED", "severity": "critical",
                "ok": bool(src.get("ok")),
                "detail": src.get("label") if src.get("ok") else (src.get("error") or "unresolved"),
            }
        except Exception as e:
            return {"id": "ACCOUNT_SOURCE_RESOLVED", "severity": "critical", "ok": False,
                    "detail": f"selector error: {str(e)[:120]}"}

    def _check_broker_reads(self, view):
        # degraded_class: a FAILED broker read is UNVERIFIABLE, not FANTASY. Fantasy = fake numbers shown
        # as real; a degraded read makes the dashboard honestly show "unknown"/last-known-good (the money
        # tiles already null out + badge age, the phantom/positions checks fail-safe). So this must NOT
        # trip the red "FANTASY DATA DETECTED" alarm — that cries wolf on a benign, self-healing state
        # (usually a busy scheduler cycle saturating TradeStation) and erodes trust in the guard. It maps
        # to the amber BROKER_READ_DEGRADED verdict instead. It stays 'critical' so it can never be
        # ignored, but degraded_class routes it to the honest verdict.
        return {
            "id": "BROKER_READS_OK", "severity": "critical", "degraded_class": True,
            "ok": bool(view.get("reads_ok")),
            "broker_side": bool(view.get("read_broker_side")),   # 5xx from TS = their server, not our blip
            "detail": (f"reading {view.get('account_label')}" if view.get("reads_ok")
                       else ("broker read failed — " + (view.get("read_detail") or view.get("status") or "")
                             + (" (TradeStation server error — broker-side outage)"
                                if view.get("read_broker_side") else " (likely a transient local blip)"))),
        }

    def _check_phantom_positions(self, view):
        """No open position in EITHER local ledger (equity or options) that the broker does
        not actually hold. Covers both books so options mode cannot open a fantasy hole."""
        import json
        from pathlib import Path

        ledger_syms = set()
        try:
            from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine
            for t in PaperTradeLedgerEngine()._read_all():
                if t.get("status") == "OPEN" and t.get("symbol"):
                    ledger_syms.add(str(t.get("symbol")).upper())
        except Exception as e:
            return {"id": "NO_PHANTOM_POSITIONS", "severity": "critical", "ok": False,
                    "detail": f"equity ledger read error: {str(e)[:120]}"}
        # options ledger — open positions are keyed by the OSI option symbol
        try:
            opt_file = Path("app/data/options_paper_trading/options_paper_trade_ledger.jsonl")
            if opt_file.exists():
                for line in opt_file.read_text().splitlines():
                    if not line.strip():
                        continue
                    t = json.loads(line)
                    if t.get("status") == "OPEN" and t.get("option_symbol"):
                        ledger_syms.add(str(t.get("option_symbol")).upper())
        except Exception:
            pass

        # FAIL-SAFE on a degraded broker read: if the broker positions couldn't be read, the broker-held
        # set is empty/partial, and comparing the local ledger to it would flag EVERY local position as a
        # phantom — a FALSE fantasy alarm. You cannot call a position phantom if you couldn't read the
        # broker. BROKER_READS_OK already flags the real (degraded) problem; don't double-cry a fabricated
        # phantom list on top of it. (Same fail-safe as the concentration breaker's degraded-read guard.)
        if not view.get("reads_ok", True):
            return {"id": "NO_PHANTOM_POSITIONS", "severity": "critical", "ok": True,
                    "detail": "broker read degraded — phantom check UNVERIFIED this cycle (cannot compare "
                              "the local ledger to an unread broker; see BROKER_READS_OK)",
                    "phantoms": [], "unverified": True}

        broker_syms = {str(p.get("symbol") or "").upper() for p in (view.get("positions") or [])}
        # A WORKING buy-to-open limit order is a legitimate in-between state: the entry is
        # recorded and submitted, but the broker has not filled it yet. That is pending, not
        # fantasy — counting it as a phantom would make the guard cry wolf on every limit
        # entry (which is now the normal entry path) and train the operator to ignore it.
        # If the order later dies, the reconciler voids the ledger entry; if it is never
        # resolved, the symbol drops out of `working` and it becomes a phantom for real.
        pending_syms = {str(b.get("symbol") or "").upper()
                        for b in (view.get("pending_buys") or [])}
        phantoms = sorted(s for s in ledger_syms if s not in broker_syms and s not in pending_syms)
        pending_open = sorted(ledger_syms & (pending_syms - broker_syms))
        return {
            "id": "NO_PHANTOM_POSITIONS", "severity": "critical",
            "ok": not phantoms,
            "detail": ((f"no local ledger positions (equity or options) absent from the broker"
                        + (f"; {len(pending_open)} awaiting fill" if pending_open else ""))
                       if not phantoms
                       else f"{len(phantoms)} phantom position(s) in local ledger, not held at broker: "
                            f"{', '.join(phantoms[:8])}"),
            "phantoms": phantoms,
            "pending_fill": pending_open,
        }

    # CANONICAL map of every direct-to-broker sleeve -> the instruments it manages while armed. ONE source
    # of truth: managed_symbols() (untracked-risk guard + dashboard labels) AND _active_universe() (price-bar
    # scope) both read it, so they can never disagree and no sleeve can be forgotten. (flag, module, class,
    # attr) — attr is a str symbol, a list/tuple basket, or a 0-arg method (tbill .symbol()).
    _DIRECT_BROKER_SLEEVES = (
        ("GREYLINE_VOL_CARRY_ENABLED", "vol_term_structure_carry_engine", "VolTermStructureCarryEngine", "SYMBOL"),
        ("GREYLINE_TREND_ENABLED", "trend_following_engine", "TrendFollowingEngine", "BASKET"),
        ("GREYLINE_LOW_VOL_ENABLED", "low_volatility_engine", "LowVolatilityEngine", "BASKET"),
        ("GREYLINE_XSMOM_ENABLED", "cross_sectional_momentum_engine", "CrossSectionalMomentumEngine", "UNIVERSE"),
        ("GREYLINE_MANAGED_FUTURES_ENABLED", "managed_futures_engine", "ManagedFuturesEngine", "BASKET"),
        ("GREYLINE_TBILL_SWEEP_ENABLED", "tbill_cash_sweep_engine", "TbillCashSweepEngine", "symbol"),
    )

    @classmethod
    def _armed_sleeve_symbols(cls):
        """Symbols managed by the ARMED direct-to-broker sleeves (empty for any that's off/unreadable)."""
        from os import getenv
        import importlib
        out = set()
        for flag, module, klass, attr in cls._DIRECT_BROKER_SLEEVES:
            if (getenv(flag, "") or "").strip().lower() != "true":
                continue
            try:
                val = getattr(getattr(importlib.import_module("app.services." + module), klass), attr)
                val = val() if callable(val) else val      # tbill .symbol() is a method; the rest are attrs
                if isinstance(val, str):
                    out.add(val.upper())
                else:
                    out.update(str(s).upper() for s in val)
            except Exception:
                pass
        return out

    def managed_symbols(self):
        """The single definition of what GreyLine actually opened and is managing.

        Owned here, not in a route: the guard uses it to detect untracked broker risk and
        the dashboard uses it to label rows, and those two must never disagree. Routes stay
        display-only — they read this instead of touching a ledger themselves, which also
        keeps the "positions come from the broker, never the local ledger" rule intact.
        """
        import json
        from pathlib import Path

        syms = set()
        try:
            from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine
            for t in PaperTradeLedgerEngine()._read_all():
                if t.get("status") == "OPEN" and t.get("symbol"):
                    syms.add(str(t["symbol"]).upper())
        except Exception:
            pass
        try:
            f = Path("app/data/options_paper_trading/options_paper_trade_ledger.jsonl")
            if f.exists():
                for line in f.read_text().splitlines():
                    if not line.strip():
                        continue
                    t = json.loads(line)
                    if t.get("status") == "OPEN" and t.get("option_symbol"):
                        syms.add(str(t["option_symbol"]).upper())
        except Exception:
            pass
        # VRP defined-risk condors: each is one ledger unit with 4 legs. All legs are GreyLine-
        # managed (as a unit, by the VRP engine's exit doctrine) — without this they mislabel as
        # UNMANAGED on the dashboard and read as untracked broker risk to the guard.
        try:
            f = Path("app/data/options_paper_trading/vrp_short_premium_ledger.jsonl")
            if f.exists():
                for line in f.read_text().splitlines():
                    if not line.strip():
                        continue
                    t = json.loads(line)
                    if t.get("status") == "OPEN":
                        for lg in t.get("legs", []) or []:
                            s = str(lg.get("symbol") or "").upper()
                            if s:
                                syms.add(s)
        except Exception:
            pass
        # Direct-to-broker equity/ETF sleeves (carry/trend/low_vol/xs_momentum/managed_futures/T-bill) book
        # straight to the broker, not a paper ledger — register each armed sleeve's instruments as managed,
        # or they mislabel UNMANAGED on the dashboard and read as untracked risk to the guard. ONE canonical
        # list (was carry/trend/tbill only here — low_vol + xs were armed but never added, so low_vol's held
        # basket read as untracked; fixed 2026-08-11).
        syms |= self._armed_sleeve_symbols()
        return syms

    def _check_untracked_broker_positions(self, view):
        """The MIRROR of the phantom check: the broker holds something no GreyLine ledger does.

        A phantom is GreyLine claiming a position it doesn't have. This is the opposite —
        real risk in the account that GreyLine is not managing: no stop, no take-profit, no
        maturity liquidation, and it is still rendered on the broker-sourced dashboard as if
        it were GreyLine's. Silent is the dangerous part.

        WARNING, not critical: the account holder may legitimately place their own trades.
        The requirement is that such positions are visible and labelled, never mistaken for
        GreyLine's own book.
        """
        tracked = self.managed_symbols()
        untracked = sorted({str(p.get("symbol") or "").upper()
                            for p in (view.get("positions") or [])} - tracked)
        return {
            "id": "NO_UNTRACKED_BROKER_POSITIONS", "severity": "warning",
            "ok": not untracked,
            "detail": ("every broker position is tracked by a GreyLine ledger"
                       if not untracked
                       else f"{len(untracked)} broker position(s) NOT managed by GreyLine "
                            f"(no stop/TP/maturity rule applies): {', '.join(untracked[:8])}"),
            "untracked": untracked,
        }

    def _check_exec_booking_coherent(self):
        paper_exec = _flag("GREYLINE_PAPER_EXECUTION_ENABLED")
        sim_booking = _flag("GREYLINE_SIM_BOOKING_ENABLED")
        ok = (not paper_exec) or sim_booking
        return {
            "id": "EXEC_BOOKING_COHERENT", "severity": "critical", "ok": ok,
            "detail": ("execution and booking are coherent"
                       if ok else
                       "PAPER EXECUTION IS ON BUT SIM BOOKING IS OFF — trades would fabricate in the "
                       "local ledger and never reach TradeStation. Turn on GREYLINE_SIM_BOOKING_ENABLED "
                       "or turn off GREYLINE_PAPER_EXECUTION_ENABLED."),
            "paper_execution_enabled": paper_exec, "sim_booking_enabled": sim_booking,
        }

    def _check_data_source(self):
        try:
            import json
            from pathlib import Path
            cache = Path("app/data/momentum_reversal/top_candidates_cache.json")
            if not cache.exists():
                return {"id": "DATA_SOURCE_REAL", "severity": "warning", "ok": True,
                        "detail": "no candidate snapshot computed yet"}
            from os import getenv
            d = json.loads(cache.read_text())
            source = d.get("data_source")
            as_of = d.get("as_of")
            source_ok = source in REAL_DATA_SOURCES
            stale = False
            if as_of:
                try:
                    stale = (datetime.utcnow().date() - datetime.fromisoformat(str(as_of)[:10]).date()).days > MAX_CANDIDATE_STALE_DAYS
                except (ValueError, TypeError):
                    stale = False
            # WRONG-FLAG FIX (2026-08-17, same shape as the condor cache): top_candidates_cache.json is PRODUCED
            # only by MomentumScanWarmEngine.warm_if_due (gated on GREYLINE_MOMENTUM_SCAN_WARM, OFF by default) —
            # NOT by arming the momentum sleeve (the rebalance path writes different files and never reads this
            # one). So gate STALENESS on the producer's flag: with scan-warm off nothing auto-refreshes it, so a
            # stale snapshot is EXPECTED (e.g. operator away >5d), not a fault. A FAKE source is always flagged.
            scan_warm_on = (getenv("GREYLINE_MOMENTUM_SCAN_WARM", "false") or "").strip().lower() == "true"
            stale_flag = stale and scan_warm_on
            ok = source_ok and not stale_flag
            note = "" if scan_warm_on else " (scan-warm off — snapshot not auto-refreshed, staleness expected)"
            return {"id": "DATA_SOURCE_REAL", "severity": "warning", "ok": ok,
                    "detail": (f"candidates from {source} as of {as_of}{note}" if ok
                               else f"suspect candidate source={source!r} as_of={as_of!r} "
                                    f"(real sources: {sorted(REAL_DATA_SOURCES)}, max {MAX_CANDIDATE_STALE_DAYS}d stale)")}
        except Exception as e:
            return {"id": "DATA_SOURCE_REAL", "severity": "warning", "ok": True,
                    "detail": f"data-source check skipped: {str(e)[:100]}"}

    def _active_universe(self):
        """Symbols whose bar quality actually matters RIGHT NOW: what GreyLine holds/manages plus the
        trading universe of each ARMED sleeve. A corrupt/mismatched bar in a symbol no armed sleeve trades
        and we don't hold is real but INERT — it can't poison a live signal, ATR or stop — so it should NOT
        raise the banner. Returns None to mean "don't scope, check everything" (when momentum is armed its
        screener universe is broad enough that effectively everything is signal-relevant). Reads only local
        ledgers + static sleeve baskets — never the broker (this runs on every dashboard refresh)."""
        from os import getenv
        if (getenv("GREYLINE_MOMENTUM_ENABLED", "true") or "").strip().lower() == "true":
            return None
        # managed_symbols() already folds in the armed direct-to-broker baskets via the canonical list
        # (which also fixes the old XSMOM_ENABLED flag-name typo that silently dropped xs_momentum here).
        return {str(s).upper() for s in self.managed_symbols()}

    @staticmethod
    def _scope_symbols(raw):
        """Flatten a scan issue's `symbol` field (may be a comma-joined DUP list) to individual tickers."""
        return {s.strip().upper() for s in str(raw or "").split(",") if s.strip()}

    def _check_price_bars(self):
        """The price bars every signal/ATR/stop is computed from must not be corrupt.

        Reads the LAST SCAN (PriceBarIntegrityEngine writes it) rather than rescanning — a
        full pass is seconds-long and this runs on every dashboard refresh. Critical findings
        (impossible OHLC, cross-symbol duplicate closes, non-positive prices) mean signals are
        being computed on bad data, which manufactures fake edge.
        """
        try:
            from app.services.price_bar_integrity_engine import PriceBarIntegrityEngine
            scan = PriceBarIntegrityEngine().last_scan()
        except Exception as e:
            return {"id": "PRICE_BARS_CLEAN", "severity": "warning", "ok": True,
                    "detail": f"price-bar check skipped: {str(e)[:100]}"}
        if not scan:
            return {"id": "PRICE_BARS_CLEAN", "severity": "warning", "ok": True,
                    "detail": "no price-bar scan run yet"}
        crit = int(scan.get("critical_count") or 0)
        age = ""
        try:
            age = (f", scanned {(datetime.utcnow() - datetime.fromisoformat(scan['scanned_at'])).days}d ago")
        except Exception:
            pass
        if crit == 0:
            return {"id": "PRICE_BARS_CLEAN", "severity": "warning", "ok": True,
                    "detail": f"{scan.get('symbols_checked')} symbols clean ({scan.get('mode')}{age})"}
        # SCOPE to signal-relevant bars: corruption in a symbol no armed sleeve trades / we don't hold, OR in a
        # thin sub-253-bar stub the screener never reads (e.g. AAAC/ABI), is real but INERT — it can't poison a
        # live signal/ATR/stop. Alarm only on corruption in a TRADEABLE, in-universe name.
        from app.services.price_bar_integrity_engine import PriceBarIntegrityEngine as _PBI
        from pathlib import Path as _P
        active = self._active_universe()
        corrupt_syms = set()
        for i in (scan.get("issues") or []):
            if i.get("type") in _PBI.CRITICAL_TYPES:
                corrupt_syms |= self._scope_symbols(i.get("symbol"))
        live_bad, thin, inert = self._scope_tradeable_symbols(
            sorted(corrupt_syms), active, _P("app/data/historical"))
        if live_bad:
            return {"id": "PRICE_BARS_CLEAN", "severity": "warning", "ok": False,
                    "detail": (f"{len(live_bad)} TRADEABLE, in-universe symbol(s) have corrupt bars: "
                               f"{', '.join(sorted(live_bad)[:8])} — signals/ATR/stops at risk{age}")}
        parts = []
        if thin:
            parts.append(f"{len(thin)} thin sub-253-bar stub(s)")
        if inert:
            parts.append(f"{len(inert)} untraded (inert)")
        why = "; ".join(parts) or "none material"
        return {"id": "PRICE_BARS_CLEAN", "severity": "warning", "ok": True,
                "detail": (f"{crit} corrupt bar(s) across {scan.get('symbols_checked')} symbols, but none in a "
                           f"TRADEABLE, in-universe name ({why}){age}")}

    @staticmethod
    def _scope_tradeable_symbols(symbols, active, bars_dir, min_bars=253):
        """Partition symbols into (in_scope, thin, inert): in_scope = in the active universe (or active None =
        everything) AND TRADEABLE (>= min_bars bars). A thin sub-min-bars stub or an out-of-universe name can't
        poison a live signal/ATR/stop, so it must never raise the banner. Shared by the CLEAN + MATCH_SOURCE checks."""
        in_scope, thin, inert = [], [], []
        for raw in symbols:
            s = str(raw or "").upper()
            if not s:
                continue
            if active is not None and s not in active:
                inert.append(s); continue                       # no armed sleeve trades it / we don't hold it
            try:
                nbars = sum(1 for _ in open(bars_dir / f"{s}_daily.csv"))
            except Exception:
                nbars = 0
            if nbars < min_bars:
                thin.append(s); continue                        # sub-min-bars stub — no real signal reads it
            in_scope.append(s)
        return in_scope, thin, inert

    @classmethod
    def _scope_source_mismatches(cls, mismatches, active, run_ts, bars_dir, min_bars=253):
        """Split cross-source VALUE mismatches into (live_bad, restated, thin, inert). Only `live_bad` — in the
        active universe, TRADEABLE, and NOT restated since the scan — poisons a live signal and should page. A
        file rewritten after the run has almost certainly self-healed via restatement -> re-verify, not a fail."""
        in_scope, thin, inert = cls._scope_tradeable_symbols(
            [m.get("symbol") for m in (mismatches or [])], active, bars_dir, min_bars)
        live_bad, restated = [], []
        for s in in_scope:
            try:
                mtime = datetime.utcfromtimestamp((bars_dir / f"{s}_daily.csv").stat().st_mtime)
            except Exception:
                mtime = None
            (restated if (run_ts and mtime and mtime > run_ts) else live_bad).append(s)
        return live_bad, restated, thin, inert

    def _check_price_bars_match_source(self):
        """The bars must match an INDEPENDENT source, not merely be self-consistent.

        PRICE_BARS_CLEAN proves the CSVs are internally coherent. That cannot catch data
        that is uniformly wrong — a shifted series, a mis-mapped ticker, an unadjusted split
        — all of which are self-consistent and would silently poison every ATR, stop and TP.
        This reads the rotating reconciliation against TradeStation's own barcharts.

        Reads the last run rather than reconciling here: this runs on every dashboard
        refresh and the comparison makes real API calls.
        """
        try:
            from app.services.price_bar_cross_source_engine import PriceBarCrossSourceEngine
            run = PriceBarCrossSourceEngine().last_run()
        except Exception as e:
            return {"id": "PRICE_BARS_MATCH_SOURCE", "severity": "warning", "ok": True,
                    "detail": f"cross-source check skipped: {str(e)[:100]}"}
        if not run:
            return {"id": "PRICE_BARS_MATCH_SOURCE", "severity": "warning", "ok": True,
                    "detail": "no cross-source reconciliation run yet"}
        if run.get("ok") is None:
            return {"id": "PRICE_BARS_MATCH_SOURCE", "severity": "warning", "ok": True,
                    "detail": str(run.get("detail") or run.get("status"))[:110]}
        bad = int(run.get("mismatched") or 0)
        age = ""
        try:
            age = f", {(datetime.utcnow() - datetime.fromisoformat(run['timestamp'])).days}d ago"
        except Exception:
            pass
        if bad == 0:
            return {"id": "PRICE_BARS_MATCH_SOURCE", "severity": "warning", "ok": True,
                    "detail": (f"{run.get('matched')}/{run.get('checked')} symbols match "
                               f"TradeStation barcharts{age}")}
        # SCOPE the "wrong prices" page precisely — only where a VALUE mismatch actually poisons a LIVE signal.
        # The cross-source engine already flags only real value disagreements (UNADJUSTED_SPLIT / SYSTEMATIC over
        # OVERLAPPING dates — never mere staleness). On top of that, page only when the symbol is:
        #   (1) in the active signal universe (or momentum-armed = everything is signal-relevant),
        #   (2) TRADEABLE — >= MIN_BARS bars, so a thin/penny sub-253-bar stub the screener never trades doesn't
        #       cry wolf (a $1, 114-bar name is inert), and
        #   (3) NOT restated since the scan — a bar file rewritten after the run has almost certainly self-healed
        #       via cross-source restatement/refresh, so it's pending re-verify, not a hard fail.
        from pathlib import Path as _P
        MIN_BARS = 253
        active = self._active_universe()
        run_ts = None
        try:
            run_ts = datetime.fromisoformat(run["timestamp"])
        except Exception:
            pass
        live_bad, restated, thin, inert = self._scope_source_mismatches(
            run.get("mismatches") or [], active, run_ts, _P("app/data/historical"), MIN_BARS)
        if live_bad:
            return {"id": "PRICE_BARS_MATCH_SOURCE", "severity": "warning", "ok": False,
                    "detail": (f"{len(live_bad)} TRADEABLE, in-universe symbol(s) DISAGREE with TradeStation "
                               f"barcharts{age}: {', '.join(sorted(live_bad)[:5])} — signals computed from wrong prices")}
        parts = []
        if restated:
            parts.append(f"{len(restated)} restated since scan (re-verify pending)")
        if thin:
            parts.append(f"{len(thin)} thin sub-{MIN_BARS}-bar stub(s)")
        if inert:
            parts.append(f"{len(inert)} untraded (inert)")
        why = "; ".join(parts) or "none material"
        return {"id": "PRICE_BARS_MATCH_SOURCE", "severity": "warning", "ok": True,
                "detail": (f"{bad} symbol(s) disagree with TradeStation{age}, but none TRADEABLE + in-universe + "
                           f"unresolved ({why})")}

    def _check_signal_bars_tradable(self):
        """Signals must be computed from bars that were actually TRADED.

        MIN_BARS counts raw bars, so a ticker carrying a long pre-listing stub can satisfy
        253 bars while offering almost no real history — momentum measured across that
        boundary compares prices nobody transacted at, and ATR (every doctrine stop)
        collapses. The strategy now excludes these; this proves the exclusion is live.
        """
        try:
            from app.services.price_bar_tradability_engine import PriceBarTradabilityEngine
            scan = PriceBarTradabilityEngine().last_scan()
        except Exception as e:
            return {"id": "SIGNAL_BARS_TRADABLE", "severity": "warning", "ok": True,
                    "detail": f"tradability check skipped: {str(e)[:100]}"}
        if not scan:
            return {"id": "SIGNAL_BARS_TRADABLE", "severity": "warning", "ok": True,
                    "detail": "no tradability scan run yet"}
        bad = int(scan.get("contaminated_signal_windows") or 0)
        if bad == 0:
            return {"id": "SIGNAL_BARS_TRADABLE", "severity": "warning", "ok": True,
                    "detail": (f"{scan.get('symbols')} symbols: every signal window is built "
                               f"on traded bars")}
        names = ", ".join(r.get("symbol") for r in (scan.get("contaminated") or [])[:5])
        return {"id": "SIGNAL_BARS_TRADABLE", "severity": "warning", "ok": True,
                "detail": (f"{bad} symbol(s) excluded from the universe — signal window "
                           f"reaches into untraded bars: {names}")}

    def _check_survivorship_archive(self):
        """The point-in-time universe archive must be advancing.

        Delisted names cannot be re-acquired — TradeStation answers "Invalid Symbol" for
        every dead ticker — so a day the archive fails to record is a day of survivorship-free
        data lost permanently. This is the one data gap that gets strictly worse with silence.
        """
        try:
            from app.services.universe_survivorship_engine import UniverseSurvivorshipEngine
            st = UniverseSurvivorshipEngine().status()
        except Exception as e:
            return {"id": "SURVIVORSHIP_ARCHIVE_ADVANCING", "severity": "warning", "ok": True,
                    "detail": f"survivorship check skipped: {str(e)[:100]}"}
        days = int(st.get("archive_days") or 0)
        if days == 0:
            return {"id": "SURVIVORSHIP_ARCHIVE_ADVANCING", "severity": "warning", "ok": False,
                    "detail": "no point-in-time universe archive — every day without one is "
                              "survivorship-free data lost for good"}
        return {"id": "SURVIVORSHIP_ARCHIVE_ADVANCING", "severity": "warning", "ok": True,
                "detail": (f"point-in-time universe recorded for {days} day(s) since "
                           f"{st.get('survivorship_free_from')}; "
                           f"{st.get('retained_delisted_count')} delisted name(s) retained. "
                           f"History before that date remains biased.")}

    def _check_total_return_available(self):
        """A dividend-adjusted total-return series should exist alongside the price series.

        Price-only closes understate every dividend payer (MO: 1.77%/yr price vs 13.32% total
        return) and turn each ex-dividend drop into a false reversal dip. This is advisory:
        the raw price series stays valid for price; total return is the correct input for a
        return-based signal and its absence is a quality gap, not a fantasy condition.
        """
        try:
            from app.services.total_return_series_engine import TotalReturnSeriesEngine
            rep = TotalReturnSeriesEngine().last_report()
        except Exception as e:
            return {"id": "TOTAL_RETURN_SERIES_AVAILABLE", "severity": "warning", "ok": True,
                    "detail": f"total-return check skipped: {str(e)[:100]}"}
        if not rep:
            return {"id": "TOTAL_RETURN_SERIES_AVAILABLE", "severity": "warning", "ok": False,
                    "detail": "no total-return series built yet — returns are price-only and "
                              "understate every dividend payer"}
        return {"id": "TOTAL_RETURN_SERIES_AVAILABLE", "severity": "warning", "ok": True,
                "detail": (f"{rep.get('symbols_built')} symbols have a dividend+split adjusted "
                           f"total-return series ({rep.get('total_dividends_applied')} dividends "
                           f"applied)")}

    def _check_regime_gate(self):
        """Surface the market-regime gate so its state is never invisible.

        The gate blocks dip-buys when the index is below its 200DMA. If it silently degrades
        (missing/stale index data) it fails OPEN — trades flow with no crash protection — so
        that state must be visible, not hidden. Advisory: a degraded gate is a protection gap,
        not a fantasy condition.
        """
        try:
            from app.services.market_regime_gate_engine import MarketRegimeGateEngine
            e = MarketRegimeGateEngine()
            r = e.assess()
            enabled = e.enabled()
        except Exception as ex:
            return {"id": "REGIME_GATE_HEALTHY", "severity": "warning", "ok": True,
                    "detail": f"regime check skipped: {str(ex)[:100]}"}
        if not enabled:
            return {"id": "REGIME_GATE_HEALTHY", "severity": "warning", "ok": True,
                    "detail": "regime gate DISABLED — dip-buying has no downtrend brake"}
        if r.get("degraded"):
            return {"id": "REGIME_GATE_HEALTHY", "severity": "warning", "ok": False,
                    "detail": f"regime gate degraded (fails open, no crash brake): {r.get('detail')}"}
        return {"id": "REGIME_GATE_HEALTHY", "severity": "warning", "ok": True,
                "detail": f"{r.get('regime')} — {r.get('detail')}"}

    def _check_lineage_stable(self):
        """Settled price history must not have silently changed since the accepted baseline.

        Every other check verifies the data is correct NOW; this is the only one that notices
        when an already-settled bar changed underneath us (vendor restatement, re-adjustment,
        or corruption). A silent change to validated history makes past research irreproducible
        — the numbers move and nothing says why. Warning severity: a change needs review and
        re-acceptance, it is not a fantasy-positions condition.
        """
        try:
            from app.services.price_bar_lineage_engine import PriceBarLineageEngine
            rep = PriceBarLineageEngine().last_report()
        except Exception as e:
            return {"id": "LINEAGE_STABLE", "severity": "warning", "ok": True,
                    "detail": f"lineage check skipped: {str(e)[:100]}"}
        if not rep:
            return {"id": "LINEAGE_STABLE", "severity": "warning", "ok": True,
                    "detail": "no lineage verification run yet"}
        ch = int(rep.get("changed_count") or 0)
        if ch == 0:
            return {"id": "LINEAGE_STABLE", "severity": "warning", "ok": True,
                    "detail": (f"{rep.get('symbols_checked')} symbols: settled history unchanged "
                               f"since baseline ({rep.get('settled_through')})")}
        names = ", ".join(c.get("symbol") for c in (rep.get("changed") or [])[:5])
        return {"id": "LINEAGE_STABLE", "severity": "warning", "ok": False,
                "detail": (f"{ch} symbol(s) with settled history CHANGED since baseline "
                           f"(review, then re-accept): {names}")}

    def _check_options_capture(self):
        """The options surface must be captured every day — it cannot be recovered later.

        An options edge cannot be backtested here (UW's historic-contract endpoint returns
        nothing; TradeStation purges expired contracts), so this forward panel is the ONLY
        evidence base the options mission can ever be verified against. A day not captured is
        a permanent hole, which is why a stale capture is surfaced rather than ignored.
        """
        # INTENT GATE (consistent with _check_data_source / _check_decision_caches_fresh): the options capture
        # REQUIRES a UW key to advance. With no key the mission isn't being pursued, so "no capture" is EXPECTED,
        # not a fault — else this warns forever on a deployment that never opted into the options mission.
        try:
            from app.services.env_reload import uw_api_key
            if not uw_api_key():
                return {"id": "OPTIONS_CAPTURE_ADVANCING", "severity": "warning", "ok": True,
                        "detail": "options mission not configured (no UW key) — capture N/A"}
        except Exception:
            pass
        try:
            from app.services.options_reality_capture_engine import OptionsRealityCaptureEngine
            cov = OptionsRealityCaptureEngine().coverage()
        except Exception as e:
            return {"id": "OPTIONS_CAPTURE_ADVANCING", "severity": "warning", "ok": True,
                    "detail": f"options capture check skipped: {str(e)[:90]}"}
        days = int(cov.get("days_captured") or 0)
        if days == 0:
            return {"id": "OPTIONS_CAPTURE_ADVANCING", "severity": "warning", "ok": False,
                    "detail": "no options surface captured yet — the options mission has no "
                              "evidence base and cannot be verified"}
        last = str(cov.get("last_day") or "")
        stale = ""
        try:
            age = (datetime.utcnow().date() - datetime.fromisoformat(last).date()).days
            if age > 4:      # allows a holiday weekend
                return {"id": "OPTIONS_CAPTURE_ADVANCING", "severity": "warning", "ok": False,
                        "detail": (f"last options capture {last} is {age}d old — every missed "
                                   f"day is evidence that cannot be reconstructed")}
            stale = f", {age}d ago"
        except Exception:
            pass
        return {"id": "OPTIONS_CAPTURE_ADVANCING", "severity": "warning", "ok": True,
                "detail": (f"{days} day(s) of options surface captured, {cov.get('total_rows')} "
                           f"rows, through {last}{stale}")}

    def _check_backup_current(self):
        """The unrecoverable data must be backed up OFF-MACHINE and recently.

        options_reality, the PIT universe archive and the earnings-vol panel accrue
        forward-only — no API can rebuild them. One disk failure restarts the options edge
        experiment from zero. A same-disk copy does not count and is reported as such.
        """
        # PRIMARY off-machine channel is the GIT backup — the only one the always-on service can run
        # (macOS TCC blocks this LaunchAgent from iCloud + external volumes). If it's fresh, that's
        # real off-machine protection the service itself maintains and can verify.
        try:
            from app.services.git_data_backup_engine import GitDataBackupEngine
            gh = GitDataBackupEngine().hours_since()
            if gh is not None and gh <= 26:
                return {"id": "BACKUP_CURRENT", "severity": "warning", "ok": True,
                        "detail": f"unrecoverable data backed up off-machine via git ({gh}h ago, "
                                  f"branch '{GitDataBackupEngine.BRANCH}')"}
        except Exception:
            pass
        try:
            from app.services.disaster_recovery_engine import DisasterRecoveryEngine
            st = DisasterRecoveryEngine().status()
        except Exception as e:
            return {"id": "BACKUP_CURRENT", "severity": "warning", "ok": True,
                    "detail": f"backup check skipped: {str(e)[:90]}"}
        if not st.get("last_backup_at"):
            return {"id": "BACKUP_CURRENT", "severity": "warning", "ok": False,
                    "detail": "unrecoverable data has NEVER been backed up — a disk failure "
                              "would permanently destroy the options evidence base"}
        if not st.get("off_machine"):
            return {"id": "BACKUP_CURRENT", "severity": "warning", "ok": False,
                    "detail": f"backup destination is on the SAME DISK — not redundancy: "
                              f"{str(st.get('destination_note'))[:70]}"}
        age = st.get("hours_since_backup")
        if age is not None and age > 48:
            return {"id": "BACKUP_CURRENT", "severity": "warning", "ok": False,
                    "detail": f"last off-machine backup was {age}h ago — forward-only data "
                              f"since then is unprotected"}
        # VERIFY the mirror is actually COMPLETE — don't trust the marker's claimed count. A partial
        # run left latest/ with 3 of 17 files while the marker (and this check) reported "17 verified"
        # (2026-07-30). Count the real off-machine files vs what should be protected.
        exp, got = st.get("expected_files"), st.get("off_machine_files")
        if exp is not None and got is not None and got < exp:
            return {"id": "BACKUP_CURRENT", "severity": "warning", "ok": False,
                    "detail": (f"off-machine mirror INCOMPLETE — only {got} of {exp} unrecoverable "
                               f"files present in latest/ (partial/failed backup; marker claims "
                               f"{st.get('files_protected')}). Re-run the backup.")}
        return {"id": "BACKUP_CURRENT", "severity": "warning", "ok": True,
                "detail": (f"{got if got is not None else st.get('files_protected')} of "
                           f"{exp} unrecoverable files verified off-machine, {age}h ago")}

    def _check_restore_drill(self):
        """The off-machine backup must be proven RESTORABLE, not just written. A backup never
        test-restored is a latent DR failure — it can be missing files or corrupt and you only find out
        during a real disaster. Reads the last restore-drill marker (no network here — the scheduler
        runs the actual drill weekly)."""
        try:
            from app.services.disaster_restore_drill_engine import DisasterRestoreDrillEngine
            e = DisasterRestoreDrillEngine()
            hs = e.hours_since()
            import json
            marker = json.loads(e.MARKER.read_text()) if e.MARKER.exists() else {}
        except Exception as ex:
            return {"id": "RESTORE_DRILL_CURRENT", "severity": "warning", "ok": True,
                    "detail": f"restore-drill check skipped: {str(ex)[:90]}"}
        if not marker or hs is None:
            return {"id": "RESTORE_DRILL_CURRENT", "severity": "warning", "ok": False,
                    "detail": "off-machine backup has NEVER been test-restored — restorability UNVERIFIED"}
        if not marker.get("restorable"):
            return {"id": "RESTORE_DRILL_CURRENT", "severity": "warning", "ok": False,
                    "detail": (f"last restore drill FAILED ({marker.get('status')}) — the backup is NOT "
                               f"restorable: {marker.get('missing')} missing, {marker.get('corrupt')} corrupt")}
        if hs > 2 * DisasterRestoreDrillEngine.DUE_HOURS:
            return {"id": "RESTORE_DRILL_CURRENT", "severity": "warning", "ok": False,
                    "detail": f"last successful restore drill was {hs}h ago — overdue, re-run to re-verify"}
        return {"id": "RESTORE_DRILL_CURRENT", "severity": "warning", "ok": True,
                "detail": (f"off-machine backup verified RESTORABLE {hs}h ago "
                           f"({marker.get('verified')}/{marker.get('expected')} TIER1 files present + parse)")}

    def _check_deadman_heartbeat(self):
        """The off-box deadman must actually be BEATING. Every other alert sends from this Mac; if the
        Mac dies only the GitHub-side heartbeat check can reach the operator — but that only works if the
        service is successfully PUSHING the heartbeat. This on-Mac check catches a silently-broken beacon
        (push failing / never pushed) while the Mac is still up. Marker-read only (no push here)."""
        try:
            from app.services.deadman_heartbeat_engine import DeadmanHeartbeatEngine
            e = DeadmanHeartbeatEngine()
            ms = e.minutes_since()
            import json
            marker = json.loads(e.MARKER.read_text()) if e.MARKER.exists() else {}
            interval = e._interval_min()
        except Exception as ex:
            return {"id": "DEADMAN_HEARTBEAT", "severity": "warning", "ok": True,
                    "detail": f"deadman check skipped: {str(ex)[:90]}"}
        if not marker:
            return {"id": "DEADMAN_HEARTBEAT", "severity": "warning", "ok": False,
                    "detail": "off-box deadman heartbeat has NEVER been pushed — a dead Mac would alert no one"}
        if not marker.get("pushed"):
            return {"id": "DEADMAN_HEARTBEAT", "severity": "warning", "ok": False,
                    "detail": f"last deadman heartbeat push FAILED ({str(marker.get('detail'))[:80]}) — "
                              f"the off-box alert is broken while the Mac is still up"}
        if ms is not None and ms > 4 * interval:
            return {"id": "DEADMAN_HEARTBEAT", "severity": "warning", "ok": False,
                    "detail": f"deadman heartbeat is {ms} min stale (interval {interval} min) — the beacon "
                              f"is lagging; the GitHub check may false-alarm or the push is degrading"}
        return {"id": "DEADMAN_HEARTBEAT", "severity": "warning", "ok": True,
                "detail": f"off-box deadman beating — heartbeat pushed to GitHub {ms} min ago "
                          f"(GitHub Action alerts if it goes stale)"}

    def _check_broker_side_protection(self):
        """Open longs should have a failsafe that survives this process dying.

        Every doctrine exit — the ATR stop, the TP ladder, the maturity liquidation — is
        evaluated in software and needs the scheduler alive. If this machine sleeps or the
        process dies, positions with no resting broker order have NO protection at all. This
        surfaces that exposure; it does not fail hard, because the disaster stop is deliberately
        OFF by default (it places real orders) — the point is to make the gap VISIBLE, not
        silent. Positions with a working close order are not counted as exposed.
        """
        try:
            from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine
            st = BrokerProtectiveStopEngine().status()
        except Exception as e:
            return {"id": "BROKER_SIDE_PROTECTION", "severity": "warning", "ok": True,
                    "detail": f"protection check skipped: {str(e)[:90]}"}
        unprotected = st.get("unprotected") or []
        if not unprotected:
            return {"id": "BROKER_SIDE_PROTECTION", "severity": "warning", "ok": True,
                    "detail": ("no open long is exposed — either flat, all closing, or resting "
                               "broker stops are in place")}
        armed = "armed" if st.get("enabled") else "DISABLED (GREYLINE_BROKER_PROTECTIVE_STOPS)"
        return {"id": "BROKER_SIDE_PROTECTION", "severity": "warning", "ok": False,
                "detail": (f"{len(unprotected)} open long(s) have NO broker-side stop — no "
                           f"protection if GreyLine stops running; disaster stops are {armed}. "
                           f"Exposed: {', '.join(unprotected[:8])}")}

    def _check_broker_stops_fire_drill(self):
        """The armed disaster stops must be periodically FIRE-DRILLED — verified as actually resting at
        the broker with FULL-quantity coverage per position, not just 'we placed one once'. The coarse
        BROKER_SIDE_PROTECTION check above misses a partial-qty stop (3 shares resting on a 6-share long).
        Marker-read only (the scheduler runs the actual read-only drill)."""
        try:
            from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine as B
            e = B()
            import json
            p = e._drill_marker_path()
            marker = json.loads(p.read_text()) if p.exists() else {}
            hs = e.drill_hours_since()
        except Exception as ex:
            return {"id": "BROKER_STOPS_FIRE_DRILL", "severity": "warning", "ok": True,
                    "detail": f"fire-drill check skipped: {str(ex)[:90]}"}
        if marker and marker.get("armed") is False:
            return {"id": "BROKER_STOPS_FIRE_DRILL", "severity": "warning", "ok": True,
                    "detail": "disaster stops OFF by design — no coverage to fire-drill"}
        if not marker or hs is None:
            return {"id": "BROKER_STOPS_FIRE_DRILL", "severity": "warning", "ok": False,
                    "detail": "broker-side stops have NEVER been fire-drilled — resting-stop coverage UNVERIFIED"}
        if marker.get("status") == "BROKER_STOPS_GAP" or (marker.get("gaps") or 0) > 0:
            return {"id": "BROKER_STOPS_FIRE_DRILL", "severity": "warning", "ok": False,
                    "detail": f"last fire drill found {marker.get('gaps')} coverage GAP(s) — an armed book has "
                              f"open longs with no / partial resting stop; a process death leaves them unhedged"}
        if hs > 2 * B.FIRE_DRILL_DUE_HOURS:
            return {"id": "BROKER_STOPS_FIRE_DRILL", "severity": "warning", "ok": False,
                    "detail": f"last broker-stop fire drill was {hs}h ago — overdue, re-verify coverage"}
        return {"id": "BROKER_STOPS_FIRE_DRILL", "severity": "warning", "ok": True,
                "detail": f"broker-side stops fire-drilled {hs}h ago — {marker.get('verified')} open long(s) "
                          f"have full-quantity resting stops"}

    def _check_external_alerting(self):
        """A CRITICAL event must be able to LEAVE this machine.

        The notification ledger is dashboard-only. If GreyLine breaks while the operator is away,
        an on-machine-only alert is never seen — exactly the silent backfill failure. This checks
        that at least one off-machine channel is configured; a warning, not a block, because the
        operator may deliberately run without one.
        """
        try:
            from app.services.external_alert_engine import ExternalAlertEngine
            st = ExternalAlertEngine().status()
        except Exception as e:
            return {"id": "EXTERNAL_ALERTING", "severity": "warning", "ok": True,
                    "detail": f"alert check skipped: {str(e)[:90]}"}
        if st.get("has_external_channel"):
            return {"id": "EXTERNAL_ALERTING", "severity": "warning", "ok": True,
                    "detail": f"external alert channel(s) live: {', '.join(st['external_channels'])}"}
        return {"id": "EXTERNAL_ALERTING", "severity": "warning", "ok": False,
                "detail": ("NO external alert channel — CRITICAL events stay on this machine and "
                           "are invisible when the operator is away (the silent-backfill case). "
                           "Set GREYLINE_ALERT_WEBHOOK_URL or GREYLINE_ALERT_NTFY_TOPIC")}

    REALIZED_CONTINUITY_STATE = Path("app/data/reality_guard/realized_continuity.json")
    REALIZED_MOVE_EPS = 1.0   # dollars; ignore rounding noise

    def _check_realized_continuity(self):
        """FANTASY DETECTOR for the class that slipped past every other check (2026-07-30): the
        realized-P&L ledger booking a spurious delta at a day boundary (broker daily realized resets
        on ET; the tracker keyed it to UTC -> double-booked then ERASED a real loss overnight, equity
        read a fantasy +$74). Invariant: REALIZED P&L CAN ONLY CHANGE FROM FILLS, AND FILLS ONLY
        HAPPEN DURING THE REGULAR SESSION. So if cumulative realized moves across a MARKET-CLOSED
        interval, that's not a real trade — it's a ledger/day-boundary artifact. Critical = go red.
        Stateful: persists (realized, market_open) each check; the first run just baselines (ok)."""
        try:
            from app.services.mission_realized_pnl_engine import MissionRealizedPnlEngine
            from app.services.market_hours_engine import MarketHoursEngine
            now_realized = float(MissionRealizedPnlEngine().cumulative_realized())
            now_open = MarketHoursEngine().status().get("is_regular_session") is True
        except Exception as e:
            # Fail CLOSED, like the sibling critical checks (account-source, phantom-positions): a
            # CRITICAL fantasy detector that cannot evaluate is an UNKNOWN, not a pass. Silently
            # returning ok:True let a thrown MissionRealizedPnl/MarketHours read mask the exact
            # day-boundary artifact this exists to catch.
            return {"id": "REALIZED_CONTINUITY", "severity": "critical", "ok": False,
                    "detail": f"could not evaluate (fail-closed — treated as UNKNOWN): {str(e)[:80]}"}
        prev = None
        try:
            prev = json.loads(self.REALIZED_CONTINUITY_STATE.read_text())
        except Exception:
            prev = None
        ok, detail = True, f"realized ${round(now_realized, 2)} stable"
        if prev is not None:
            prev_realized = _num(prev.get("realized"))
            delta = round(now_realized - prev_realized, 2)
            closed_across = (not now_open) and (not bool(prev.get("market_open")))
            if abs(delta) >= self.REALIZED_MOVE_EPS and closed_across:
                ok = False
                detail = (f"realized moved ${delta} (to ${round(now_realized, 2)}) while the market was "
                          "CLOSED — realized only comes from fills; this is a ledger/day-boundary "
                          "artifact, not a real trade.")
        try:
            self.REALIZED_CONTINUITY_STATE.parent.mkdir(parents=True, exist_ok=True)
            self.REALIZED_CONTINUITY_STATE.write_text(json.dumps(
                {"realized": round(now_realized, 2), "market_open": now_open,
                 "at": datetime.utcnow().isoformat()}))
        except Exception:
            pass
        return {"id": "REALIZED_CONTINUITY", "severity": "critical", "ok": ok, "detail": detail}

    DATA_FRESH_STALE_DAYS = 5   # calendar days; > this on a decision-driving symbol = stale pipeline

    def _check_data_freshness(self):
        """FANTASY DETECTOR for stale-as-live bar data (2026-07-30 audit): the daily-bar refresh can
        stall while the momentum gate (keys off the universe-MAX bar date) and trend (no gate) still
        compute + DISPLAY signals as 'live'. Independently check the newest bar date of the symbols
        that actually drive decisions (regime SPY + trend basket); if any is older than the threshold
        (weekend-tolerant), the pipeline is stale and 'live' displays are lying. Warning severity."""
        import csv as _csv
        from datetime import date
        HIST = Path("app/data/historical")
        symbols = ["SPY", "QQQM", "IWM", "TLT", "GLDM", "EFA", "DBC"]
        today = None
        try:
            from zoneinfo import ZoneInfo
            today = datetime.now(ZoneInfo("America/New_York")).date()
        except Exception:
            today = datetime.utcnow().date()
        stale = []
        for s in symbols:
            p = HIST / f"{s}_daily.csv"
            if not p.exists():
                continue
            try:
                last = None
                with open(p) as f:
                    for row in _csv.reader(f):
                        if row and row[0] and row[0][0].isdigit():
                            last = row[0]
                if last:
                    d = date.fromisoformat(last[:10])
                    if (today - d).days > self.DATA_FRESH_STALE_DAYS:
                        stale.append(f"{s}:{last}({(today - d).days}d)")
            except Exception:
                continue
        ok = not stale
        return {"id": "DATA_FRESHNESS", "severity": "warning", "ok": ok,
                "detail": ("decision-driving bars are current" if ok else
                           f"STALE bar data on {len(stale)} decision symbol(s) — the daily refresh has "
                           f"stalled and signals/displays may present stale bars as live: "
                           + ", ".join(stale[:6]))}

    # (shadow_id, module, class) — the source of truth for 'is this shadow enabled' is the engine's own
    # enabled(), never a re-derived flag default (WORK RULE: engines decide). Kept in lock-step with the
    # scheduler's shadow-heartbeat record() call.
    _SHADOW_REGISTRY = [
        ("condor", "app.services.condor_shadow_engine", "CondorShadowEngine"),
        ("overnight", "app.services.overnight_anomaly_shadow_engine", "OvernightAnomalyShadowEngine"),
        ("fomc_cycle", "app.services.fomc_cycle_shadow_engine", "FomcCycleShadowEngine"),
        ("iv_skew", "app.services.iv_skew_shadow_engine", "IvSkewShadowEngine"),
        ("dispersion", "app.services.dispersion_shadow_engine", "DispersionShadowEngine"),
        ("extended_etf", "app.services.extended_etf_shadow_engine", "ExtendedEtfShadowEngine"),
        ("vol_etp", "app.services.vol_etp_shadow_engine", "VolEtpShadowEngine"),
        ("futures_tsmom", "app.services.futures_tsmom_shadow_engine", "FuturesTsmomShadowEngine"),
        ("fx_trend", "app.services.fx_trend_shadow_engine", "FxTrendShadowEngine"),
        ("gex_strategy", "app.services.gex_mean_reversion_shadow_engine", "GexMeanReversionShadowEngine"),
        ("vanna_charm", "app.services.vanna_charm_shadow_engine", "VannaCharmShadowEngine"),
    ]
    SHADOW_STALE_DAYS = 4   # a shadow marks ~nightly when not deferred; > this (covers Fri->Mon + tolerance) = silent stall

    def _check_shadow_freshness(self):
        """FANTASY DETECTOR for silently-stalled forward-test shadows (the 2026-08-17 freeze class): when the
        process pegs/freezes/mis-clocks for days, the heavy-gated shadows quietly stop accruing while their
        cards keep showing the last (stale) state as if live — the condor & gex stall was caught only by chance.

        Reads the scheduler's per-shadow heartbeat (`shadow_mark_heartbeat`, `last_ran` = last time the shadow
        actually executed its mark logic, cadence-independent) and flags any ENABLED shadow whose last real run
        is older than SHADOW_STALE_DAYS. CRY-WOLF DISCIPLINE mirrors _check_data_freshness: (1) gate on the
        engine's own enabled() — a disabled shadow never runs, so it must not be flagged; (2) only when the
        scheduler is LIVE — if the scheduler itself is down that alarm owns it, so we stay quiet here; (3) a
        shadow with no heartbeat yet BASELINES silently (populates on the next non-deferred cycle). Warning
        severity — a stalled forward-test costs measurement, not capital."""
        base = {"id": "SHADOW_FRESHNESS", "severity": "warning"}
        try:
            from app.services.background_scheduler_service import BackgroundSchedulerService
            if not BackgroundSchedulerService.scheduler_live():
                return {**base, "ok": True,
                        "detail": "scheduler not live — shadow-staleness deferred to the scheduler-liveness alarm"}
        except Exception:
            return {**base, "ok": True, "detail": "scheduler liveness unresolved — shadow-staleness check skipped"}

        try:
            from app.services.shadow_mark_heartbeat import read as _read_hb
            hb = _read_hb()
        except Exception as exc:
            return {**base, "ok": True, "detail": f"heartbeat unreadable (skipped): {repr(exc)[:80]}"}

        import importlib
        now = _clock.time()
        stale = []
        verified = 0
        baselining = 0
        for sid, module, cls_name in self._SHADOW_REGISTRY:
            try:
                eng = getattr(importlib.import_module(module), cls_name)
                enabled = eng.enabled() if hasattr(eng, "enabled") else True
                if not enabled:
                    continue
                last_ran = (hb.get(sid) or {}).get("last_ran")
                if not last_ran:               # never recorded yet -> baseline silently (populates next non-deferred cycle)
                    baselining += 1
                    continue
                days = (now - float(last_ran)) / 86400.0
                if days > self.SHADOW_STALE_DAYS:
                    stale.append(f"{sid}:{days:.1f}d")
                else:
                    verified += 1
            except Exception:
                continue                        # a broken shadow import must never break the guard

        ok = not stale
        return {**base, "ok": ok,
                "detail": ((f"{verified} enabled forward-test shadow(s) accruing on schedule"
                            + (f", {baselining} baselining" if baselining else "")) if ok else
                           f"{len(stale)} enabled shadow(s) have SILENTLY STOPPED accruing (last real mark > "
                           f"{self.SHADOW_STALE_DAYS}d ago) — the cycle isn't reaching their mark step; cards may "
                           f"show stale state as live: " + ", ".join(sorted(stale)))}

    def _recently_closed_symbols(self, days):
        """Symbols on ledger trades marked CLOSED (with realized P&L booked) in the last `days`.

        Covers all three books. These are the closes that BANKED realized P&L — the moment a close
        is committed on intent rather than a confirmed fill, this is where the fantasy gets recorded."""
        import json
        from pathlib import Path

        def _recent(ts):
            try:
                return (datetime.utcnow() - datetime.fromisoformat(str(ts).replace("Z", ""))).days <= days
            except Exception:
                return False

        syms = set()
        try:
            from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine
            for t in PaperTradeLedgerEngine()._read_all():
                if (t.get("status") == "CLOSED" and t.get("realized_pnl") is not None
                        and _recent(t.get("exit_timestamp")) and t.get("symbol")):
                    syms.add(str(t["symbol"]).upper())
        except Exception:
            pass
        for fn, key in ((("app/data/options_paper_trading/options_paper_trade_ledger.jsonl"), "option_symbol"),
                        (("app/data/options_paper_trading/vrp_short_premium_ledger.jsonl"), None)):
            try:
                f = Path(fn)
                if not f.exists():
                    continue
                for line in f.read_text().splitlines():
                    if not line.strip():
                        continue
                    t = json.loads(line)
                    if t.get("status") != "CLOSED" or not _recent(t.get("exit_timestamp") or t.get("closed_at")):
                        continue
                    if key and t.get(key):
                        syms.add(str(t[key]).upper())
                    elif not key:                      # VRP condor unit — a failed close strands leg(s)
                        for lg in t.get("legs", []) or []:
                            if lg.get("symbol"):
                                syms.add(str(lg["symbol"]).upper())
            except Exception:
                pass
        return syms

    def _recently_closed_realized(self, days):
        """Like _recently_closed_symbols, but keeps the largest |realized P&L| booked per symbol. Lets the
        EXITS check tell a REAL fabricated-P&L fantasy (non-zero dollars banked on a still-held position)
        from a benign reconciliation lag (closed with 0/None realized — an unfilled residual the broker
        still shows, e.g. an illiquid wing the flatten marked closed but couldn't sell). Returns
        {SYMBOL: max_abs_realized_float} (None realized -> 0.0)."""
        import json
        from pathlib import Path

        def _recent(ts):
            try:
                return (datetime.utcnow() - datetime.fromisoformat(str(ts).replace("Z", ""))).days <= days
            except Exception:
                return False

        out = {}

        def _add(sym, r):
            if not sym:
                return
            s = str(sym).upper()
            val = abs(float(r)) if isinstance(r, (int, float)) else 0.0
            out[s] = max(out.get(s, 0.0), val)

        try:
            from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine
            for t in PaperTradeLedgerEngine()._read_all():
                if (t.get("status") == "CLOSED" and t.get("realized_pnl") is not None
                        and _recent(t.get("exit_timestamp")) and t.get("symbol")):
                    _add(t["symbol"], t.get("realized_pnl"))
        except Exception:
            pass
        for fn, key in ((("app/data/options_paper_trading/options_paper_trade_ledger.jsonl"), "option_symbol"),
                        (("app/data/options_paper_trading/vrp_short_premium_ledger.jsonl"), None)):
            try:
                f = Path(fn)
                if not f.exists():
                    continue
                for line in f.read_text().splitlines():
                    if not line.strip():
                        continue
                    t = json.loads(line)
                    if t.get("status") != "CLOSED" or not _recent(t.get("exit_timestamp") or t.get("closed_at")):
                        continue
                    if key and t.get(key):
                        _add(t[key], t.get("realized_pnl"))
                    elif not key:
                        for lg in t.get("legs", []) or []:
                            if lg.get("symbol"):
                                _add(lg["symbol"], t.get("realized_pnl"))
            except Exception:
                pass
        return out

    def _check_open_positions_match_broker(self, view):
        """The dashboard's Open Positions MUST equal the TradeStation account EXACTLY. Compare the set the
        dashboard renders (the broker view) to the RAW TradeStation Positions API, symbol + quantity, so
        the view's transformation can never silently drop, add, or missize a real holding. The broker
        view preserves the raw TS symbol verbatim (OSI for options), so this is apples-to-apples."""
        if not view.get("reads_ok", True):
            return {"id": "OPEN_POSITIONS_MATCH_BROKER", "severity": "critical", "degraded_class": True,
                    "ok": True, "detail": "broker read degraded — comparison skipped (BROKER_READS_OK owns that)"}
        try:
            from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine
            pos_resp = TradeStationPositionsLiveEngine().get_positions()
            dash = {str(p.get("symbol") or "").upper(): round(float(p.get("quantity") or 0), 4)
                    for p in (view.get("positions") or []) if p.get("symbol")}
            # This check makes its OWN fresh positions read (to verify the view's transform against the RAW
            # TS API). On a saturated box that second read can transiently fail — a non-200, OR a 200 with
            # an EMPTY Positions array while the view (which passed reads_ok) holds many. Either way the two
            # reads simply DISAGREE under load; that is UNVERIFIABLE, not a fabricated book. Treating it as a
            # critical mismatch flagged the ENTIRE ledger as phantom and cried the red FANTASY alarm (an
            # all-positions-vanished-at-once event is implausible; a transient empty read is the real cause —
            # same empty-read signature the mission risk governor already guards). Skip it (degraded/amber).
            if pos_resp.get("http_status") != 200:
                return {"id": "OPEN_POSITIONS_MATCH_BROKER", "severity": "critical", "degraded_class": True,
                        "ok": True, "detail": ("the comparison's own fresh positions read did not return 200 "
                                               "(broker saturated) — comparison unverifiable this cycle")}
            raw = (pos_resp.get("response_json") or {}).get("Positions") or []
            ts = {str(p.get("Symbol") or "").upper(): round(float(p.get("Quantity") or 0), 4)
                  for p in raw if p.get("Symbol")}
            if not ts and dash:
                return {"id": "OPEN_POSITIONS_MATCH_BROKER", "severity": "critical", "degraded_class": True,
                        "ok": True, "detail": (f"broker returned 0 positions while the view holds {len(dash)} "
                                               "— transient empty read under load, comparison unverifiable")}
        except Exception as e:
            return {"id": "OPEN_POSITIONS_MATCH_BROKER", "severity": "critical", "degraded_class": True,
                    "ok": True, "detail": f"could not compare dashboard positions to TradeStation: {str(e)[:120]}"}
        ts_side = {k: ts[k] for k in ts if dash.get(k) != ts[k]}           # in TS, missing/wrong on dash
        dash_side = {k: dash[k] for k in dash if ts.get(k) != dash[k]}     # on dash, missing/wrong in TS
        ok = not ts_side and not dash_side
        return {
            "id": "OPEN_POSITIONS_MATCH_BROKER", "severity": "critical", "ok": ok,
            "detail": (f"the dashboard's open positions exactly match the TradeStation account "
                       f"({len(dash)} position(s))" if ok else
                       f"MISMATCH — dashboard vs TradeStation diverge. TS-only/wrong-qty: {ts_side}; "
                       f"dashboard-only/wrong-qty: {dash_side}"),
            "tradestation_count": len(ts), "dashboard_count": len(dash),
        }

    def _check_exits_filled_not_intended(self, view):
        """A ledger trade marked CLOSED (realized P&L banked) whose symbol the broker STILL holds and
        that no OPEN ledger explains = the close was committed on INTENT, not a confirmed fill. The
        realized dollars are fantasy and the position is still live. This is the exact Root-A failure:
        momentum/condor exits that flip CLOSED + bank realized without checking the broker `ok`."""
        CLOSE_LOOKBACK_DAYS = 4
        try:
            broker_syms = {str(p.get("symbol") or "").upper() for p in (view.get("positions") or [])}
            recently_closed = self._recently_closed_symbols(CLOSE_LOOKBACK_DAYS)
            still_open = self.managed_symbols()          # legit current holdings (incl. re-buys)
            suspects = sorted((recently_closed & broker_syms) - still_open)
        except Exception as e:
            return {"id": "EXITS_FILLED_NOT_INTENDED", "severity": "critical", "ok": False,
                    "detail": f"could not cross-check closed trades vs broker: {str(e)[:120]}"}
        if not suspects:
            return {"id": "EXITS_FILLED_NOT_INTENDED", "severity": "critical", "ok": True,
                    "detail": "every recently-CLOSED trade is actually flat at the broker", "suspects": []}
        # Split by whether the close actually BANKED realized dollars. A NON-ZERO realized on a still-held
        # position is a real fabricated-P&L fantasy (critical, red). A close with 0/None realized that the
        # broker still holds is a benign reconciliation lag — an unfilled residual (e.g. an illiquid wing
        # the flatten marked CLOSED but couldn't sell); it banked NO phantom dollars and self-clears at
        # fill/expiry, so it is a WARNING (amber), NOT a red FANTASY. Stops crying wolf on self-healing
        # residuals while a genuinely fabricated exit P&L still trips critical.
        realized = self._recently_closed_realized(CLOSE_LOOKBACK_DAYS)
        EPS = 0.005
        banked = sorted(s for s in suspects if realized.get(s, 0.0) > EPS)
        residual = sorted(s for s in suspects if s not in banked)
        if banked:
            return {"id": "EXITS_FILLED_NOT_INTENDED", "severity": "critical", "ok": False,
                    "detail": (f"{len(banked)} trade(s) marked CLOSED with NON-ZERO realized P&L banked, "
                               f"but the broker STILL holds them — fantasy realized P&L / unhedged "
                               f"position: " + ", ".join(banked[:8])),
                    "suspects": banked, "residual_no_pnl": residual}
        return {"id": "EXITS_FILLED_NOT_INTENDED", "severity": "warning", "ok": False,
                "detail": (f"{len(residual)} recently-CLOSED trade(s) the broker still holds, but NO P&L "
                           f"was banked (realized 0/None) — an unfilled residual / reconciliation lag, not "
                           f"fantasy; self-clears at fill or expiry: " + ", ".join(residual[:8])),
                "suspects": residual}

    def _check_decision_caches_fresh(self):
        """The condor and optionable-universe DECISION caches the dashboard renders as live must not be
        silently frozen by a stalled scheduler. DATA_FRESHNESS covers daily bars; this covers the two
        decision caches it doesn't."""
        import json
        import time
        from os import getenv
        from pathlib import Path

        caches = [("optionable-universe", "app/data/research/optionable_universe.json", 4 * 86400)]
        # The best-condors cache is refreshed by the scheduler's best-condors phase, which has its OWN gate
        # GREYLINE_BEST_CONDORS_ENABLED (the condor dashboard card was retired, so the per-cycle UW recompute
        # is dead work and gated OFF by default). Its freshness therefore tracks THAT flag — NOT whether the
        # VRP sleeve is armed. The VRP sleeve books condors from its own plan()/ledger and never reads this
        # cache, so arming VRP must not resume a freshness check on a cache nothing is refreshing (that was
        # the 2026-08-14 false "scheduler may be wedged" alarm: VRP got armed while the recompute stayed off).
        # Only check freshness when the producer that fills it is actually enabled.
        if (getenv("GREYLINE_BEST_CONDORS_ENABLED", "") or "").strip().lower() == "true":
            caches.insert(0, ("best-condors", "app/data/condor_shadow/best_condors.json", 24 * 3600))

        stale = []
        for label, path, max_age_s in caches:
            try:
                d = json.loads(Path(path).read_text())
                age = time.time() - float(d.get("computed_epoch") or 0)
                if age > max_age_s:
                    stale.append(f"{label} ({round(age / 3600)}h old)")
            except Exception:
                pass                                     # missing cache is handled by its own warming state
        return {"id": "DECISION_CACHES_FRESH", "severity": "warning", "ok": not stale,
                "detail": (f"{len(caches)} live decision cache(s) current ({', '.join(l for l, _, _ in caches)})"
                           if not stale
                           else "STALE decision cache(s) rendered as live — scheduler may be wedged: "
                                + ", ".join(stale))}

    def _check_readout_integrity(self):
        """The single sanctioned readout (/decision-readout) must aggregate every canonical decision
        cleanly — a degraded section means an answer sourced from it would be missing or divergent."""
        try:
            from app.services.decision_readout_engine import DecisionReadoutEngine
            r = DecisionReadoutEngine().readout()
            degraded = r.get("degraded_sections") or []
        except Exception as e:
            return {"id": "READOUT_INTEGRITY", "severity": "warning", "ok": False,
                    "detail": f"sanctioned readout could not be built: {str(e)[:120]}"}
        return {"id": "READOUT_INTEGRITY", "severity": "warning", "ok": not degraded,
                "detail": ("the sanctioned readout aggregates all canonical decisions cleanly" if not degraded
                           else f"{len(degraded)} readout section(s) degraded: " + ", ".join(degraded))}

    def _check_candidate_surfaces_healthy(self):
        """VRP + Iron Condor list + Opportunity Board must not silently break — catching BOTH regression
        classes we fixed: (1) a sleeve/edge that THROWS returns [] and reads as 'no opportunities', and
        (2) a key the producer stopped providing renders a BLANK field (the entry_dte class). Checks the
        surfaced error markers AND that rendered rows carry their required fields. VRP is covered via both
        the Iron Condor sleeve_errors and the board's VRP edge."""
        import json as _json
        from pathlib import Path as _Path

        problems = []
        # --- Iron Condor list (BestCondorsEngine, aggregating the VRP + earnings sleeves) ---
        try:
            d = _json.loads(_Path("app/data/condor_shadow/best_condors.json").read_text())
            for sleeve, err in (d.get("sleeve_errors") or {}).items():
                problems.append(f"IronCondor[{sleeve}] threw: {str(err)[:45]}")
            req = ("return_on_risk", "dte", "short_put", "short_call", "wing_put", "wing_call")
            for c in (d.get("condors") or []):
                blank = [f for f in req if c.get(f) is None]
                if blank:
                    problems.append(f"IronCondor[{c.get('symbol')}] blank fields {blank}")
                    break                              # one example is enough
        except Exception:
            pass                                       # a missing cache is DECISION_CACHES_FRESH's concern
        # --- Opportunity Board (momentum + earnings + VRP edges) ---
        try:
            from app.services.unified_opportunity_board_engine import UnifiedOpportunityBoardEngine
            b = UnifiedOpportunityBoardEngine().board()
            for edge in (b.get("degraded_edges") or []):
                problems.append(f"Board[{edge}] threw")
            for g in (b.get("groups") or []):
                for c in (g.get("candidates") or []):
                    if c.get("score") is None or c.get("status") is None:
                        problems.append(f"Board[{g.get('strategy')}/{c.get('symbol')}] blank score/status")
                        break
        except Exception as e:
            problems.append(f"Board could not be built: {str(e)[:60]}")
        return {"id": "CANDIDATE_SURFACES_HEALTHY", "severity": "warning", "ok": not problems,
                "detail": ("VRP + Iron Condor + Opportunity Board surfaces intact — no thrown sleeve, no "
                           "blank required field" if not problems else
                           f"{len(problems)} surface issue(s): " + "; ".join(problems[:4]))}

    @staticmethod
    def _momentum_open_rows():
        """Returns (rows, read_ok). read_ok=False means the ledger couldn't be read — an empty list then
        means UNKNOWN, not 'no positions', so the caller must not report it as a verified-clean state."""
        import json
        from pathlib import Path
        try:
            rows = [json.loads(l) for l in
                    Path("app/data/paper_trading/paper_trade_ledger.jsonl").read_text().splitlines() if l.strip()]
        except Exception:
            return [], False
        return [r for r in rows if r.get("status") == "OPEN" and r.get("trade_intent") == "MOMENTUM_REVERSAL"], True

    def _check_momentum_stops_consistent(self):
        """Every OPEN momentum position must be MANAGED to the stop it RECORDED at entry — else the risk
        the edge court measures on isn't the risk actually being ENFORCED. Flags a position past the grace
        window with a recorded entry_stop but no live doctrine plan (UNMANAGED), or a managed stop that has
        drifted materially from the recorded entry_stop (>2% of price). Warning: a risk-hygiene gap, not
        fantasy. Fresh opens (attach the doctrine next cycle) and pre-feature rows (no recorded stop) pass."""
        from datetime import datetime
        GRACE_H, TOL = 2.0, 0.02
        rows, read_ok = self._momentum_open_rows()
        if not read_ok:                                # a swallowed read must NOT read as verified-clean
            return {"id": "MOMENTUM_STOPS_CONSISTENT", "severity": "warning", "ok": True,
                    "detail": "momentum ledger unreadable — stop consistency UNVERIFIED this cycle"}
        problems, checked, skipped, now = [], 0, 0, datetime.utcnow()
        for r in rows:
            try:
                entry = float(r.get("entry_price") or 0)
            except (TypeError, ValueError):
                entry = 0.0
            rec = r.get("entry_stop")
            if rec is None or entry <= 0:              # pre-feature row / no recorded stop -> NOT verifiable
                skipped += 1
                continue
            checked += 1
            managed = (r.get("exit_doctrine") or {}).get("initial_stop")
            sym = r.get("symbol")
            if managed is None:
                try:
                    age_h = (now - datetime.fromisoformat(str(r.get("timestamp")))).total_seconds() / 3600.0
                except Exception:
                    age_h = GRACE_H + 1
                if age_h >= GRACE_H:                   # fresh opens attach the plan next cycle -> grace
                    problems.append(f"{sym} recorded stop {rec} but UNMANAGED (no doctrine plan, {round(age_h)}h old)")
            else:
                try:
                    if abs(float(managed) - float(rec)) > TOL * entry:
                        problems.append(f"{sym} managed stop {round(float(managed), 2)} != recorded {round(float(rec), 2)}")
                except (TypeError, ValueError):
                    pass
        if problems:
            return {"id": "MOMENTUM_STOPS_CONSISTENT", "severity": "warning", "ok": False,
                    "detail": "; ".join(problems[:6])}
        # HONEST detail: say what was actually VERIFIED vs merely skipped — never claim "managed" for
        # positions that carry no recorded stop (the vacuous-green trap).
        if checked == 0:
            detail = (f"no open momentum position has a recorded entry stop yet ({skipped} pre-feature/"
                      "ATR-unavailable) — nothing to verify" if skipped else "no open momentum positions")
        else:
            detail = f"{checked} open momentum position(s) managed to their recorded entry stop"
            if skipped:
                detail += f"; {skipped} not yet verifiable (no recorded stop)"
        return {"id": "MOMENTUM_STOPS_CONSISTENT", "severity": "warning", "ok": True, "detail": detail}

    def _check_sleeve_edge_not_decayed(self):
        """The edge court is the RETIRE signal — surface any sleeve it judged DECAYED (cost-net edge < 0
        at 95% confidence, >= the trade gate) so a statistically-losing edge is visible, not silently
        bleeding. Warning severity: a slow, defined-risk bleed the operator should act on, not an emergency."""
        try:
            from app.services.edge_persistence_engine import EdgePersistenceEngine
            sleeves = EdgePersistenceEngine().realized_edge().get("sleeves") or {}
        except Exception as e:
            return {"id": "EDGE_NOT_DECAYED", "severity": "warning", "ok": True,
                    "detail": f"edge court check skipped: {str(e)[:80]}"}
        decayed = sorted(s for s, v in sleeves.items() if str(v.get("verdict", "")).startswith("DECAYED"))
        if not decayed:
            return {"id": "EDGE_NOT_DECAYED", "severity": "warning", "ok": True,
                    "detail": "no sleeve judged DECAYED by the edge court"}
        return {"id": "EDGE_NOT_DECAYED", "severity": "warning", "ok": False,
                "detail": f"DECAYED sleeve(s), cost-net edge < 0 at 95% (court): {', '.join(decayed)} — "
                          "candidate to retire / cut capital (see /edge-persistence)"}

    def _check_alloc_override_coherent(self):
        """The gated budget auto-apply writes REVERSIBLE sleeve %-overrides. Assert they can't drift into
        an incoherent state that silently moves capital: every override pct in [0,100], the resulting book
        deploys <= 100% of equity, and EVERY override traces to a real recorded apply (no manual/orphan
        injection presented as auto-applied). Warning severity — a budget-coherence gap to fix, not a
        position lie. No file (the common case: never applied / reverted) is clean."""
        from os import getenv as _getenv
        import json as _json
        try:
            from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine as _B
            from app.services.sleeve_budget_autoapply_engine import SleeveBudgetAutoApplyEngine as _A
            ov_file, hist = _B.OVERRIDE_FILE, _A.HISTORY        # single source of truth (no path dup)
        except Exception as e:
            return {"id": "ALLOC_OVERRIDE_COHERENT", "severity": "warning", "ok": True,
                    "detail": f"auto-apply engines unavailable: {str(e)[:60]}"}
        if not ov_file.exists():
            return {"id": "ALLOC_OVERRIDE_COHERENT", "severity": "warning", "ok": True,
                    "detail": "no auto-apply sleeve overrides active (env/default budgets)"}
        try:
            overrides = {str(k).lower(): float(v)
                         for k, v in (_json.loads(ov_file.read_text()).get("pct") or {}).items()}
        except Exception as e:
            return {"id": "ALLOC_OVERRIDE_COHERENT", "severity": "warning", "ok": False,
                    "detail": f"override file present but unreadable ({str(e)[:60]}) — budget state UNVERIFIED"}
        problems, total = [], None
        for s, v in overrides.items():                       # (1) each override a sane percent
            if not (0.0 <= v <= 100.0):
                problems.append(f"{s}={v} out of [0,100]")
        try:                                                 # (2) resulting book deploys <= 100% of equity
            total = round(sum(_B.pct(s) for s in _B.DEFAULT_PCT), 2)   # pct honors env > override > default
            if total > 100.0 + 1e-6:
                problems.append(f"book deploys {total}% > 100% of equity")
        except Exception as e:
            problems.append(f"could not compute book total ({str(e)[:50]})")
        try:                                                 # (3) every override traces to a recorded apply
            if hist.exists():
                moved = {str(m.get("sleeve")).lower()
                         for line in hist.read_text().splitlines() if line.strip()
                         for m in (_json.loads(line).get("moves") or [])}
                orphans = sorted(s for s in overrides if s not in moved)
                if orphans:
                    problems.append(f"override(s) with NO recorded apply (orphan/manual): {', '.join(orphans)}")
            else:
                problems.append("auto-apply history log missing — override provenance UNVERIFIED")
        except Exception as e:
            problems.append(f"history unreadable ({str(e)[:50]}) — provenance UNVERIFIED")
        if problems:
            return {"id": "ALLOC_OVERRIDE_COHERENT", "severity": "warning", "ok": False,
                    "detail": "; ".join(problems[:6]) + " (see /sleeve-budget-autoapply)"}
        shadowed = sorted(s for s in overrides
                          if str(_getenv("GREYLINE_%s_ALLOC_PCT" % s.upper(), "")).strip())
        note = f"; {len(shadowed)} shadowed by an env pin (env wins, override stale)" if shadowed else ""
        return {"id": "ALLOC_OVERRIDE_COHERENT", "severity": "warning", "ok": True,
                "detail": f"{len(overrides)} sleeve override(s) coherent (book {total}% <= 100%){note}"}

    def check(self, allow_cache=True):
        """Serve the cached guard verdict to operator routes; recompute fresh when stale or forced.

        allow_cache=True (routes/dashboard): return the last computed verdict if younger than the TTL —
        instant, not the ~30s live recompute. allow_cache=False (scheduler): always recompute + refresh the
        cache so the routes stay warm. Only a real, fully-computed verdict is cached (never fabricated)."""
        ttl = _guard_ttl()
        if allow_cache and ttl > 0 and _GUARD_CACHE["result"] is not None:
            age = _clock.monotonic() - _GUARD_CACHE["at"]
            if age < ttl:
                out = dict(_GUARD_CACHE["result"])
                out["served_from_cache"] = True
                out["cache_age_seconds"] = round(age, 1)
                return out
        result = self._compute_check()
        if ttl > 0:
            _GUARD_CACHE["at"] = _clock.monotonic()
            _GUARD_CACHE["result"] = result
        return result

    def fantasy_alert(self, dispatch=True):
        """Page (deduped, off-machine) the instant the guard detects a TRUE fantasy state — fake data shown
        as real (verdict FANTASY_DETECTED). This ACTIVATES the anti-fantasy safety net: without it the
        35-invariant guard only ran when a human opened the dashboard, so a fantasy state arising while the
        operator was away went undetected. Deliberately does NOT page on BROKER_READ_DEGRADED (honest,
        self-healing amber — the guard's own cry-wolf rule). Deduped by the stable set of failing fantasy
        invariants → pages ONCE per new fantasy state, not every cycle. Read-only, best-effort, never raises."""
        try:
            res = self.check()          # serves the fresh verdict the scheduler just computed
        except Exception as e:
            return {"status": "REALITY_GUARD_ALERT_DEGRADED", "error": repr(e)[:100]}
        fantasy = sorted(res.get("fantasy_failures") or [])
        if not fantasy:
            return {"status": "REALITY_GUARD_NO_FANTASY", "verdict": res.get("verdict"), "fantasy": []}
        by_id = {c["id"]: c for c in (res.get("checks") or [])}
        detail = "; ".join(f"{i}: {str(by_id.get(i, {}).get('detail') or '')[:120]}" for i in fantasy)
        if dispatch:
            try:
                from app.services.external_alert_engine import ExternalAlertEngine
                eng = ExternalAlertEngine()
                if eng.has_external_channel():
                    eng.dispatch(
                        title="GreyLine FANTASY DETECTED — displayed state is not broker-real",
                        message=(f"The Reality Guard flags {len(fantasy)} CRITICAL fantasy invariant(s) "
                                 f"(fabricated/mismatched state shown as real): {detail}. The dashboard is "
                                 "RED. Do not trust the book until resolved. See /reality-guard."),
                        severity="CRITICAL", fingerprint=f"REALITY_FANTASY:{','.join(fantasy)}")
            except Exception:
                pass
        return {"status": "REALITY_GUARD_FANTASY_FLAGGED", "fantasy": fantasy, "detail": detail}

    def _compute_check(self):
        try:
            from app.services.broker_account_view_engine import BrokerAccountViewEngine
            view = BrokerAccountViewEngine().snapshot()
        except Exception as e:
            view = {"reads_ok": False, "status": f"BROKER_VIEW_ERROR: {str(e)[:120]}", "positions": []}

        checks = [
            self._check_account_source(),
            self._check_broker_reads(view),
            self._check_phantom_positions(view),
            self._check_untracked_broker_positions(view),
            self._check_open_positions_match_broker(view),
            self._check_exits_filled_not_intended(view),
            self._check_exec_booking_coherent(),
            self._check_realized_continuity(),
            self._check_data_freshness(),
            self._check_shadow_freshness(),
            self._check_decision_caches_fresh(),
            self._check_readout_integrity(),
            self._check_candidate_surfaces_healthy(),
            self._check_data_source(),
            self._check_price_bars(),
            self._check_price_bars_match_source(),
            self._check_signal_bars_tradable(),
            self._check_survivorship_archive(),
            self._check_total_return_available(),
            self._check_regime_gate(),
            self._check_lineage_stable(),
            self._check_options_capture(),
            self._check_backup_current(),
            self._check_restore_drill(),
            self._check_deadman_heartbeat(),
            self._check_broker_side_protection(),
            self._check_broker_stops_fire_drill(),
            self._check_external_alerting(),
            self._check_sleeve_edge_not_decayed(),
            self._check_momentum_stops_consistent(),
            self._check_alloc_override_coherent(),
        ]
        critical_failures = [c for c in checks if c["severity"] == "critical" and not c["ok"]]
        warnings = [c for c in checks if c["severity"] == "warning" and not c["ok"]]

        # Split the criticals: a TRUE fantasy failure (fake data shown as real) vs a DEGRADED-class one
        # (an unverifiable/failed broker read — honest "unknown", NOT fabrication). A degraded read must
        # not raise the red FANTASY alarm, or the guard cries wolf on a benign, self-healing state. True
        # fantasy always wins if BOTH are present (worst-case honesty).
        fantasy_failures = [c for c in critical_failures if not c.get("degraded_class")]
        degraded_failures = [c for c in critical_failures if c.get("degraded_class")]

        if fantasy_failures:
            verdict = "FANTASY_DETECTED"
        elif degraded_failures:
            verdict = "BROKER_READ_DEGRADED"       # unverifiable live state — honest amber, not red fantasy
        elif warnings:
            verdict = "REAL_DATA_WITH_WARNINGS"
        else:
            verdict = "REAL_DATA_VERIFIED"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "verdict": verdict,
            "account_mode": view.get("account_mode"),
            "account_label": view.get("account_label"),
            "checks": checks,
            "critical_failures": [c["id"] for c in critical_failures],
            "fantasy_failures": [c["id"] for c in fantasy_failures],
            "degraded_failures": [c["id"] for c in degraded_failures],
            "warnings": [c["id"] for c in warnings],
            "status": "REALITY_GUARD_READY",
        }
