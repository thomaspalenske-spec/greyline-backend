"""Single source of truth for WHICH TradeStation account the dashboard reads.

One switch — `GREYLINE_DASHBOARD_ACCOUNT_MODE` — decides it everywhere:

  * "paper" (default)  -> the SIMULATED account on the sandbox host (sim-api).
  * "live"             -> the REAL-MONEY account on the production host (api).

This is READ-ONLY account selection for GET balances/positions/orders. It does NOT
enable order placement of any kind. Placing a LIVE order remains a separate, independently
gated action (LiveOrderSafetyGuard + GREYLINE_LIVE_* flags) that this switch never touches.
So flipping to "live" makes the dashboard show the real account's holdings; it cannot cause
a trade.

Two safety properties, because the config is a known landmine (a real account and a SIM
account both wired):

  * NO CROSS-FALLBACK. Paper mode uses ONLY the SIM account id — it never falls back to the
    real margin account (the previous read engines did `SIM or MARGIN`, which could silently
    read the real book if the SIM id went missing). Live mode uses only the real account id.
  * HOST/ACCOUNT INTERLOCK. A SIM account id (starts with "SIM") is only served from the
    sandbox host; a real (numeric) account id only from production. A mismatch fails closed
    rather than reading the wrong book against the wrong host.
"""

from os import getenv


class TradeStationAccountSourceEngine:

    PAPER = "paper"
    LIVE = "live"

    def mode(self):
        return (getenv("GREYLINE_DASHBOARD_ACCOUNT_MODE", "paper") or "paper").strip().lower()

    def resolve(self):
        """Return the selected account target, or an ok=False error that fails closed.

        Shape: {ok, mode, base_url, account_id, host_kind, label, error}.
        """
        mode = self.mode()
        if mode == self.LIVE:
            base_url = getenv("TRADESTATION_PRODUCTION_URL", "https://api.tradestation.com")
            account_id = getenv("TRADESTATION_LIVE_ACCOUNT_ID") or getenv("TRADESTATION_MARGIN_ACCOUNT_ID", "")
            host_kind = "PRODUCTION"
            if not account_id:
                return self._err(mode, "LIVE mode set but no live account configured "
                                       "(TRADESTATION_LIVE_ACCOUNT_ID / TRADESTATION_MARGIN_ACCOUNT_ID)")
            if str(account_id).upper().startswith("SIM"):
                return self._err(mode, f"LIVE mode resolved a SIM account id ({account_id}) — refusing")
            label = f"TradeStation LIVE (real money) · {account_id}"
        else:  # paper (default)
            base_url = getenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com")
            account_id = getenv("TRADESTATION_SIM_ACCOUNT_ID", "")
            host_kind = "SANDBOX"
            if not account_id:
                return self._err(self.PAPER, "PAPER mode but TRADESTATION_SIM_ACCOUNT_ID is not set")
            if not str(account_id).upper().startswith("SIM"):
                return self._err(self.PAPER, f"PAPER mode resolved a non-SIM account id ({account_id}) — refusing")
            label = "TradeStation Paper Trading Account"

        # host/account interlock
        is_sandbox_host = "sim-api" in base_url
        acct_is_sim = str(account_id).upper().startswith("SIM")
        if acct_is_sim != is_sandbox_host:
            return self._err(mode, f"host/account mismatch: account {account_id} vs host {base_url}")

        return {"ok": True, "mode": mode, "base_url": base_url, "account_id": account_id,
                "host_kind": host_kind, "label": label, "error": None}

    def _err(self, mode, msg):
        return {"ok": False, "mode": mode, "base_url": None, "account_id": None,
                "host_kind": None, "label": f"UNRESOLVED ({mode})", "error": msg}
