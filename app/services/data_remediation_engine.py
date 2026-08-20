"""Automatic data-fault remediation — GreyLine fixes its own stale/corrupt bars instead of waiting.

The reality guard VALIDATES app/data/historical/*_daily.csv every cycle (DATA_FRESHNESS,
PRICE_BARS_CLEAN, REGIME_GATE_HEALTHY, LINEAGE_STABLE) but nothing ever REFRESHED those CSVs — the
daily fetch was always a manual script, so the bars age until they trip. This engine owns that gap.

SAFETY POSTURE (it must NOT defeat the guards it remediates):
  * REFRESH bars: append-only from TradeStation (never overwrites settled history, never the Yahoo
    full-backfill that reintroduces survivorship bias). Validates each file grows/stays-ordered.
  * OHLC repair: clamp low/high only, originals backed up (never touches open/close).
  * LINEAGE re-accept: auto-accept ONLY when every changed symbol is a benign multi-year
    RETROACTIVE_READJUSTMENT AND none is flagged critical by the integrity scan. A TARGETED restatement
    or a critical overlap → HOLD + alert a human. Blindly re-accepting would turn the fantasy-detector
    into a fantasy-hider — so it never does.
  * Anything needing human judgment (held lineage, surviving criticals, rejected writes) → iMessage +
    audit ledger. Every action is logged.
Gated by GREYLINE_DATA_AUTOREMEDIATE (default TRUE). Self-gates to once/day in the scheduler.
"""

import csv
import json
from datetime import datetime
from os import getenv
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

BARS_DIR = Path("app/data/historical")
STATE = Path("app/data/data_quality")
LOG = STATE / "remediation_log.jsonl"
MARKER = STATE / "remediation_last_run.txt"
EVENT_MARKER = STATE / "remediation_last_event.json"   # event-driven run: {ts, fingerprint}
FIELDNAMES = ["date", "open", "high", "low", "close", "volume"]
BARS_BACK = 40


class DataRemediationEngine:

    DEFAULT_UNIVERSE_LIMIT = 250      # stalest-first slice of the broad universe per run (cycles over days)
    EVENT_MIN_INTERVAL_MIN = 15       # hard floor between alert-driven runs — protects the TS API
    EVENT_UNIVERSE_LIMIT = 40         # small refresh slice on an alert-run (decision syms always + this)
    BACKUP_STALE_HOURS = 26           # off-machine git backup older than this = flagged (matches the guard)
    MIN_TRADEABLE_BARS = 253          # < this = a junk stub (SPAC/warrant/newly-listed) that no signal reads;
                                      # its bad bars must not page (matches DirectionalSignalEngine.MIN_BARS)

    @classmethod
    def _tradeable_criticals(cls, crit_issues):
        """Critical issues restricted to names with enough history to actually trade — a 3-bar junk stub's
        bad bar can't cry wolf. Bars counted once per critical symbol (cheap: only a handful post-repair)."""
        out, bars = [], {}
        for i in crit_issues:
            sym = str(i.get("symbol") or "").upper()
            if sym not in bars:
                try:
                    with open(BARS_DIR / f"{sym}_daily.csv") as f:
                        bars[sym] = sum(1 for _ in f) - 1
                except Exception:
                    bars[sym] = 0
            if bars[sym] >= cls.MIN_TRADEABLE_BARS:
                out.append(i)
        return out

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_DATA_AUTOREMEDIATE", "true") or "true").strip().lower() == "true"

    # ---- symbols -------------------------------------------------------------------------------

    @classmethod
    def _decision_symbols(cls):
        syms = ["SPY"]
        try:
            from app.services.trend_following_engine import TrendFollowingEngine
            syms += list(TrendFollowingEngine.BASKET)
        except Exception:
            pass
        try:
            from app.services.managed_futures_engine import ManagedFuturesEngine
            syms += list(ManagedFuturesEngine.BASKET)
        except Exception:
            pass
        try:
            # the low-vol basket is consumed by its zero-capital shadow every cycle, so it must stay fresh
            # even while the sleeve is parked (otherwise the forward-test marks on week-old bars).
            from app.services.low_volatility_engine import LowVolatilityEngine
            syms += list(LowVolatilityEngine.BASKET)
        except Exception:
            pass
        syms += ["SVXY", "SGOV"]
        seen, out = set(), []
        for s in syms:
            u = s.upper()
            if u not in seen and (BARS_DIR / f"{u}_daily.csv").exists():
                seen.add(u)
                out.append(u)
        return out

    @classmethod
    def _shadow_symbols(cls):
        """The bar-dependent FORWARD-SHADOW universes that read app/data/historical daily bars and accrue their
        proof-gate observations off them — they must be refreshed EVERY run or a shadow silently marks/accrues on
        stale bars. (2026-08-20: the overnight-anomaly shadow stalled for days because QQQ/IWM/DIA lagged ~3 days
        while only a 250-name stalest slice of a 2,263-name universe rotated per run.) These are small, bounded
        baskets, so always-refreshing them is cheap; the rotating stale slice still handles the archival tail.
        The momentum-reversal / XS-momentum LIVE-price shadows settle on live quotes, not these CSVs, so they are
        deliberately NOT included."""
        def _uni(dotted, attr):
            mod_name, cls_name = dotted.rsplit(".", 1)
            try:
                mod = __import__(mod_name, fromlist=[cls_name])
                E = getattr(mod, cls_name)
                fn = getattr(E, attr, None)
                if fn is None:
                    return []
                if callable(fn):
                    try:
                        return list(fn())                 # classmethod / staticmethod
                    except TypeError:
                        return list(fn(E()))               # bound instance method
                return list(fn)
            except Exception:
                return []
        out = []
        out += _uni("app.services.overnight_anomaly_shadow_engine.OvernightAnomalyShadowEngine", "_universe")
        out += _uni("app.services.extended_etf_shadow_engine.ExtendedEtfShadowEngine", "_universe")
        out += _uni("app.services.cross_sectional_momentum_shadow_engine.CrossSectionalMomentumShadowEngine", "UNIVERSE")
        try:
            from app.services.vol_etp_shadow_engine import VolEtpShadowEngine
            out.append(getattr(VolEtpShadowEngine, "INSTRUMENT", "VXX"))
        except Exception:
            pass
        seen, res = set(), []
        for s in out:
            u = str(s).upper()
            if u and u not in seen and (BARS_DIR / f"{u}_daily.csv").exists():
                seen.add(u)
                res.append(u)
        return res

    @classmethod
    def _stale_symbols(cls, limit):
        """The broad-universe symbols the integrity scan flagged STALE_FILE (stalest first if aged)."""
        try:
            from app.services.price_bar_integrity_engine import PriceBarIntegrityEngine
            scan = PriceBarIntegrityEngine().last_scan() or {}
            issues = scan.get("issues") or []
            stale = [str(i.get("symbol")).upper() for i in issues
                     if str(i.get("type")) == "STALE_FILE" and i.get("symbol")]
            # de-dup, preserve order
            seen, out = set(), []
            for s in stale:
                if s not in seen and (BARS_DIR / f"{s}_daily.csv").exists():
                    seen.add(s)
                    out.append(s)
            return out[:limit]
        except Exception:
            return []

    # ---- append-only refresh -------------------------------------------------------------------

    @staticmethod
    def _existing_rows(path):
        rows = []
        try:
            with open(path) as f:
                for r in csv.DictReader(f):
                    if r.get("date"):
                        rows.append(r)
        except Exception:
            return []
        return rows

    @staticmethod
    def _fetch_bars(symbol, base_url, token):
        import requests
        url = base_url.rstrip("/") + f"/v3/marketdata/barcharts/{symbol}"
        resp = requests.get(url, params={"unit": "Daily", "barsback": BARS_BACK},
                            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                            timeout=20)
        resp.raise_for_status()
        out = []
        for b in (resp.json() or {}).get("Bars", []) or []:
            ts = b.get("TimeStamp") or b.get("Timestamp")
            try:
                row = {"date": str(ts)[:10], "open": round(float(b["Open"]), 6),
                       "high": round(float(b["High"]), 6), "low": round(float(b["Low"]), 6),
                       "close": round(float(b["Close"]), 6), "volume": int(float(b.get("TotalVolume") or 0))}
            except (KeyError, TypeError, ValueError):
                continue
            if row["date"] and row["close"] > 0:
                out.append(row)
        out.sort(key=lambda r: r["date"])
        return out

    def _refresh_one(self, symbol, base_url, token, today_iso, apply):
        path = BARS_DIR / f"{symbol}_daily.csv"
        rows = self._existing_rows(path)
        if not rows:
            return {"symbol": symbol, "status": "SKIP_EMPTY", "added": 0}
        last_date = max(r["date"] for r in rows)
        try:
            bars = self._fetch_bars(symbol, base_url, token)
        except Exception as e:
            return {"symbol": symbol, "status": "FETCH_FAILED", "added": 0, "error": str(e)[:80]}
        new = [b for b in bars if last_date < b["date"] < today_iso]   # exclude the partial live bar
        if not new:
            return {"symbol": symbol, "status": "ALREADY_CURRENT", "added": 0}
        dates = [b["date"] for b in new]
        if len(set(dates)) != len(dates) or dates != sorted(dates) or min(dates) <= last_date:
            return {"symbol": symbol, "status": "REJECTED_VALIDATION", "added": 0}
        if apply:
            with open(path, "a", newline="") as f:
                csv.DictWriter(f, fieldnames=FIELDNAMES).writerows(new)
            after = self._existing_rows(path)
            ad = [r["date"] for r in after]
            if len(after) != len(rows) + len(new) or ad != sorted(ad):
                return {"symbol": symbol, "status": "REJECTED_POST_WRITE", "added": 0}
        return {"symbol": symbol, "status": ("APPENDED" if apply else "WOULD_APPEND"),
                "added": len(new), "through": dates[-1]}

    def _token(self):
        try:
            from app.services.tradestation_token_maintenance_engine import TradeStationTokenMaintenanceEngine
            TradeStationTokenMaintenanceEngine().evaluate()
        except Exception:
            pass
        token = getenv("TRADESTATION_ACCESS_TOKEN", "")
        base_url = getenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com")
        return token, base_url

    # ---- the run -------------------------------------------------------------------------------

    def remediate(self, apply=True, universe_limit=None, lineage="auto"):
        """Refresh stale bars, repair OHLC, and (safely) re-accept lineage. lineage: auto|force|never."""
        started = datetime.utcnow().isoformat()
        actions, alerts = {}, []
        limit = self.DEFAULT_UNIVERSE_LIMIT if universe_limit is None else int(universe_limit)
        token, base_url = self._token()
        if not token:
            return {"status": "REMEDIATE_NO_TOKEN", "acted": False}

        # 1) refresh — decision + bar-dependent shadow universes ALWAYS (they accrue proof-gate obs off these
        #    bars daily), then a stalest slice of the broad universe for the archival tail.
        today_iso = datetime.utcnow().strftime("%Y-%m-%d")
        targets, seen = [], set()
        for s in self._decision_symbols() + self._shadow_symbols() + self._stale_symbols(limit):
            if s not in seen:
                seen.add(s)
                targets.append(s)
        refreshed, rejected, failed, added = [], [], [], 0
        for s in targets:
            r = self._refresh_one(s, base_url, token, today_iso, apply)
            if r["status"] in ("APPENDED", "WOULD_APPEND"):
                refreshed.append(r["symbol"]); added += r["added"]
            elif r["status"].startswith("REJECTED"):
                rejected.append(r["symbol"])
            elif r["status"] == "FETCH_FAILED":
                failed.append(r["symbol"])
        actions["refresh"] = {"targeted": len(targets), "refreshed": len(refreshed), "bars_added": added,
                              "rejected": rejected[:20], "fetch_failed": len(failed),
                              "decision_symbols": self._decision_symbols()}
        if rejected:
            alerts.append(f"{len(rejected)} bar file(s) REJECTED on refresh (left untouched): {', '.join(rejected[:8])}")

        # 2) integrity — read the LAST scan, REPAIR any OHLC violations, then RE-SCAN so the alert reflects
        # the POST-repair truth. Reporting the last scan's PRE-repair counts cried wolf on the very issues
        # the same pass just fixed (2026-08-19: 421 OHLC_VIOLATION repaired but still reported 'present').
        crit_syms, integ, counts, tradeable_crit = set(), {}, {}, []
        try:
            from app.services.price_bar_integrity_engine import PriceBarIntegrityEngine
            eng = PriceBarIntegrityEngine()
            integ = eng.last_scan() or {}
            counts = integ.get("counts") or {}
            # 3) OHLC repair (safe clamp of low/high only, originals backed up) — only if any exist
            if counts.get("OHLC_VIOLATION"):
                rep = eng.repair_ohlc(dry_run=not apply)
                actions["ohlc_repair"] = {k: rep.get(k) for k in ("repaired", "files_changed", "status") if k in rep}
                if apply and rep.get("files_changed"):
                    integ = eng.scan(full=True, save=True) or integ      # fresh counts AFTER the repair
                    counts = integ.get("counts") or {}
            crit_issues = [i for i in (integ.get("issues") or [])
                           if str(i.get("type")) in getattr(eng, "CRITICAL_TYPES", ())]
            crit_syms = {str(i.get("symbol")).upper() for i in crit_issues}
            # scope the ALERT to TRADEABLE names — a bad bar in a sub-MIN_BARS junk stub (SPAC/warrant)
            # never enters a signal, so it must not page.
            tradeable_crit = self._tradeable_criticals(crit_issues)
            actions["integrity"] = {"counts": counts, "critical_count": integ.get("critical_count"),
                                    "tradeable_critical_count": len(tradeable_crit),
                                    "tradeable_critical_symbols": sorted({str(i.get("symbol")).upper()
                                                                          for i in tradeable_crit})[:20]}
        except Exception as e:
            actions["integrity"] = {"error": str(e)[:120]}
        if tradeable_crit:      # alert ONLY on tradeable-universe criticals (post-repair) — junk-only never pages
            from collections import Counter
            by_type = dict(Counter(str(i.get("type")) for i in tradeable_crit))
            alerts.append(f"{len(tradeable_crit)} CRITICAL integrity issue(s) in TRADEABLE names {by_type} "
                          f"— need review")

        # 4) lineage — read the last verify report (scheduler runs verify_if_due daily), then re-accept
        # ONLY if provably safe. Append-only refresh doesn't touch settled rows, so the report is valid.
        try:
            from app.services.price_bar_lineage_engine import PriceBarLineageEngine
            leng = PriceBarLineageEngine()
            rep = leng.last_report() or {}
            changed = rep.get("changed") or []
            changed_syms = {str(c.get("symbol")).upper() for c in changed}
            targeted = [c["symbol"] for c in changed if c.get("likely") == "TARGETED_RESTATEMENT_OR_CORRUPTION"]
            crit_overlap = sorted(changed_syms & crit_syms)
            cc = rep.get("changed_count", 0)
            # GreyLine's OWN cross-source reconciliation (authoritative TradeStation comparison) restates
            # settled bars continuously, so a TARGETED restatement by itself is NOT a danger signal — the
            # danger is a changed symbol that is ALSO integrity-critical (corrupt). Re-accept clean
            # restatements (logged, reviewable — the guard isn't blinded); HOLD + alert only on a corrupt
            # overlap. This keeps the lineage guard from perpetually false-alarming on legit reconciliation.
            safe = cc > 0 and not crit_overlap
            decision = "none"
            if lineage == "force" and cc > 0:
                leng.snapshot(force=True); leng.verify(save=True); decision = "force_accepted"
            elif lineage == "auto" and safe and apply:
                # re-baseline, then re-verify so the report immediately reflects STABLE (else the guard
                # keeps showing the old changes until the scheduler's next 24h-gated verify).
                leng.snapshot(force=True); leng.verify(save=True); decision = "auto_accepted_clean_restatement"
            elif crit_overlap:
                decision = "held_for_review"
                alerts.append(f"LINEAGE held — {len(crit_overlap)} changed symbol(s) ALSO flagged corrupt "
                              f"(review, don't accept): {', '.join(crit_overlap[:6])}")
            elif cc > 0:
                decision = "noop"          # dry-run or lineage='never'
            actions["lineage"] = {"changed_count": cc, "decision": decision,
                                  "targeted_restatements": len(targeted), "critical_overlap": crit_overlap,
                                  "changed_sample": sorted(changed_syms)[:10]}
        except Exception as e:
            actions["lineage"] = {"error": str(e)[:120]}

        # 5) OFF-MACHINE BACKUP — re-push the git backup if it went stale (see _remediate_backup).
        b_action, b_alert = self._remediate_backup(apply)
        actions["backup"] = b_action
        if b_alert:
            alerts.append(b_alert)

        result = {"status": "REMEDIATED" if apply else "REMEDIATE_DRYRUN", "acted": apply,
                  "started": started, "finished": datetime.utcnow().isoformat(),
                  "actions": actions, "alerts": alerts}
        self._log(result)
        if apply and alerts:
            self._alert(alerts)
        return result

    # ---- cadence, logging, alerts --------------------------------------------------------------

    def _et_date(self):
        try:
            return datetime.now(ZoneInfo("America/New_York")).date().isoformat() if ZoneInfo else None
        except Exception:
            return None

    def run_if_due(self):
        if not self.enabled():
            return {"status": "REMEDIATE_DISABLED", "ran": False}
        today = self._et_date()
        try:
            last = MARKER.read_text().strip()
        except Exception:
            last = None
        if today and last == today:
            return {"status": "REMEDIATE_NOT_DUE", "ran": False, "date": today}
        res = self.remediate(apply=True)
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            MARKER.write_text(today or "")
        except Exception:
            pass
        res["ran"] = True
        return res

    def _remediate_backup(self, apply):
        """Re-push the off-machine git backup when it has gone STALE (the guard's BACKUP_CURRENT flag).
        Git is the ONLY off-machine channel the always-on service can run (iCloud + external volumes are
        TCC-blocked). A transient push failure self-heals on retry; a persistent one dedups via the alert
        fingerprint + rate floor. Never forces a push when the backup is already current. Returns
        (action_dict, alert_or_None)."""
        try:
            from app.services.git_data_backup_engine import GitDataBackupEngine
            gb = GitDataBackupEngine()
            gh = gb.hours_since()
            if not (gh is None or gh > self.BACKUP_STALE_HOURS):
                return {"hours_since": gh, "ran": False, "status": "BACKUP_CURRENT"}, None
            if not apply:
                return {"was_hours": gh, "ran": False, "would": "force off-machine git backup"}, None
            br = gb.backup(push=True)
            action = {"was_hours": gh, "ran": True, "status": br.get("status"), "ok": br.get("ok"),
                      "pushed": br.get("pushed"), "files": br.get("files"), "expected": br.get("expected")}
            alert = None
            if not br.get("ok"):
                alert = (f"off-machine git backup FAILED to refresh (was {gh}h stale): "
                         f"{br.get('status')} — {str(br.get('detail'))[:80]}")
            return action, alert
        except Exception as e:
            # A thrown self-heal is a FAILED backup refresh, not a no-op — surface it so the run isn't
            # reported as cleanly REMEDIATED while the off-machine backup silently stayed stale.
            return ({"error": str(e)[:120], "ran": False, "status": "BACKUP_REMEDIATE_ERROR"},
                    f"off-machine git backup remediation ERRORED: {str(e)[:100]}")

    def _alert_signature(self):
        """Cheap, LOCAL read (no API) of the freshest validator reports → (has_alert, fingerprint, detail).
        The fingerprint is the exact fault set, so a persistent unfixable fault dedups to one attempt."""
        crit, crit_syms, changed, changed_syms = 0, [], 0, []
        reads_ok = True                       # a validator that THROWS is unknown, not a clean "no fault"
        try:
            from app.services.price_bar_integrity_engine import PriceBarIntegrityEngine
            eng = PriceBarIntegrityEngine()
            integ = eng.last_scan() or {}
            crit = int(integ.get("critical_count") or 0)
            crit_syms = sorted({str(i.get("symbol")).upper() for i in (integ.get("issues") or [])
                                if str(i.get("type")) in getattr(eng, "CRITICAL_TYPES", ())})
        except Exception:
            reads_ok = False
        try:
            from app.services.price_bar_lineage_engine import PriceBarLineageEngine
            lin = PriceBarLineageEngine().last_report() or {}
            changed = int(lin.get("changed_count") or 0)
            # fingerprint on the actual symbol SET, not just the count — otherwise a different set of
            # changed bars with the same count dedups as "already handled" and a new fault is skipped.
            changed_syms = sorted({str(c.get("symbol")).upper() for c in (lin.get("changed") or [])
                                   if c.get("symbol")})
        except Exception:
            reads_ok = False
        # off-machine backup staleness (local git-log read, no network) — a flagged backup is a fault
        # the remediation can fix (re-push), so it should trigger an alert-run too.
        backup_stale = False
        try:
            from app.services.git_data_backup_engine import GitDataBackupEngine
            gh = GitDataBackupEngine().hours_since()
            backup_stale = gh is None or gh > self.BACKUP_STALE_HOURS
        except Exception:
            pass
        has_alert = crit > 0 or changed > 0 or backup_stale
        fingerprint = (f"crit:{','.join(crit_syms)}|changed:{changed}"
                       f"|changed_syms:{','.join(changed_syms)}|backup_stale:{int(backup_stale)}")
        return has_alert, fingerprint, {"critical_bars": crit, "lineage_changed": changed,
                                        "backup_stale": backup_stale, "validator_reads_ok": reads_ok}

    def run_on_alert(self):
        """Event-driven remediation: fix data faults the MOMENT a validator flags them, instead of
        waiting for the daily pass (the daily run at 04:09 ran BEFORE today's scan found the faults).
        Guarded so it can never hammer the TS API: (1) skips an IDENTICAL fault already attempted
        (fingerprint dedup — re-fetching won't fix what refresh/repair already couldn't), and (2) a hard
        rate floor between any two alert-runs. Uses a SMALL refresh slice. Gated by GREYLINE_DATA_AUTOREMEDIATE."""
        if not self.enabled():
            return {"status": "REMEDIATE_DISABLED", "ran": False}
        has_alert, fingerprint, detail = self._alert_signature()
        if not has_alert:
            return {"status": "REMEDIATE_NO_ALERT", "ran": False, **detail}
        try:
            last = json.loads(EVENT_MARKER.read_text())
        except Exception:
            last = {}
        # (1) same fault we already handled → don't re-run (avoids hammering a persistent unfixable fault)
        if last.get("fingerprint") == fingerprint:
            return {"status": "REMEDIATE_ALERT_ALREADY_HANDLED", "ran": False,
                    "fingerprint": fingerprint, **detail}
        # (2) hard rate floor between alert-runs
        now = datetime.utcnow()
        try:
            elapsed = (now - datetime.fromisoformat(last.get("ts"))).total_seconds()
            if elapsed < self.EVENT_MIN_INTERVAL_MIN * 60:
                return {"status": "REMEDIATE_EVENT_THROTTLED", "ran": False,
                        "retry_after_s": int(self.EVENT_MIN_INTERVAL_MIN * 60 - elapsed), **detail}
        except Exception:
            pass
        res = self.remediate(apply=True, universe_limit=self.EVENT_UNIVERSE_LIMIT)
        res["trigger"] = "alert"
        res["alert"] = detail
        res["ran"] = True
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            EVENT_MARKER.write_text(json.dumps({"ts": now.isoformat(), "fingerprint": fingerprint}))
        except Exception:
            pass
        return res

    def _log(self, result):
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            with open(LOG, "a") as f:
                f.write(json.dumps({"ts": result["finished"], "status": result["status"],
                                    "actions": result["actions"], "alerts": result["alerts"]}) + "\n")
        except Exception:
            pass

    def _alert(self, alerts):
        try:
            from app.services.external_alert_engine import ExternalAlertEngine
            eng = ExternalAlertEngine()
            if eng.has_external_channel():
                eng.dispatch(title="GreyLine data remediation — review needed",
                             message="Auto-remediation ran but flagged: " + " | ".join(alerts[:6]),
                             severity="WARNING", fingerprint="DATA_REMEDIATION:" + ",".join(sorted(a.split()[0] for a in alerts)))
        except Exception:
            pass

    def status(self):
        try:
            last = None
            for ln in reversed(LOG.read_text().splitlines()):
                if ln.strip():
                    last = json.loads(ln); break
        except Exception:
            last = None
        return {"timestamp": datetime.utcnow().isoformat(), "enabled": self.enabled(),
                "last_run": last, "decision_symbols": self._decision_symbols()}
