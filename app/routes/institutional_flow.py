from fastapi import APIRouter

from app.services.quote_snapshot_service import QuoteSnapshotService
from app.services.quote_snapshot_reader import QuoteSnapshotReader
from app.services.quote_momentum_engine import QuoteMomentumEngine
from app.services.quote_snapshot_comparison_engine import QuoteSnapshotComparisonEngine
from app.services.historical_momentum_engine import HistoricalMomentumEngine
from app.services.relative_strength_engine import RelativeStrengthEngine
from app.services.volume_expansion_engine import VolumeExpansionEngine
from app.services.institutional_flow_engine import InstitutionalFlowEngine
from app.services.institutional_accumulation_engine import InstitutionalAccumulationEngine
from app.services.institutional_distribution_engine import InstitutionalDistributionEngine
from app.services.institutional_flow_summary_engine import InstitutionalFlowSummaryEngine

router = APIRouter()


@router.get("/quote-snapshot-nvda")
def quote_snapshot_nvda():
    return QuoteSnapshotService().capture_symbol_snapshot("NVDA")


@router.get("/quote-snapshot-reader-nvda")
def quote_snapshot_reader_nvda():
    return QuoteSnapshotReader().read_latest_snapshot("NVDA")


@router.get("/quote-momentum-nvda")
def quote_momentum_nvda():
    return QuoteMomentumEngine().calculate_momentum("NVDA")


@router.get("/quote-snapshot-compare-nvda")
def quote_snapshot_compare_nvda():
    return QuoteSnapshotComparisonEngine().compare_latest_two("NVDA")


@router.get("/historical-momentum-nvda")
def historical_momentum_nvda():
    return HistoricalMomentumEngine().calculate_momentum("NVDA")


@router.get("/relative-strength-nvda")
def relative_strength_nvda():
    return RelativeStrengthEngine().compare_to_benchmark("NVDA", "SPY")


@router.get("/volume-expansion-nvda")
def volume_expansion_nvda():
    return VolumeExpansionEngine().calculate_volume_expansion("NVDA")


@router.get("/institutional-flow-nvda")
def institutional_flow_nvda():
    return InstitutionalFlowEngine().evaluate_symbol("NVDA", "SPY")


@router.get("/institutional-accumulation-nvda")
def institutional_accumulation_nvda():
    return InstitutionalAccumulationEngine().evaluate_symbol("NVDA")


@router.get("/institutional-distribution-nvda")
def institutional_distribution_nvda():
    return InstitutionalDistributionEngine().evaluate_symbol("NVDA")


@router.get("/institutional-flow-summary-nvda")
def institutional_flow_summary_nvda():
    return InstitutionalFlowSummaryEngine().summarize_symbol("NVDA")
