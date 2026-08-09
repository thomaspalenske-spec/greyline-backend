from datetime import datetime
from app.services.operator_notification_engine import OperatorNotificationEngine as N
def test_unread_critical_count(monkeypatch):
    now = datetime.utcnow().isoformat()
    rows = [{"acknowledged": False, "severity": "CRITICAL", "timestamp": now, "title": "over"},
            {"acknowledged": False, "severity": "WARNING", "timestamp": now, "title": "backup"},
            {"acknowledged": False, "severity": "WARNING", "timestamp": now, "title": "backup"}]
    monkeypatch.setattr(N, "_read", lambda self: rows)
    u = N().unread()
    assert u["unread_count"] == 3 and u["unread_critical_count"] == 1
