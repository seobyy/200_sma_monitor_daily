"""이동평균 계산 + Stage 2 진입 스크리닝.

마크 미너비니 Stage 2 진입 셋업
--------------------------------
조건 1 (추세) : 당일 종가 > MA_LONG(예: 200일선)
조건 2 (신호) : MA_FAST(100일선)가 MA_SLOW(150일선)를 상향 돌파한 상태

두 조건은 서로 다른 날 충족될 수 있다.  "진입 신호"는 **두 조건이 모두
충족된 상태**가 되었고, 그 중 **하나가 최근(기본=오늘) 새로 충족**되어
셋업이 비로소 완성된 종목을 의미한다.

  selected = (조건1 현재충족) AND (조건2 현재충족)
             AND (조건1 또는 조건2 가 최근 lookback 영업일 내 신규 돌파)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
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
    break_ago: int          # 종가가 MA_LONG 상향돌파한 지 며칠 (0=오늘, -1=이전부터)
    gc_ago: int             # MA_FAST 가 MA_SLOW 골든크로스한 지 며칠 (0=오늘, -1=이전부터)
    change_pct: float       # 당일 등락률(%)
    trading_value: float    # 당일 거래대금(원)
    market_cap: float = 0.0  # 시가총액(원)
    break_date: object = None  # 200선 돌파일 (Timestamp 또는 None)
    gc_date: object = None     # 골든크로스일 (Timestamp 또는 None)

    @property
    def gap_pct(self) -> float:
        """장기선 대비 이격도(%)."""
        return (self.close / self.ma_long - 1) * 100 if self.ma_long else 0.0

    @property
    def completion_ago(self) -> int:
        """셋업이 완성된 지 며칠 (두 신규 돌파 중 더 최근 것). 0=오늘."""
        agos = [a for a in (self.break_ago, self.gc_ago) if a >= 0]
        return min(agos) if agos else 0


def _moving_average(df: pd.DataFrame, window: int) -> pd.DataFrame:
    if CONFIG.ma_type == "ema":
        return df.ewm(span=window, adjust=False, min_periods=window).mean()
    return df.rolling(window=window, min_periods=window).mean()


def _crosses(fast: pd.DataFrame, slow: pd.DataFrame) -> pd.DataFrame:
    """fast 가 slow 를 상향 돌파한 날 True (전일 fast<=slow, 당일 fast>slow)."""
    diff = fast - slow
    return (diff.shift(1) <= 0) & (diff > 0)


def _cross_ago_col(cross_col: pd.Series) -> int:
    """해당 시리즈에서 마지막 True 가 며칠 전인지. 없으면 -1."""
    idx = np.where(cross_col.values)[0]
    if len(idx) == 0:
        return -1
    return len(cross_col) - 1 - int(idx[-1])


def screen(close: pd.DataFrame) -> tuple[list[str], pd.Timestamp]:
    """종가 매트릭스에서 Stage 2 진입 종목과 기준 거래일 반환."""
    close = close.sort_index().astype("float64")
    base_date = close.index[-1]

    ma_long = _moving_average(close, CONFIG.ma_long)
    ma_fast = _moving_average(close, CONFIG.ma_fast)
    ma_slow = _moving_average(close, CONFIG.ma_slow)

    # 현재(기준일) 상태
    cond1_now = close.iloc[-1] > ma_long.iloc[-1]        # 종가 > 200선
    cond2_now = ma_fast.iloc[-1] > ma_slow.iloc[-1]      # 100선 > 150선

    # 최근 lookback 내 신규 돌파
    look = max(1, CONFIG.signal_lookback)
    break1 = _crosses(close, ma_long)                    # 종가가 200선 상향돌파
    cross2 = _crosses(ma_fast, ma_slow)                  # 100선이 150선 골든크로스
    break1_recent = break1.iloc[-look:].any(axis=0)
    cross2_recent = cross2.iloc[-look:].any(axis=0)

    # 두 조건 모두 충족 + 둘 중 하나가 최근 신규 돌파(셋업 완성)
    selected = cond1_now & cond2_now & (break1_recent | cross2_recent)
    tickers = [t for t, ok in selected.items() if bool(ok)]
    return tickers, base_date


def build_hits(
    close: pd.DataFrame,
    tickers: list[str],
    listing: pd.DataFrame,
) -> list[Hit]:
    """조건 충족 티커들을 정렬된 Hit 리스트로 가공.

    listing : index=code, columns=[name, market, close, change_pct, amount, marketcap]
    """
    close = close.sort_index().astype("float64")
    ma_long = _moving_average(close, CONFIG.ma_long)
    ma_fast = _moving_average(close, CONFIG.ma_fast)
    ma_slow = _moving_average(close, CONFIG.ma_slow)
    break1 = _crosses(close, ma_long)
    cross2 = _crosses(ma_fast, ma_slow)

    last_close = close.iloc[-1]
    prev_close = close.iloc[-2] if len(close) >= 2 else None
    ml, mf, ms = ma_long.iloc[-1], ma_fast.iloc[-1], ma_slow.iloc[-1]
    index = close.index

    def _date_of(ago: int):
        return index[-1 - ago] if ago is not None and ago >= 0 else None

    hits: list[Hit] = []
    for t in tickers:
        if t in listing.index:
            row = listing.loc[t]
            name = str(row.get("name", t))
            market = str(row.get("market", ""))
            tval = float(row.get("amount", 0.0) or 0.0)
            mcap = float(row.get("marketcap", 0.0) or 0.0)
        else:
            row, name, market, tval, mcap = None, t, "", 0.0, 0.0

        # 등락률은 매트릭스에서 직접 계산해 임의 기준일에도 정확하게.
        if prev_close is not None and prev_close.get(t):
            change = (float(last_close[t]) / float(prev_close[t]) - 1) * 100
        elif row is not None:
            change = float(row.get("change_pct", 0.0) or 0.0)
        else:
            change = 0.0

        if CONFIG.min_trading_value and tval < CONFIG.min_trading_value:
            continue

        b_ago = _cross_ago_col(break1[t])
        g_ago = _cross_ago_col(cross2[t])
        hits.append(
            Hit(
                ticker=t,
                name=name,
                market=market,
                close=float(last_close[t]),
                ma_long=float(ml[t]),
                ma_fast=float(mf[t]),
                ma_slow=float(ms[t]),
                break_ago=b_ago,
                gc_ago=g_ago,
                change_pct=change,
                trading_value=tval,
                market_cap=mcap,
                break_date=_date_of(b_ago),
                gc_date=_date_of(g_ago),
            )
        )

    # 셋업이 가장 최근 완성된 종목 우선 → 시가총액 큰 순
    hits.sort(key=lambda h: (h.completion_ago, -h.market_cap))
    return hits
