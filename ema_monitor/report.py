"""Export the exact screening result for read-only consumers; never send alerts."""
from dataclasses import asdict
from datetime import date, datetime, timezone
from numbers import Real, Integral
from pathlib import Path
import json
import math
import os
import tempfile


def _clean(value):
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Real):
        return (int(value) if isinstance(value, Integral) else float(value)) if math.isfinite(value) else None
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    raise TypeError(f"Unsupported report value: {type(value).__name__}")


def build_report(hits, base_date, config, universe_count, evaluated_count, missing_latest_count):
    # Explicit allowlist: Config also contains Telegram credentials.
    settings = {key: getattr(config, key) for key in (
        'ma_long', 'ma_fast', 'ma_slow', 'ma_type', 'signal_lookback',
        'markets', 'exclude_spac', 'exclude_preferred', 'min_market_cap', 'min_trading_value')}
    rows = [{**asdict(hit), 'gap_pct': hit.gap_pct, 'completion_ago': hit.completion_ago} for hit in hits]
    return _clean({
        'schemaVersion': 1, 'source': '200_sma_monitor_daily',
        'asOf': base_date.isoformat()[:10], 'collectedAt': datetime.now(timezone.utc).isoformat(),
        'settings': settings, 'universeCount': universe_count, 'evaluatedCount': evaluated_count,
        'missingLatestCount': missing_latest_count, 'rows': rows,
    })


def write_report(report, path=None):
    path = Path(path) if path else Path(__file__).resolve().parent.parent / 'output' / 'latest.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, suffix='.tmp', delete=False) as file:
            temp = file.name
            file.write(body)
        os.replace(temp, path)
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)
    return path
