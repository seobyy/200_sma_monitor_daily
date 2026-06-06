"""전체 파이프라인 오케스트레이션: 수집 → 스크리닝 → 알림."""
from __future__ import annotations

import logging

from config import CONFIG
from ema_monitor import data, notifier, screener
from ema_monitor.screener import Hit

log = logging.getLogger("ema_monitor")


def run(
    dry_run: bool = False,
    force_refresh: bool = False,
    as_of: str | None = None,
) -> list[Hit]:
    """모니터링 1회 실행.

    Parameters
    ----------
    dry_run : True 면 텔레그램 전송 없이 콘솔 출력만.
    force_refresh : True 면 캐시 무시하고 전체 재수집.
    as_of : "YYYY-MM-DD". 지정 시 해당 일자(이하 마지막 거래일)를 기준일로
            스크리닝한다. None 이면 가장 최근 거래일.

    Returns
    -------
    조건 충족 Hit 리스트
    """
    import pandas as pd

    log.info("유니버스 수집 (markets=%s)", ",".join(CONFIG.markets))
    listing = data.get_listing()
    log.info("대상 종목 수: %d", len(listing))

    log.info("종가 매트릭스 수집/캐시 갱신")
    close = data.get_close_matrix(listing, force_refresh=force_refresh)

    # 스크리닝 대상을 현재 유니버스로 제한 (캐시에 남은 비대상 종목 제외).
    universe_cols = [c for c in close.columns if c in listing.index]
    close = close[universe_cols]
    log.info("유니버스 정합 후 매트릭스 종목 수: %d", close.shape[1])

    if as_of:
        cutoff = pd.Timestamp(as_of)
        close = close.loc[close.index <= cutoff]
        log.info("기준일 지정: %s 이하로 절단 (마지막 거래일 %s)",
                 as_of, close.index[-1].date() if len(close) else "없음")

    if close.empty or len(close) < CONFIG.ma_long:
        raise RuntimeError(
            f"데이터 부족: {len(close)} 거래일 (필요 {CONFIG.ma_long}+). "
            "기준일이 너무 과거이거나 수집 실패일 수 있습니다."
        )

    tickers, base_date = screener.screen(close)
    log.info("조건 충족: %d 종목", len(tickers))

    hits = screener.build_hits(close, tickers, listing)
    log.info("최종 포착: %d 종목 (기준일 %s)",
             len(hits), base_date.strftime("%Y-%m-%d"))

    if dry_run:
        print(notifier.build_message(hits, base_date))
    else:
        notifier.notify(hits, base_date)
        log.info("텔레그램 전송 완료")

    return hits
