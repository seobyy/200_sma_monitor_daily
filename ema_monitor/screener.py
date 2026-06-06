"""이동평균 계산 + 조건 스크리닝.

조건
----
C1 (추세) : 당일 종가 > MA_LONG (예: 200일선)
C2 (신호) : MA_FAST 가 MA_SLOW 를 골든크로스
            (lookback 영업일 이내에 fast 가 slow 를 상향돌파)
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from config import CONFIG


@dataclass
class Hit:
    ticker: str
    name: str
    market: str
    close: float
    ma_long: float
    ma_fast: float
    ma_slow: float
    cross_ago: int          # 골든크로스가 며칠 전 발생했는지 (0=당일)
    change_pct: float       # 당일 등락률(%)
    trading_value: float    # 당일 거래대금(원)
    market_cap: float = 0.0 # 시가총액(원)

    @property
    def gap_pct(self) -> float:
        """장기선 대비 이격도(%)."""
        return (self.close / self.ma_long - 1) * 100 if self.ma_long else 0.0


def _moving_average(df: pd.DataFrame, window: int) -> pd.DataFrame:
    if CONFIG.ma_type == "ema":
        return df.ewm(span=window, adjust=False, min_periods=window).mean()
    return df.rolling(window=window, min_periods=window).mean()


def screen(close: pd.DataFrame) -> tuple[list[str], pd.Timestamp]:
    """종가 매트릭스(index=date str, columns=ticker)에서 조건 충족 티커 반환.

    Returns
    -------
    (조건 충족 티커 리스트, 기준 거래일 문자열)
    """
    close = close.sort_index().astype("float64")
    base_date = close.index[-1]

    ma_long = _moving_average(close, CONFIG.ma_long)
    ma_fast = _moving_average(close, CONFIG.ma_fast)
    ma_slow = _moving_average(close, CONFIG.ma_slow)

    # C1: 당일 종가 > 장기선
    last_close = close.iloc[-1]
    cond_trend = last_close > ma_long.iloc[-1]

    # C2: 최근 lookback 영업일 내 fast 가 slow 를 골든크로스
    diff = ma_fast - ma_slow                 # >0 이면 fast 가 위
    prev_below = diff.shift(1) <= 0          # 전일 fast <= slow
    now_above = diff > 0                      # 당일 fast > slow
    crossed = prev_below & now_above         # 그 날 골든크로스 발생

    look = max(1, CONFIG.golden_cross_lookback)
    recent_cross = crossed.iloc[-look:]
    cond_cross = recent_cross.any(axis=0)

    selected = cond_trend & cond_cross
    tickers = [t for t, ok in selected.items() if bool(ok)]
    return tickers, base_date


def _cross_ago(close: pd.DataFrame, ticker: str) -> int:
    """티커별 골든크로스가 며칠 전 발생했는지 (0=당일)."""
    ma_fast = _moving_average(close, CONFIG.ma_fast)[ticker]
    ma_slow = _moving_average(close, CONFIG.ma_slow)[ticker]
    diff = ma_fast - ma_slow
    crossed = (diff.shift(1) <= 0) & (diff > 0)
    look = max(1, CONFIG.golden_cross_lookback)
    recent = crossed.iloc[-look:]
    idx = [i for i, v in enumerate(recent.values) if v]
    if not idx:
        return -1
    return len(recent) - 1 - idx[-1]


def build_hits(
    close: pd.DataFrame,
    tickers: list[str],
    listing: pd.DataFrame,
) -> list[Hit]:
    """조건 충족 티커들을 정렬된 Hit 리스트로 가공.

    listing : index=code, columns=[name, market, close, change_pct, amount]
    """
    ma_long = _moving_average(close, CONFIG.ma_long).iloc[-1]
    ma_fast = _moving_average(close, CONFIG.ma_fast).iloc[-1]
    ma_slow = _moving_average(close, CONFIG.ma_slow).iloc[-1]
    last_close = close.iloc[-1]
    prev_close = close.iloc[-2] if len(close) >= 2 else None

    hits: list[Hit] = []
    for t in tickers:
        if t in listing.index:
            row = listing.loc[t]
            name = str(row.get("name", t))
            market = str(row.get("market", ""))
            tval = float(row.get("amount", 0.0) or 0.0)
            mcap = float(row.get("marketcap", 0.0) or 0.0)
        else:
            name, market, tval, mcap = t, "", 0.0, 0.0

        # 등락률은 매트릭스에서 직접 계산해 임의 기준일에도 정확하게.
        if prev_close is not None and prev_close.get(t):
            change = (float(last_close[t]) / float(prev_close[t]) - 1) * 100
        else:
            change = float(row.get("change_pct", 0.0) or 0.0) if t in listing.index else 0.0

        if CONFIG.min_trading_value and tval < CONFIG.min_trading_value:
            continue

        hits.append(
            Hit(
                ticker=t,
                name=name,
                market=market,
                close=float(last_close[t]),
                ma_long=float(ma_long[t]),
                ma_fast=float(ma_fast[t]),
                ma_slow=float(ma_slow[t]),
                cross_ago=_cross_ago(close, t),
                change_pct=change,
                trading_value=tval,
                market_cap=mcap,
            )
        )

    # 당일 골든크로스 -> 거래대금 큰 순으로 정렬
    hits.sort(key=lambda h: (h.cross_ago, -h.trading_value))
    return hits
