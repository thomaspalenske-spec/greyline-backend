from app.reports.account_schema import ACCOUNT_REPORT_SCHEMA


def validate_account_schema(report_dict):
    missing_fields = []

    for field in ACCOUNT_REPORT_SCHEMA:
        if field not in report_dict:
            missing_fields.append(field)

    return {
        "valid": len(missing_fields) == 0,
        "missing_fields": missing_fields
    }
