from fastapi import APIRouter

from app.services.leadership_rotation_engine import LeadershipRotationEngine
from app.services.universe_snapshot_capture_engine import UniverseSnapshotCaptureEngine
from app.services.universe_snapshot_reader import UniverseSnapshotReader
from app.services.universe_momentum_ranking_engine import UniverseMomentumRankingEngine
from app.services.leadership_persistence_engine import LeadershipPersistenceEngine
from app.services.leadership_rotation_summary_engine import LeadershipRotationSummaryEngine
from app.services.sector_rotation_summary_engine import SectorRotationSummaryEngine
from app.services.cross_asset_flow_engine import CrossAssetFlowEngine
from app.services.cross_asset_flow_summary_engine import CrossAssetFlowSummaryEngine
from app.services.greyline_institutional_command_center import GreyLineInstitutionalCommandCenter
from app.services.rotation_velocity_engine import RotationVelocityEngine
from app.services.institutional_sponsorship_engine import InstitutionalSponsorshipEngine
from app.services.options_flow_engine import OptionsFlowEngine

router = APIRouter()


@router.get("/leadership-rotation-core")
def leadership_rotation_core():
    return LeadershipRotationEngine().evaluate_leaders(["NVDA", "AMD", "META", "PLTR", "TSM"])


@router.get("/universe-snapshot-capture")
def universe_snapshot_capture():
    return UniverseSnapshotCaptureEngine().capture_core_universe()


@router.get("/universe-snapshot-coverage")
def universe_snapshot_coverage():
    return UniverseSnapshotReader().read_snapshot_coverage()


@router.get("/universe-momentum-rankings")
def universe_momentum_rankings():
    return UniverseMomentumRankingEngine().rank_universe()


@router.get("/leadership-persistence")
def leadership_persistence():
    return LeadershipPersistenceEngine().evaluate_persistence()


@router.get("/leadership-rotation-summary")
def leadership_rotation_summary():
    return LeadershipRotationSummaryEngine().summarize()


@router.get("/sector-rotation-summary")
def sector_rotation_summary():
    return SectorRotationSummaryEngine().summarize()


@router.get("/cross-asset-flow")
def cross_asset_flow():
    return CrossAssetFlowEngine().evaluate_cross_asset_flow()


@router.get("/cross-asset-flow-summary")
def cross_asset_flow_summary():
    return CrossAssetFlowSummaryEngine().summarize()


@router.get("/greyline-command-center")
def greyline_command_center():
    return GreyLineInstitutionalCommandCenter().get_command_center()


@router.get("/rotation-velocity")
def rotation_velocity():
    return RotationVelocityEngine().evaluate_velocity()


@router.get("/institutional-sponsorship-nvda")
def institutional_sponsorship_nvda():
    return InstitutionalSponsorshipEngine().evaluate_symbol("NVDA")


@router.get("/options-flow-nvda")
def options_flow_nvda():
    return OptionsFlowEngine().evaluate_symbol("NVDA")
