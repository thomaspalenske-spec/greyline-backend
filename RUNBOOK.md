# GreyLine Operations Runbook

Practical reference for running GreyLine: what the safety flags do, how to arm/disarm
paper trading, how to verify state, and what to check **before** ever enabling live
trading. Keep this current — it is the single written source of operational truth.

---

## 0. Observability & running the process

**Single health pane:** `GET /ops/metrics` — one consolidated view rolling up to
`overall_status` GREEN / YELLOW / RED, with `problems[]`:
- uptime, scheduler cycle health (success/failure counts, `cycle_success_rate_pct`,
  `consecutive_failures`, `last_error`, `last_duration_ms`), reliability score,
  execution state, and a live data-store integrity probe.
- RED when: scheduler thread down, data store degraded, or ≥5 consecutive cycle failures.
- YELLOW when: reliability degraded or ≥3 consecutive failures.

`GET /background-scheduler/status` now also carries the cycle-health fields
(`success_count` / `failure_count` / `consecutive_failures` / `recent_cycles`), so
flapping is visible instead of just the last status.

**⚠️ Do not run an armed system with `uvicorn --reload`.** `--reload` restarts the
process on any file change, which interrupts in-flight scheduler cycles and shows up as
transient `BACKGROUND_SCHEDULER_CYCLE_FAILED` (harmless but noisy, and it drops in-flight
work). For real/armed operation run without reload, e.g.:
```bash
uvicorn main:app            # no --reload; one worker (the scheduler is a singleton thread)
```
Use a supervisor (systemd / launchd / pm2) to restart on crash. Keep a single worker —
the background scheduler is an in-process singleton; multiple workers would run duplicate
cycles.

---

## 1. Execution model (how gating actually works)

GreyLine's paper-trade executors (`run_paper_trade_executor`, `OptionsPaperExecutionSweepEngine`)
gate on **`ExecutionAuthorityEngine.evaluate()`**, which requires **all** of:

1. An `EXECUTE` signal from `GreyLineMasterDecisionEngine`
2. Reliability governor in `PAPER_OPERATIONAL` (or `LIVE_OPERATIONAL`) mode
3. The **kill-switch**: `ExecutionGovernor` reports `paper_execution_enabled` (env flag) — a
   disabled flag forces `KILL_SWITCH_BLOCKED` even if 1 and 2 pass
4. The master decision's **risk gate**: `RiskEngine` risk_state must be `NORMAL`
   (drawdown-based; see §5)

`ExecutionGovernor` is the **single source of truth** for the kill-switch. Every status
surface (reliability core, scheduler status, control/command centers, operator dashboard
authority panel, options-account tiles) reads from it — they will always agree.

> A quote-freshness guard also blocks execution when the market is closed / quotes are stale,
> so nothing trades outside market hours regardless of the flags.

---

## 2. Flag reference

All boolean flags are case-insensitive `"true"`/`"false"`. **Precedence:** `main.py` calls
`load_dotenv(override=False)`, so a real shell `export` **overrides** the `.env` file. If a
flag "won't change" from `.env`, check for a stale export: `env | grep GREYLINE`.

### Paper / live execution (read by `ExecutionGovernor`)
| Flag | Default (unset) | Meaning |
|---|---|---|
| `GREYLINE_PAPER_EXECUTION_ENABLED` | **`false`** (fail-safe) | Arms autonomous paper trading. Must be explicitly `true`. |
| `GREYLINE_LIVE_TRADING_ENABLED` | `false` | Real-money master switch. |
| `GREYLINE_LIVE_ORDER_PLACEMENT_ALLOWED` | `false` | Live order placement; only effective with `GREYLINE_LIVE_TRADING_ENABLED=true`. |

### Live authority gate (separate subsystem, read by `LiveTradeAuthorityGateEngine`)
| Flag | Default | Meaning |
|---|---|---|
| `GREYLINE_LIVE_EXECUTION_ENABLED` | `false` | Live-path execution enable. |
| `GREYLINE_ORDER_PLACEMENT_ALLOWED` | `false` | Live-path order placement. |
| `GREYLINE_KILL_SWITCH_STATE` | `LOCKED` | Live-path kill switch. |

### Risk gate (read by `RiskEngine` → master decision)
| Flag | Default | Meaning |
|---|---|---|
| `GREYLINE_RISK_HALT_DRAWDOWN_PCT` | `20` | Paper-equity drawdown % that forces risk_state `HALTED` → `NO_ACTION`. |
| `GREYLINE_RISK_DEFENSIVE_DRAWDOWN_PCT` | `10` | Drawdown % that forces `DEFENSIVE`. |

### Broker / account
| Flag | Notes |
|---|---|
| `TRADESTATION_SANDBOX_URL` | Broker API base URL used by the live read engines. **Misnamed** — may hold a PRODUCTION host. Code default fails **safe** to `https://sim-api.tradestation.com`. Broker access is currently **read-only**. |
| `TRADESTATION_MARGIN_ACCOUNT_ID` | Expected account id — checked by `PreTradeRiskGateEngine` and `GreyLineConnectionWatchdogEngine` (fail-safe: unset → gate blocks). |
| `UNUSUAL_WHALES_API_KEY` | **Mission-critical.** Goes in `.env.local`. The institutional-flow engine only collects real data when this is set; the scheduler **auto-enables** `collect_unusual_whales` when present. Absent → flow signals stay defaulted and the strategy runs on a price-momentum proxy (see §8). |
| `DEV_MODE` | Dev convenience. A failing readiness score is `BLOCKED` unless `DEV_MODE=true`. |

---

## 3. Arm paper trading (make it "hot")

1. **Set the flag in `.env`:**
   ```bash
   # in greyline-backend/.env
   GREYLINE_PAPER_EXECUTION_ENABLED=true
   ```
2. **Restart from a shell with no stale exports** (Terminal 1 = the server terminal):
   ```bash
   # Ctrl+C to stop uvicorn, then:
   unset GREYLINE_PAPER_EXECUTION_ENABLED GREYLINE_LIVE_TRADING_ENABLED GREYLINE_LIVE_ORDER_PLACEMENT_ALLOWED
   uvicorn main:app --reload
   ```
   (A fresh terminal has no exports and is equivalent.)
3. Once armed and the market is open, the scheduler records paper trades autonomously when a
   candidate qualifies (subject to the risk gate and quote-freshness guard).

### Disarm
Set `GREYLINE_PAPER_EXECUTION_ENABLED=false` in `.env` (or re-export it) and restart.

---

## 4. Verify state (Terminal 2 = command terminal)

```bash
# no stale export shadowing .env (should print nothing when relying on .env):
env | grep GREYLINE

# kill-switch / execution:
curl -s localhost:8000/background-scheduler/status | python3 -m json.tool | grep -E "execution_enabled|order_placement"

# full health:
curl -s localhost:8000/greyline-reliability-core | python3 -m json.tool

# operator dashboard (visual): http://localhost:8000/operator-dashboard
#   Authority Verdict PAPER_EXECUTE (green) + Paper Kill-Switch ARMED = hot
#   KILL_SWITCH_BLOCKED (red) = disarmed
```

Armed looks like: `execution_enabled: true`, `order_placement_allowed: true`, dashboard
Authority Verdict `PAPER_EXECUTE`, Paper Execution `READY`, **Live Order Placement `BLOCKED`**.

---

## 5. Risk gate (multi-dimensional)

`RiskEngine.evaluate()` resolves `risk_state` to the **worst** of these dimensions. When
`risk_state != NORMAL`, the master decision returns `NO_ACTION` (blocks new entries).

| Dimension | Source | Block type |
|---|---|---|
| **Drawdown** | `PaperDrawdownEngine` (live) | HARD — HALTED ≥ `..._HALT_...`, DEFENSIVE ≥ `..._DEFENSIVE_...` |
| **Correlation** | `PortfolioCorrelationEngine` (live sector clustering) | HARD — `correlation_risk == HIGH` |
| **Position/exposure limits** | `PositionExposureLimitEngine` (live) | HARD — `GREYLINE_MAX_OPEN_POSITIONS` / `GREYLINE_MAX_SECTOR_EXPOSURE_PCT` breach |
| **Directional** | `PortfolioDirectionalExposureEngine` (live net exposure) | SOFT — `directional_risk == HIGH` blocks SAME-direction only |
| **Liquidity** | *placeholder* — not computed | (never; labeled `PLACEHOLDER_NOT_COMPUTED`) |

- **HARD blocks** stop new entries in ANY direction. A **SOFT (directional) block** stops
  same-direction entries but permits opposite/neutral ones to rebalance — the master decision
  uses `entry_allowed(risk, candidate_direction)`, not the bare `risk_state`.
- `blocking_factors` / `hard_block_factors` name exactly what tripped; `net_directional_bias`
  says which way the book leans.
- Any dimension compute error fails to a **non-blocking** `RISK_STATE_DEGRADED` — never crashes
  or silently halts the decision path.

---

## 6. ⚠️ Before enabling LIVE trading — checklist

Live trading is **off** and there is currently **no live order-placement engine**. Do NOT flip
`GREYLINE_LIVE_TRADING_ENABLED=true` until all of the following are done:

- [x] **Broker URL guard — BUILT.** `LiveOrderSafetyGuard` (`live_order_safety_guard_engine.py`)
      refuses live orders against a PRODUCTION host unless `GREYLINE_LIVE_PRODUCTION_CONFIRMED=true`.
      Its production check is also wired into `LiveTradeAuthorityGateEngine` (won't arm otherwise).
      **Any future live-order code MUST call `LiveOrderSafetyGuard().assert_safe_to_place_live_order()`
      immediately before the broker POST** — it raises `LiveOrderSafetyError` if not safe.
- [ ] Confirm `TRADESTATION_MARGIN_ACCOUNT_ID` matches the intended account.
- [ ] Reconcile the two flag families (`GREYLINE_LIVE_TRADING_ENABLED` vs
      `GREYLINE_LIVE_EXECUTION_ENABLED`) so both gate subsystems agree.
- [ ] Extend `RiskEngine` beyond drawdown (correlation/liquidity are placeholders).
- [ ] Full reconciliation + kill-switch test against the real broker workflow.

### To actually place live orders against production, ALL must hold:
1. `GREYLINE_LIVE_TRADING_ENABLED=true`
2. `GREYLINE_LIVE_ORDER_PLACEMENT_ALLOWED=true`
3. `GREYLINE_LIVE_PRODUCTION_CONFIRMED=true`  ← conscious "yes, this is production" acknowledgement
4. (live authority gate family) `GREYLINE_LIVE_EXECUTION_ENABLED=true`,
   `GREYLINE_ORDER_PLACEMENT_ALLOWED=true`, `GREYLINE_KILL_SWITCH_STATE=ARMED`

Sandbox endpoints (`sim-api.tradestation.com`) do **not** require confirmation (3).

---

## 7. Known placeholders / deferred (not bugs, but be aware)

- `RiskEngine` correlation/liquidity — placeholders (drawdown is real).
- `paper_trading_command_center` / `paper_trading_control_center` arming gates
  (`paper_trading_ready`, `approval_passed`, etc.) are deliberately hardcoded human-gated
  values; only the factual `broker_connected` / `api_credentials_configured` fields are live.
- Hardcoded symbol universes in a few engines (fast-quote heartbeat, leadership, cross-asset).
- `decision_quality_score` returns `None` until forward outcomes are scored — expected.

---

## 8. Strategy validation & institutional flow (the mission's core question)

GreyLine's edge — *does institutional flow predict direction?* — is **measured, not assumed.**
All verdicts are drift-robust and refuse to render on invalid/insufficient data.

### Endpoints
| Endpoint | What it answers |
|---|---|
| `GET /ops/metrics` | System health rollup (GREEN/YELLOW/RED) — uptime, cycle success rate, reliability, data-store probe |
| `GET /strategy-validation` | Directional edge on recorded outcomes, EXECUTE-only, **drift-confound aware** (won't claim edge on drift-dominated data) |
| `GET /fixed-horizon-validation?horizon_hours=24` | Grades each decision at a **fixed horizon** (not "current price"); reports MCC-based skill |
| `GET /flow-skill-validation?horizon_hours=24` | **The founding hypothesis:** MCC of institutional-flow-implied direction vs actual moves |
| `GET /shadow-comparison?horizon_hours=24` | **Head-to-head A/B:** momentum-proxy MCC vs institutional-flow MCC on the *same* decisions → `winner` |

### The metric that matters: MCC (`skill.mcc`)
Matthews Correlation Coefficient is **0 for any constant / drift-following predictor**, so it can't
be fooled by market direction: `> 0` significant = real skill · `~0` = none · `< 0` = anti-skill.
Raw hit rate and per-direction rates are drift-confounded — do **not** read them as skill.

### Current state
- The live directional decision still runs on a **price-momentum proxy**
  (`InstitutionalFootprintEngine`, `NO_DIRECT_DARK_POOL_OR_BLOCK_FEED`) — measured **anti-skilled**
  (MCC ≈ −0.3). Real flow is **not yet wired into the decision** (validate first, then wire).
- Real institutional-flow collection is **LIVE**: `UNUSUAL_WHALES_API_KEY` is set, the scheduler
  auto-armed `collect_unusual_whales`, and `institutional_buying_score` / `selling_score` now
  populate with real varying values.

### Momentum-vs-flow A/B (how the verdict gets made)
Two mechanisms feed the validators, both firing on the decision path each cycle:
- **Flow↔price co-record** (`InstitutionalMemoryEngine.record` → `PriceHistoryStore`): every cycle,
  the symbol's price is saved to the price series so outcomes are joinable at a fixed horizon. The
  price is **passed in explicitly** from the quote already fetched that cycle
  (`LiveUniverseQuoteScanner` surfaces `last` → `opportunity_scoring_engine` → `record(price=…)`);
  the record path only falls back to a live quote fetch when no price is supplied. Price is recorded
  **before** the snapshot dedup/interval gates, so the series stays dense **even when the flow
  snapshot itself dedups** (flow signals are often constant → snapshots rarely change, but the join
  needs a price near both `T` and `T+horizon`). A price failure never blocks snapshot recording.
- **Shadow log** (`DecisionShadowLogEngine` → `app/data/decision_shadow/…`): each decision records
  BOTH the momentum-proxy direction and the flow-implied direction (no effect on trading).

`GET /shadow-comparison` then grades both against actual moves and reports `winner` + each MCC.

> **Why a validator can be starved (`INSUFFICIENT_DATA` / `dropped_no_price_join`):** the join needs a
> price within tolerance of BOTH the snapshot time and snapshot+horizon. Two legitimate causes: (a) the
> snapshot is younger than the horizon (its forward price doesn't exist yet — just wait), or (b) a symbol
> got flow snapshots but no joinable price series (historically this happened when the co-record's live
> fetch failed silently; fixed above). For symbols already orphaned this way (e.g. a symbol that stopped
> being scanned), forward accumulation can't recover them — **backfill** instead: see below.

### Backfilling price history for orphaned snapshots
`backfill_price_history.py` (repo root) repopulates `PriceHistoryStore` for symbols that have flow
snapshots but missing/sparse prices, pulling historical bars from the TradeStation MarketData
BarCharts API (read-only; reuses the same token maintenance + `TRADESTATION_SANDBOX_URL` as the quote
engine). Run it on a machine with a valid TradeStation token and network:
```bash
python backfill_price_history.py            # backfill all snapshot symbols over their snapshot window
python backfill_price_history.py --dry-run  # show gaps + planned fetches, write nothing
python backfill_price_history.py --symbols NVDA XLU   # limit to specific symbols
```
It is idempotent (skips bars already present within a few minutes), records intraday 60-min bars so
the ±tolerance join is satisfied, and prints a before/after coverage + newly-gradable report. Re-run
`/flow-skill-validation` and `/shadow-comparison` afterward (no restart needed — validators read the
store live).

### Reading the verdict → deciding whether to wire flow in
1. Let flow + price + shadow data accumulate across a session (ideally a few days, both up and down moves).
2. `curl /shadow-comparison` and `curl /flow-skill-validation` → read `winner` and `skill.mcc`.
3. If flow's MCC is significantly **> 0** (and beats momentum), wire the flow signal into
   `opportunity_scoring_engine`'s directional decision (replacing the price proxy). If not, the
   founding hypothesis needs rethinking — better to know honestly than to trade on faith.

> Restart note: engine changes need a server restart to take effect (armed runs use no `--reload`, see §0).
