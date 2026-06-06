#!/usr/bin/env python
"""KOSPI/KOSDAQ 추세·골든크로스 모니터 실행 엔트리포인트.

사용 예:
    python run.py                 # 스크리닝 후 텔레그램 전송
    python run.py --dry-run       # 전송 없이 콘솔 미리보기
    python run.py --refresh       # 캐시 무시하고 전체 재수집
    python run.py --test-telegram # 텔레그램 연결 테스트 메시지 1건 전송
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys

from config import CONFIG
from ema_monitor import data, notifier, pipeline

# Windows 콘솔(cp949)에서도 이모지/한글이 깨지지 않도록 UTF-8 로 강제
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def main() -> int:
    parser = argparse.ArgumentParser(description="KRX 추세·골든크로스 모니터")
    parser.add_argument("--dry-run", action="store_true",
                        help="텔레그램 전송 없이 콘솔 출력")
    parser.add_argument("--refresh", action="store_true",
                        help="캐시 무시하고 전체 재수집")
    parser.add_argument("--test-telegram", action="store_true",
                        help="텔레그램 연결 테스트")
    parser.add_argument("--skip-if-closed", action="store_true",
                        help="오늘이 거래일이 아니면(주말/공휴일) 아무것도 안 하고 종료")
    parser.add_argument("--as-of", metavar="YYYY-MM-DD", default=None,
                        help="지정 일자(이하 마지막 거래일)를 기준으로 스크리닝")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.test_telegram:
        notifier.send("✅ <b>모니터 연결 테스트</b>\n정상 동작합니다.")
        print("테스트 메시지 전송 완료")
        return 0

    if args.skip_if_closed:
        latest = data._trading_days(1)[-1].date()
        if latest != dt.date.today():
            logging.info("오늘(%s)은 거래일이 아님 (최근 거래일 %s). 종료.",
                         dt.date.today(), latest)
            return 0

    try:
        hits = pipeline.run(
            dry_run=args.dry_run,
            force_refresh=args.refresh,
            as_of=args.as_of,
        )
    except Exception as exc:  # noqa: BLE001
        logging.error("실행 실패: %s", exc)
        # 운영 중 오류도 텔레그램으로 알리고 싶으면 아래 주석 해제
        # if not args.dry_run and CONFIG.telegram_bot_token:
        #     try:
        #         notifier.send(f"⚠️ 모니터 오류: {exc}")
        #     except Exception:
        #         pass
        return 1

    print(f"완료: {len(hits)}개 종목 포착")
    return 0


if __name__ == "__main__":
    sys.exit(main())
