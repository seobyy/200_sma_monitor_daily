import json
import tempfile
import unittest
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from ema_monitor.report import build_report, write_report


@dataclass
class Hit:
    ticker: str = '005930'
    close: float = 100.0
    change_pct: float = 0.0
    break_date: object = date(2026, 10, 30)
    gc_date: object = None
    gap_pct: float = 2.5
    completion_ago: int = 0


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(ma_long=200, ma_fast=100, ma_slow=150, ma_type='sma',
            signal_lookback=1, markets=['KOSPI', 'KOSDAQ'], exclude_spac=True, exclude_preferred=True,
            min_market_cap=100_000_000_000, min_trading_value=0,
            telegram_bot_token='must-not-export', telegram_chat_id='must-not-export')

    def test_exact_hits_dates_zero_and_no_credentials(self):
        report = build_report([Hit()], date(2026, 10, 30), self.config, 1234, 1200, 3)
        self.assertEqual(report['rows'][0]['change_pct'], 0)
        self.assertEqual(report['rows'][0]['break_date'], '2026-10-30')
        self.assertIsNone(report['rows'][0]['gc_date'])
        self.assertEqual(report['universeCount'], 1234)
        self.assertEqual(report['missingLatestCount'], 3)
        self.assertNotIn('telegram', json.dumps(report))
        self.assertNotIn('must-not-export', json.dumps(report))

    def test_empty_day_and_atomic_replacement(self):
        report = build_report([], date(2026, 10, 30), self.config, 100, 95, 0)
        self.assertEqual(report['rows'], [])
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'latest.json'
            write_report(report, file)
            self.assertEqual(json.loads(file.read_text(encoding='utf-8')), report)
            with self.assertRaises(ValueError):
                write_report({'invalid': float('nan')}, file)
            self.assertEqual(json.loads(file.read_text(encoding='utf-8')), report)
            self.assertEqual(list(Path(folder).iterdir()), [file])

    def test_nonfinite_source_number_stays_missing(self):
        report = build_report([Hit(close=float('nan'))], date(2026, 10, 30), self.config, 1, 1, 1)
        self.assertIsNone(report['rows'][0]['close'])


if __name__ == '__main__':
    unittest.main()
