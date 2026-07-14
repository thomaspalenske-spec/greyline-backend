from datetime import datetime

from app.services.leadership_rotation_summary_engine import LeadershipRotationSummaryEngine
from app.services.sector_rotation_summary_engine import SectorRotationSummaryEngine
from app.services.cross_asset_flow_summary_engine import CrossAssetFlowSummaryEngine
from app.services.institutional_flow_summary_engine import InstitutionalFlowSummaryEngine
from app.services.opportunity_summary_engine import OpportunitySummaryEngine
from app.services.execution_governor import ExecutionGovernor


class GreyLineInstitutionalCommandCenter:

    def get_command_center(self):
        leadership = LeadershipRotationSummaryEngine().summarize()
        sector_rotation = SectorRotationSummaryEngine().summarize()
        cross_asset_flow = CrossAssetFlowSummaryEngine().summarize()
        opportunity_summary = OpportunitySummaryEngine().get_summary()
        governor = ExecutionGovernor().evaluate_execution_permission("EXECUTE")

        institutional_focus = None
        opportunities = opportunity_summary.get("opportunities", [])

        if opportunities:
            top = sorted(
                opportunities,
                key=lambda item: item.get("composite_score", 0),
                reverse=True
            )[0]
            institutional_focus = InstitutionalFlowSummaryEngine().summarize_symbol(
                top.get("symbol")
            )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "leadership": leadership,
            "sector_rotation": sector_rotation,
            "cross_asset_flow": cross_asset_flow,
            "institutional_focus": institutional_focus,
            "opportunity_summary": opportunity_summary,
            "execution_governor": governor,
            "execution_enabled": governor.get("execution_enabled"),
            "order_placement_allowed": governor.get("order_placement_allowed"),
            "status": "GREYLINE_INSTITUTIONAL_COMMAND_CENTER_READY"
        }
