from fastapi import FastAPI
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
