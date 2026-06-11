from datetime import datetime


class GreyLineLiveActivationEngine:

    def __init__(self, state_engine, safety_gate, broker_router):

        self.state_engine = state_engine
        self.safety_gate = safety_gate
        self.broker_router = broker_router

    def activate_live_mode(self):

        # STEP 1: MUST GO THROUGH ARMED STATE FIRST
        r1 = self.state_engine.transition("PAPER")
        if r1["status"] != "STATE_UPDATED":
            return {"status": "FAILED_AT_PAPER_STAGE", "detail": r1}

        r2 = self.state_engine.transition("ARMED")
        if r2["status"] != "STATE_UPDATED":
            return {"status": "FAILED_AT_ARMED_STAGE", "detail": r2}

        # STEP 2: ENABLE SAFETY GATE LIVE FLAG
        self.safety_gate.live_enabled = True

        # STEP 3: MOVE TO LIVE_ENABLED (NOT LIVE_EXECUTION YET)
        r3 = self.state_engine.transition("LIVE_ENABLED")
        if r3["status"] != "STATE_UPDATED":
            return {"status": "FAILED_AT_LIVE_ENABLED_STAGE", "detail": r3}

        # STEP 4: SWITCH BROKER MODE
        self.broker_router.mode = "LIVE"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "LIVE_MODE_ARMED_AND_ENABLED",
            "state": self.state_engine.state,
            "live_enabled": True
        }

    def deactivate_live_mode(self):

        self.safety_gate.live_enabled = False
        self.state_engine.transition("PAPER")
        self.broker_router.mode = "PAPER"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "LIVE_MODE_DISABLED",
            "state": self.state_engine.state,
            "live_enabled": False
        }
