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
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import FinanceDataReader as fdr
import pandas as pd
from tqdm import tqdm

from config import CACHE_FILE, CONFIG

_REF_TICKER = "005930"  # 삼성전자: 거래일 캘린더 기준


def _get_env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


# ── 유니버스 / 스냅샷 ────────────────────────────────────────
def get_listing() -> pd.DataFrame:
    """필터링된 전 종목 스냅샷.

    Returns DataFrame  index=code(str)
        columns = name, market, close, change_pct, amount, marketcap
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
            "Marcap": "marketcap",        # 시가총액(원)
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

    # 시가총액 필터
    if CONFIG.min_market_cap and "marketcap" in df.columns:
        mc = pd.to_numeric(df["marketcap"], errors="coerce")
        df = df[mc >= CONFIG.min_market_cap]

    keep = ["name", "market", "close", "change_pct", "amount", "marketcap"]
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


def _fetch_one(code: str, start: str, retries: int = 3):
    """단일 종목 종가 시계열 (실패 시 재시도)."""
    for attempt in range(retries):
        try:
            px = fdr.DataReader(code, start)
            if px is not None and not px.empty and "Close" in px.columns:
                return code, px["Close"]
            return code, None
        except Exception:
            time.sleep(0.4 * (attempt + 1))  # throttle 대비 백오프
    return code, None


def _merge(cache: pd.DataFrame, filled: dict[str, pd.Series]) -> pd.DataFrame:
    if not filled:
        return cache
    new = pd.DataFrame(filled)
    new.index = pd.to_datetime(new.index)
    # 새로 받은 실데이터(수정주가)가 기존 값(스냅샷 보강치)보다 우선
    return new if cache.empty else new.combine_first(cache)


def _backfill_into_cache(
    cache: pd.DataFrame, codes: list[str], start: dt.date
) -> pd.DataFrame:
    """종목별 종가를 병렬 수집하고, 중간중간 캐시에 저장한다.

    중간 저장 덕분에 도중에 끊겨도 다음 실행에서 받은 만큼 이어받는다.
    """
    start_str = start.strftime("%Y-%m-%d")
    workers = max(1, _get_env_int("BACKFILL_WORKERS", 8))
    save_every = max(50, _get_env_int("BACKFILL_SAVE_EVERY", 300))

    buffer: dict[str, pd.Series] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_fetch_one, c, start_str): c for c in codes}
        for fut in tqdm(as_completed(futures), total=len(futures),
                        desc="가격 이력 백필", unit="종목"):
            code, s = fut.result()
            if s is not None:
                buffer[code] = s
            done += 1
            if done % save_every == 0 and buffer:
                cache = _merge(cache, buffer)
                _save_cache(cache)
                buffer = {}

    if buffer:
        cache = _merge(cache, buffer)
        _save_cache(cache)
    return cache


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
        # 캐시에 아예 없는 날뿐 아니라 값이 거의 비어 있는 날도 결손으로 본다.
        # (신규상장 종목만 백필된 날은 그 종목 외 전부 NaN 인 '구멍' 행이 남아
        #  rolling MA 전체를 NaN 으로 만든다 → 전 종목 재수집으로 복구)
        row_fill = cache.reindex(needed).notna().mean(axis=1)
        missing_days = [d for d in needed if row_fill.loc[d] < 0.5]
        # 최신일 1개만 빠진 정상적인 일일 갱신이면 백필 불필요
        only_latest_missing = missing_days in ([], [latest])
        new_codes = [c for c in codes if c not in cache.columns]
        to_backfill = new_codes if only_latest_missing else codes

    # 2) 백필 수행 (병렬 + 중간 저장)
    if to_backfill:
        cache = _backfill_into_cache(cache, to_backfill, start_date)

    # 3) 당일 종가를 스냅샷에서 빠르게 보강 (백필이 못 채운 최신일).
    #    신규상장 백필 직후엔 최신일 행이 그 종목만 채워진 채 존재할 수 있으므로
    #    행 유무가 아니라 셀 단위로 NaN 만 스냅샷 종가로 메운다.
    snap_close = listing["close"].astype("float64")
    if latest not in cache.index:
        cache.loc[latest] = snap_close
    else:
        cache.loc[latest] = cache.loc[latest].fillna(snap_close)

    cache = cache.sort_index()
    _save_cache(cache)

    # 4) 필요한 구간만 반환
    matrix = cache.reindex(needed)
    matrix = matrix.dropna(axis=1, how="all")
    return matrix
