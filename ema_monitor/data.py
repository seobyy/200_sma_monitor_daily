"""KRX 데이터 수집 + 캐싱 (FinanceDataReader 기반).

설계
----
* 유니버스/스냅샷 : fdr.StockListing("KRX") 1회 호출로 전 종목의
  코드·종목명·시장·당일종가·등락률·거래대금을 한 번에 확보.
* 가격 이력(이동평균용) : 종목별 fdr.DataReader 로 종가 시계열 수집.
  - 최초 1회만 전 종목 백필(수분 소요) → parquet 캐시.
  - 이후 매 영업일은 StockListing 의 '당일 종가' 한 줄만 추가(빠름).
  - 신규 상장 종목만 추가 백필.
"""
from __future__ import annotations

import datetime as dt
import time

import FinanceDataReader as fdr
import pandas as pd
from tqdm import tqdm

from config import CACHE_FILE, CONFIG

_REF_TICKER = "005930"  # 삼성전자: 거래일 캘린더 기준


# ── 유니버스 / 스냅샷 ────────────────────────────────────────
def get_listing() -> pd.DataFrame:
    """필터링된 전 종목 스냅샷.

    Returns DataFrame  index=code(str)
        columns = name, market, close, change_pct, amount
    """
    raw = fdr.StockListing("KRX")
    df = raw.rename(
        columns={
            "Code": "code",
            "Name": "name",
            "Market": "market",
            "Close": "close",
            "ChagesRatio": "change_pct",  # FDR 철자(오타) 그대로
            "Amount": "amount",
        }
    )
    df = df[df["market"].isin(CONFIG.markets)].copy()
    df["code"] = df["code"].astype(str).str.zfill(6)
    df = df.set_index("code")

    # 스팩 / 우선주 제외
    if CONFIG.exclude_spac:
        df = df[~df["name"].str.contains("스팩", na=False)]
    if CONFIG.exclude_preferred:
        df = df[df.index.str.endswith("0")]

    keep = ["name", "market", "close", "change_pct", "amount"]
    return df[[c for c in keep if c in df.columns]]


# ── 거래일 캘린더 ────────────────────────────────────────────
def _trading_days(n: int) -> pd.DatetimeIndex:
    """최근 n 거래일 (오름차순 DatetimeIndex).

    삼성전자 일봉의 거래일 인덱스를 KRX 영업일 캘린더로 사용한다.
    """
    today = dt.date.today()
    start = today - dt.timedelta(days=int(n * 1.9) + 30)
    df = fdr.DataReader(_REF_TICKER, start.strftime("%Y-%m-%d"))
    idx = pd.to_datetime(df.index)
    return idx[-n:]


# ── 캐시 ─────────────────────────────────────────────────────
def _load_cache() -> pd.DataFrame:
    if CACHE_FILE.exists():
        df = pd.read_parquet(CACHE_FILE)
        df.index = pd.to_datetime(df.index)
        return df.sort_index()
    return pd.DataFrame()


def _save_cache(df: pd.DataFrame) -> None:
    df.sort_index().to_parquet(CACHE_FILE)


def _backfill(codes: list[str], start: dt.date) -> dict[str, pd.Series]:
    """종목별 종가 시계열 백필."""
    out: dict[str, pd.Series] = {}
    for code in tqdm(codes, desc="가격 이력 백필", unit="종목"):
        try:
            px = fdr.DataReader(code, start.strftime("%Y-%m-%d"))
            if px is not None and not px.empty and "Close" in px.columns:
                out[code] = px["Close"]
        except Exception:
            pass
        time.sleep(0.05)
    return out


# ── 종가 매트릭스 ────────────────────────────────────────────
def get_close_matrix(
    listing: pd.DataFrame, force_refresh: bool = False
) -> pd.DataFrame:
    """(거래일 × 종목) 종가 매트릭스. index=Timestamp, columns=code."""
    needed = _trading_days(CONFIG.lookback_trading_days)
    latest = needed[-1]
    start_date = needed[0].date()
    codes = list(listing.index)

    cache = pd.DataFrame() if force_refresh else _load_cache()

    # 1) 백필이 필요한 종목 판별
    if cache.empty:
        to_backfill = codes
    else:
        cached_days = set(cache.index)
        missing_days = [d for d in needed if d not in cached_days]
        # 최신일 1개만 빠진 정상적인 일일 갱신이면 백필 불필요
        only_latest_missing = missing_days in ([], [latest])
        new_codes = [c for c in codes if c not in cache.columns]
        to_backfill = new_codes if only_latest_missing else codes

    # 2) 백필 수행
    if to_backfill:
        filled = _backfill(to_backfill, start_date)
        if filled:
            new = pd.DataFrame(filled)
            new.index = pd.to_datetime(new.index)
            cache = new if cache.empty else cache.combine_first(new)

    # 3) 당일 종가를 스냅샷에서 빠르게 보강 (백필이 못 채운 최신일)
    if latest not in cache.index or cache.loc[latest].isna().all():
        snap_close = listing["close"].astype("float64")
        cache.loc[latest] = snap_close

    cache = cache.sort_index()
    _save_cache(cache)

    # 4) 필요한 구간만 반환
    matrix = cache.reindex(needed)
    matrix = matrix.dropna(axis=1, how="all")
    return matrix
