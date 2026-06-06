"""중앙 설정 모듈.

.env 파일 또는 환경변수에서 값을 읽어 타입 변환된 설정을 제공한다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
CACHE_FILE = DATA_DIR / "close_prices.parquet"


def _get_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_int(key: str, default: int) -> int:
    val = os.getenv(key)
    try:
        return int(val) if val is not None else default
    except ValueError:
        return default


@dataclass
class Config:
    # Telegram
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Moving averages
    ma_long: int = _get_int("MA_LONG", 200)
    ma_fast: int = _get_int("MA_FAST", 100)
    ma_slow: int = _get_int("MA_SLOW", 150)
    ma_type: str = os.getenv("MA_TYPE", "sma").strip().lower()
    golden_cross_lookback: int = _get_int("GOLDEN_CROSS_LOOKBACK", 1)

    # Universe
    markets: list[str] = field(
        default_factory=lambda: [
            m.strip().upper()
            for m in os.getenv("MARKETS", "KOSPI,KOSDAQ").split(",")
            if m.strip()
        ]
    )
    exclude_spac: bool = _get_bool("EXCLUDE_SPAC", True)
    exclude_preferred: bool = _get_bool("EXCLUDE_PREFERRED", True)
    min_trading_value: int = _get_int("MIN_TRADING_VALUE", 0)
    # 최소 시가총액(원). 0 이면 미적용. 기본 1000억.
    min_market_cap: int = _get_int("MIN_MARKET_CAP", 100_000_000_000)

    @property
    def lookback_trading_days(self) -> int:
        """필요한 최소 거래일 수 (가장 긴 선 + 골든크로스 판정 여유)."""
        longest = max(self.ma_long, self.ma_slow, self.ma_fast)
        return longest + self.golden_cross_lookback + 10

    def validate_telegram(self) -> None:
        if not self.telegram_bot_token or not self.telegram_chat_id:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 설정되지 않았습니다. "
                ".env 파일을 확인하세요 (.env.example 참고)."
            )


CONFIG = Config()
