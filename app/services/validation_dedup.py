"""
Shared validation helper: collapse correlated samples to independent observations.

The shadow log appends one entry per scored candidate, so a single symbol at a single
instant can appear multiple times (multiple option contracts, same directional signal).
Those are NOT independent samples — counting them all inflates n and makes the MCC
significance test overconfident. For skill measurement we keep ONE observation per
(symbol, minute).

Caveat: this removes same-instant duplication (the blatant 50%+ correlation). Residual
autocorrelation across nearby minutes / overlapping forward windows remains a known
limitation of high-frequency forward-return studies — widen `bucket_chars` (e.g. 13 for
hour) if you want a stricter independence assumption.
"""


def dedupe_by_symbol_time(entries, bucket_chars=16):
    """
    Keep one entry per (symbol, timestamp[:bucket_chars]). bucket_chars=16 => minute
    ("YYYY-MM-DDTHH:MM"); 13 => hour. Keeps the last entry seen in each bucket.
    """
    seen = {}
    for e in entries:
        symbol = str(e.get("symbol") or "").upper()
        bucket = (e.get("timestamp") or "")[:bucket_chars]
        seen[(symbol, bucket)] = e
    return list(seen.values())
