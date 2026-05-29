from app.governance.schema_validator import validate_account_schema

sample_report = {
    "Starting Capital": 10000,
    "Estimated Current Equity": 586000,
    "Estimated Realized Gains": 241000,
    "Estimated Unrealized Gains": 335000,
    "Estimated Cash Position": 38000,
    "Risk State": "Normal",
    "Survivability Status": "Strong",
    "Deployment Bias": "Selective Aggression",
    "Portfolio Heat": "Controlled",
    "Liquidity State": "Stable",
    "Opportunity Flow": "Moderate",
    "Correlation Exposure": "Elevated",
    "DPPL Compression State": "Active",
    "Execute Thresholds": "Tightened",
    "Confidence Classification": "Simulated / Reconstructed Estimate",
}

result = validate_account_schema(sample_report)

print(result)


