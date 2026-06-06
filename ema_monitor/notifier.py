"""텔레그램 메시지 전송.

Bot API sendMessage 를 사용. MarkdownV2 대신 HTML 파싱모드를 사용해
종목명에 포함될 수 있는 특수문자 이스케이프 부담을 줄인다.
"""
from __future__ import annotations

import html

import pandas as pd
import requests

from config import CONFIG
from ema_monitor.screener import Hit

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_LEN = 4000  # 텔레그램 메시지 길이 한도(4096) 여유


def _fmt_won(value: float) -> str:
    """원 단위 거래대금을 억/조 단위로."""
    if value >= 1_0000_0000_0000:
        return f"{value / 1_0000_0000_0000:.1f}조"
    if value >= 1_0000_0000:
        return f"{value / 1_0000_0000:.0f}억"
    return f"{value:,.0f}"


def _when(date, ago: int) -> str:
    """돌파 시점을 사람이 읽기 좋게. (오늘 / 5.30 (6일전) / 이전부터)"""
    if ago is None or ago < 0 or date is None:
        return "이전부터 충족"
    ts = pd.Timestamp(date)
    d = f"{ts.month}.{ts.day}"  # 5.30 형식 (크로스플랫폼)
    if ago == 0:
        return f"오늘 ({d}) 🆕"
    return f"{d} ({ago}일전)"


def _emoji_change(pct: float) -> str:
    if pct > 0:
        return "🔺"
    if pct < 0:
        return "🔻"
    return "▪️"


def build_message(hits: list[Hit], base_date) -> str:
    date_fmt = pd.Timestamp(base_date).strftime("%Y.%m.%d")

    header = (
        f"📈 <b>Stage 2 진입 모니터</b>\n"
        f"🗓 기준일 <b>{date_fmt}</b> (KRX 종가)\n"
        f"🎯 종가&gt;MA{CONFIG.ma_long} + MA{CONFIG.ma_fast}↗MA{CONFIG.ma_slow}, "
        f"오늘 셋업 완성\n"
    )

    if not hits:
        return header + "\n오늘 셋업이 완성된 종목이 없습니다. 🤙"

    header += f"✨ <b>{len(hits)}개</b> 종목 포착\n" + "─" * 18 + "\n"

    lines = []
    for i, h in enumerate(hits, 1):
        name = html.escape(h.name)
        gap = h.gap_pct  # 장기선 이격도
        lines.append(
            f"{i}. <b>{name}</b> "
            f"<code>{h.ticker}</code> · {h.market}\n"
            f"   {_emoji_change(h.change_pct)} {h.close:,.0f}원 "
            f"({h.change_pct:+.2f}%)\n"
            f"   ① 종가&gt;MA{CONFIG.ma_long} 돌파: {_when(h.break_date, h.break_ago)}\n"
            f"   ② MA{CONFIG.ma_fast}↗MA{CONFIG.ma_slow} GC: {_when(h.gc_date, h.gc_ago)}\n"
            f"   MA{CONFIG.ma_long} 이격 {gap:+.1f}% · "
            f"시총 {_fmt_won(h.market_cap)} · "
            f"거래대금 {_fmt_won(h.trading_value)}"
        )

    return header + "\n".join(lines)


def _chunk(text: str, limit: int = MAX_LEN) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    if cur:
        chunks.append(cur)
    return chunks


def send(text: str) -> None:
    CONFIG.validate_telegram()
    url = TELEGRAM_API.format(token=CONFIG.telegram_bot_token)
    for part in _chunk(text):
        resp = requests.post(
            url,
            json={
                "chat_id": CONFIG.telegram_chat_id,
                "text": part,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"텔레그램 전송 실패: {resp.status_code} {resp.text}")


def notify(hits: list[Hit], base_date: str) -> None:
    send(build_message(hits, base_date))
