"""One correct timestamp parser, because the wrong ones kept getting copied.

GreyLine had this helper duplicated across a dozen engines in two broken variants, and
both silently corrupt horizons rather than raising:

  1. `str(ts).replace("Z","+00:00").split("+")[0]`
     Strips a POSITIVE offset but not a negative one, so "…+00:00" becomes naive while
     "…-04:00" stays tz-aware. Mixing the two raises TypeError inside a sort or a
     comparison — or, where the comparison is guarded, joins the wrong price.

  2. `datetime.fromisoformat(...).replace(tzinfo=None)`
     TRUNCATES the offset instead of converting it. "2026-07-20T09:00:00-04:00" is read as
     09:00 UTC when the instant is really 13:00 UTC. Compared against utcnow() the record
     looks four hours older than it is, so a brand-new forecast sails through a 60-minute
     maturity gate and is graded at a ~0 horizon. Nothing errors; the number is just wrong.

Both are the same root cause: a naive-UTC codebase parsing strings that may carry offsets.
`parse_utc` converts, then drops the tzinfo, so every timestamp in the system is a naive
UTC instant and comparisons are meaningful.

Import this rather than writing another copy.
"""

from datetime import datetime, timezone

_UTC = timezone.utc


def parse_utc(value):
    """Any ISO-8601 timestamp (naive, Z, +HH:MM or -HH:MM) -> naive UTC datetime, or None.

    A naive input is assumed to be UTC already, which is what the rest of the system
    writes (`datetime.utcnow().isoformat()`).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is None else value.astimezone(_UTC).replace(tzinfo=None)
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is None else parsed.astimezone(_UTC).replace(tzinfo=None)
