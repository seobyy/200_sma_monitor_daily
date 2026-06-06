"""전체 파이프라인 오케스트레이션: 수집 → 스크리닝 → 알림."""
from __future__ import annotations

import logging

from config import CONFIG
from ema_monitor import data, notifier, screener
from ema_monitor.screener import Hit

log = logging.getLogger("ema_monitor")


def run(dry_run: bool = False, force_refresh: bool = False) -> list[Hit]:
    """모니터링 1회 실행.

    Parameters
    ----------
    dry_run : True 면 텔레그램 전송 없이 콘솔 출력만.
    force_refresh : True 면 캐시 무시하고 전체 재수집.

    Returns
    -------
    조건 충족 Hit 리스트
    """
    log.info("유니버스 수집 (markets=%s)", ",".join(CONFIG.markets))
    listing = data.get_listing()
    log.info("대상 종목 수: %d", len(listing))

    log.info("종가 매트릭스 수집/캐시 갱신")
    close = data.get_close_matrix(listing, force_refresh=force_refresh)
    if close.empty or len(close) < CONFIG.ma_long:
        raise RuntimeError(
            f"데이터 부족: {len(close)} 거래일 (필요 {CONFIG.ma_long}+). "
            "장 시작 전이거나 수집 실패일 수 있습니다."
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
