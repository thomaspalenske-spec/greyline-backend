# Load .env into the process environment BEFORE any engine reads getenv(), so
# execution-governance flags (GREYLINE_*) and broker credentials are file-controlled.
# override=False keeps standard precedence: a real shell `export` still wins over .env.
import app.services.env_reload  # noqa: F401 — snapshots the real process env; MUST precede any .env load
# faulthandler on SIGUSR1: `kill -USR1 <pid>` dumps ALL thread stacks to stderr (logs/launchd.err.log).
# Harmless + always-on so a frozen scheduler cycle (or any hang) can be diagnosed live without py-spy.
import faulthandler as _fh, signal as _sig
_fh.register(_sig.SIGUSR1, all_threads=True)
from dotenv import load_dotenv
load_dotenv(override=False)

from app.routes import portfolio_governor
from fastapi import FastAPI
from app.routes import operator_notifications
from app.routes.historical_data_import import router as historical_data_import_router
from app.routes.institutional_flow import router as institutional_flow_router
from app.routes import ai_operator
from app.routes import paper_trade_ledger
from app.routes import paper_account_dashboard_route
from app.routes import options_account_dashboard
from app.routes import paper_trade_executor
from app.routes import core
from app.routes import paper_trading
from app.routes import tradestation
from app.routes import portfolio
from app.routes import watchlist
from app.routes import market_intelligence
from app.routes import institutional_flow
from app.routes import leadership
from app.routes import backend_admin
from app.routes import broker_readiness
from app.routes import decision_performance
from app.routes import decision_outcomes
from app.routes import decision_self_audit

app = FastAPI(title="GreyLine Backend Server")


# --- Password gate for remote/public access -------------------------------------------
# When GREYLINE_DASHBOARD_PASSWORD is set, EVERY request needs HTTP Basic auth with that
# password (any username). When unset, this is a no-op (localhost-only usage is unchanged).
# This is the required guard before exposing the dashboard through a tunnel — it carries the
# real account and live action buttons; a public URL with no auth is not acceptable.
import base64 as _b64
from os import getenv as _getenv
from starlette.middleware.base import BaseHTTPMiddleware as _BaseHTTPMiddleware
from starlette.responses import Response as _Response


class _DashboardAuthMiddleware(_BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        pw = _getenv("GREYLINE_DASHBOARD_PASSWORD", "") or ""
        if pw:
            header = request.headers.get("Authorization", "")
            ok = False
            if header.startswith("Basic "):
                try:
                    _, _, provided = _b64.b64decode(header[6:]).decode("utf-8", "replace").partition(":")
                    ok = provided == pw
                except Exception:
                    ok = False
            if not ok:
                return _Response(status_code=401, content="Authentication required",
                                 headers={"WWW-Authenticate": 'Basic realm="GreyLine"'})
        response = await call_next(request)
        # NEVER let a browser cache an HTML dashboard. Stale pages repeatedly showed old
        # positions/status (e.g. YELLOW + "2 alerts" when the live state was GREEN + 0),
        # which is indistinguishable from the system being wrong. Applies to every page.
        if "text/html" in str(response.headers.get("content-type", "")).lower():
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


app.add_middleware(_DashboardAuthMiddleware)

app.include_router(operator_notifications.router)
app.include_router(historical_data_import_router)
app.include_router(institutional_flow_router)
app.include_router(core.router)
app.include_router(paper_trading.router)
app.include_router(tradestation.router)
app.include_router(portfolio.router)
app.include_router(watchlist.router)
app.include_router(market_intelligence.router)
app.include_router(institutional_flow.router)
app.include_router(leadership.router)
app.include_router(backend_admin.router)
app.include_router(broker_readiness.router)
app.include_router(decision_performance.router)
app.include_router(decision_outcomes.router)
app.include_router(decision_self_audit.router)

from app.routes import decision_metrics

app.include_router(decision_metrics.router)

from app.routes import operator_decision_dashboard

app.include_router(operator_decision_dashboard.router)

from app.routes import decision_scheduler

app.include_router(decision_scheduler.router)

from app.routes import decision_validation

app.include_router(decision_validation.router)

from app.routes import forward_outcomes

app.include_router(forward_outcomes.router)

from app.routes import tradestation_token_maintenance

app.include_router(tradestation_token_maintenance.router)

from app.routes import tradestation_auth_exchange

app.include_router(tradestation_auth_exchange.router)

from app.routes import tradestation_auth_url

app.include_router(tradestation_auth_url.router)

from app.routes import decision_outcome_scores

app.include_router(decision_outcome_scores.router)

from app.routes import decision_accuracy_dashboard

app.include_router(decision_accuracy_dashboard.router)

from app.routes import decision_learning

app.include_router(decision_learning.router)

from app.routes import decision_learning_memory

app.include_router(decision_learning_memory.router)

from app.routes import learning_analytics

app.include_router(learning_analytics.router)

from app.routes import decision_feature_attribution

app.include_router(decision_feature_attribution.router)

from app.routes import decision_weight_recommendations

app.include_router(decision_weight_recommendations.router)

from app.routes import adaptive_weight_governance

app.include_router(adaptive_weight_governance.router)

from app.routes import system_health

app.include_router(system_health.router)

from app.routes import startup_recovery

app.include_router(startup_recovery.router)

from app.routes import background_scheduler

app.include_router(background_scheduler.router)

from app.routes import ts_quote_stream

app.include_router(ts_quote_stream.router)

from app.routes import gamma_flip_history

app.include_router(gamma_flip_history.router)

from app.routes import extended_etf_universe

app.include_router(extended_etf_universe.router)

from app.routes import audit_ledger

app.include_router(audit_ledger.router)

from app.startup_events import register_startup_events
register_startup_events(app)

from app.routes import greyline_connection_watchdog
app.include_router(greyline_connection_watchdog.router)

from app.routes import pre_trade_risk_gate
app.include_router(pre_trade_risk_gate.router)

from app.routes import live_trade_authority_gate
from app.routes import deployment_governance
from app.routes import paper_trade_history
app.include_router(live_trade_authority_gate.router)

app.include_router(ai_operator.router)
app.include_router(paper_trade_ledger.router)
app.include_router(paper_account_dashboard_route.router)
app.include_router(options_account_dashboard.router)
app.include_router(paper_trade_executor.router)

app.include_router(deployment_governance.router)

app.include_router(paper_trade_history.router)

from app.routes import operator_dashboard
app.include_router(operator_dashboard.router)

from app.routes import greyline_reliability_core
app.include_router(greyline_reliability_core.router)

from app.routes import ops_metrics
app.include_router(ops_metrics.router)

from app.routes import strategy_validation
app.include_router(strategy_validation.router)

from app.routes import fixed_horizon_validation
app.include_router(fixed_horizon_validation.router)

from app.routes import flow_skill_validation
app.include_router(flow_skill_validation.router)

from app.routes import shadow_comparison
app.include_router(shadow_comparison.router)

from app.routes import feature_skill
app.include_router(feature_skill.router)

from app.routes import fast_quote_heartbeat
app.include_router(fast_quote_heartbeat.router)

from app.routes import flat_day_diagnostics
app.include_router(flat_day_diagnostics.router)

from app.routes import data_integrity
app.include_router(data_integrity.router)

from app.routes import continuity
app.include_router(continuity.router)

from app.routes import uw_retention
app.include_router(uw_retention.router)

from app.routes import uw_flow_edge
app.include_router(uw_flow_edge.router)

from app.routes import momentum_reversal_strategy
app.include_router(momentum_reversal_strategy.router)

from app.routes import open_positions
app.include_router(open_positions.router)

from app.routes import account_summary
app.include_router(account_summary.router)
from app.routes import sleeve_budgets
app.include_router(sleeve_budgets.router)
from app.routes import sleeve_budget_autoapply
app.include_router(sleeve_budget_autoapply.router)
from app.routes import managed_futures
app.include_router(managed_futures.router)
from app.routes import data_remediation
app.include_router(data_remediation.router)
from app.routes import condor_shadow
app.include_router(condor_shadow.router)

from app.routes import top_candidates
app.include_router(top_candidates.router)

from app.routes import reality_guard
app.include_router(reality_guard.router)

from app.routes import options_entry_learning
app.include_router(options_entry_learning.router)

from app.routes import price_bar_integrity
app.include_router(price_bar_integrity.router)

from app.routes import price_bar_cross_source
app.include_router(price_bar_cross_source.router)

from app.routes import price_bar_tradability
app.include_router(price_bar_tradability.router)

from app.routes import mechanical_flow_research
app.include_router(mechanical_flow_research.router)

from app.routes import universe_survivorship
app.include_router(universe_survivorship.router)

from app.routes import survivorship_bias
app.include_router(survivorship_bias.router)

from app.routes import momentum_reversal_backtest
app.include_router(momentum_reversal_backtest.router)

from app.routes import options_reality
app.include_router(options_reality.router)

from app.routes import edge_discovery
app.include_router(edge_discovery.router)

from app.routes import broker_protection
app.include_router(broker_protection.router)

from app.routes import external_alerts
app.include_router(external_alerts.router)

from app.routes import options_exit_policy
app.include_router(options_exit_policy.router)

from app.routes import options_exit_quality
app.include_router(options_exit_quality.router)

from app.routes import execution_cost
app.include_router(execution_cost.router)

from app.routes import vrp_study
app.include_router(vrp_study.router)

from app.routes import conditional_vrp
app.include_router(conditional_vrp.router)

from app.routes import conditional_vrp_panel
app.include_router(conditional_vrp_panel.router)

from app.routes import vrp_short_premium
app.include_router(vrp_short_premium.router)
from app.routes import adaptive_dte
app.include_router(adaptive_dte.router)
from app.routes import harvest_proof
app.include_router(harvest_proof.router)
from app.routes import earnings_vol_proof
app.include_router(earnings_vol_proof.router)
from app.routes import earnings_vol
app.include_router(earnings_vol.router)
from app.routes import vol_carry
app.include_router(vol_carry.router)
from app.routes import trend_following
app.include_router(trend_following.router)
from app.routes import risk_and_readiness
app.include_router(risk_and_readiness.router)
from app.routes import edge_persistence
app.include_router(edge_persistence.router)
from app.routes import edge_proof
app.include_router(edge_proof.router)
from app.routes import edge_first_close
app.include_router(edge_first_close.router)
from app.routes import sleeve_trade_ledger
app.include_router(sleeve_trade_ledger.router)
from app.routes import transactions_rolling
app.include_router(transactions_rolling.router)
from app.routes import low_volatility
app.include_router(low_volatility.router)
from app.routes import cross_sectional_momentum
app.include_router(cross_sectional_momentum.router)
from app.routes import sleeve_positions
app.include_router(sleeve_positions.router)

from app.routes import index_variance_premium
app.include_router(index_variance_premium.router)

from app.routes import premium_harvest_os
app.include_router(premium_harvest_os.router)

from app.routes import portfolio_greeks
app.include_router(portfolio_greeks.router)

from app.routes import crash_stress_test
app.include_router(crash_stress_test.router)

from app.routes import total_return
app.include_router(total_return.router)

from app.routes import market_regime
app.include_router(market_regime.router)

from app.routes import price_bar_lineage
app.include_router(price_bar_lineage.router)

from app.routes import opportunity_balance
app.include_router(opportunity_balance.router)

from app.routes import directional_opportunity_report
from app.routes import directional_attribution_report
app.include_router(directional_opportunity_report.router)
app.include_router(directional_attribution_report.router)

from app.routes import directional_readiness_dashboard
app.include_router(directional_readiness_dashboard.router)

from app.routes import flow_feed_readiness_report
app.include_router(flow_feed_readiness_report.router)

from app.routes import greyline_market_battlefield
app.include_router(greyline_market_battlefield.router)

from app.routes import greyline_market_battlefield_summary
app.include_router(greyline_market_battlefield_summary.router)

from app.routes import market_battlefield_cache
app.include_router(market_battlefield_cache.router)

from app.routes import options_trade_forensics
app.include_router(options_trade_forensics.router)

from app.routes import market_battlefield_forecast
app.include_router(market_battlefield_forecast.router)

from app.routes import battlefield_learning
from app.routes import forecast_accuracy_dashboard
from app.routes import forecast_reliability_dashboard
app.include_router(battlefield_learning.router)
app.include_router(forecast_accuracy_dashboard.router)
app.include_router(forecast_reliability_dashboard.router)

app.include_router(portfolio_governor.router)

from app.routes import position_alert_acks
app.include_router(position_alert_acks.router)

from app.routes import operator_cockpit_status
app.include_router(operator_cockpit_status.router)

from app.routes import operator_commander_summary
app.include_router(operator_commander_summary.router)
