"""텔레그램 메시지 구성·전송.

Bot API sendMessage 를 사용. MarkdownV2 대신 HTML 파싱모드를 사용해
종목명에 포함될 수 있는 특수문자 이스케이프 부담을 줄인다.

메시지 레이아웃 (가독성 우선)
----------------------------
헤더  : 기준일 · 포착 종목 수 · 시장별 분포
본문  : **신호 유형별로 묶어서**, 종목당 2줄
        1줄 = 순번 · 종목명(차트 링크) · 코드 · 시장
        2줄 = 현재가 · 등락률 · 이격도 · 시가총액
푸터  : 조건/용어 2줄 요약

조건식(종가>MA200, MA100>MA150)은 스크리닝에서 이미 보장되므로 종목마다
반복하지 않고, "무엇이 새로 터졌는지"만 그룹 제목으로 한 번 보여준다.
"""
from __future__ import annotations

import html
from collections import Counter

import pandas as pd
import requests

from config import CONFIG
from ema_monitor.screener import Hit

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_LEN = 3900  # 텔레그램 한도(4096) - 파트 표기 여유
RULE = "━" * 13
INDENT = "　"  # 전각 공백: 한글 폭에 맞춰 2번째 줄을 들여쓴다

_WEEKDAYS = "월화수목금토일"
_MARKET_LABEL = {"KOSPI": "코스피", "KOSDAQ": "코스닥", "KONEX": "코넥스"}


# ── 포맷 헬퍼 ────────────────────────────────────────────────
def _fmt_won(value: float) -> str:
    """원 단위 금액을 억/조 단위로."""
    jo = 1_0000_0000_0000
    eok = 1_0000_0000
    if value >= 10 * jo:
        return f"{value / jo:,.0f}조"
    if value >= jo:
        return f"{value / jo:.1f}조"
    if value >= eok:
        return f"{value / eok:,.0f}억"
    return f"{value:,.0f}원"


def _ma(window: int) -> str:
    """이동평균선 표기. MA_TYPE 에 따라 '200선' / '200EMA'."""
    return f"{window}EMA" if CONFIG.ma_type == "ema" else f"{window}선"


def _market(name: str) -> str:
    return _MARKET_LABEL.get(str(name).upper(), str(name))


def _tradingview(ticker: str) -> str:
    """TradingView 차트 URL (KRX 심볼)."""
    return f"https://www.tradingview.com/chart/?symbol=KRX%3A{ticker}"


def _emoji_change(pct: float) -> str:
    if pct > 0:
        return "🔺"
    if pct < 0:
        return "🔻"
    return "▪️"


# ── 신호 유형 분류 ───────────────────────────────────────────
def _trigger(h: Hit) -> str:
    """셋업을 완성시킨 신호가 무엇인지."""
    look = max(1, CONFIG.signal_lookback)
    fresh_break = 0 <= h.break_ago < look   # 종가가 장기선 신규 돌파
    fresh_gc = 0 <= h.gc_ago < look         # 중기선 신규 골든크로스
    if fresh_break and fresh_gc:
        return "both"
    if fresh_break:
        return "break"
    if fresh_gc:
        return "gc"
    return "hold"  # 안전망(정상 스크리닝에서는 나오지 않음)


_TRIGGER_ORDER = ("both", "break", "gc", "hold")


def _group_title(kind: str, count: int) -> str:
    long_, fast, slow = _ma(CONFIG.ma_long), _ma(CONFIG.ma_fast), _ma(CONFIG.ma_slow)
    title = {
        "both": f"🚀 <b>{long_} 돌파 + 골든크로스</b> 동시 발생",
        "break": f"⚡ <b>{long_} 돌파</b>",
        "gc": f"🔀 <b>골든크로스</b> {fast}↗{slow}",
        "hold": "✅ <b>조건 충족</b>",
    }[kind]
    return f"{title} · <b>{count}</b>종목"


# ── 메시지 구성 ──────────────────────────────────────────────
def _entry(no: int, h: Hit) -> str:
    """종목 1건 = 2줄."""
    name = html.escape(h.name)
    ago = h.completion_ago
    when = "" if ago <= 0 else f" · {ago}일 전"
    return (
        f"<b>{no}.</b> <a href=\"{_tradingview(h.ticker)}\"><b>{name}</b></a>"
        f" <code>{h.ticker}</code> · {_market(h.market)}\n"
        f"{INDENT}{h.close:,.0f}원 {_emoji_change(h.change_pct)}{h.change_pct:+.2f}%"
        f" · 이격 {h.gap_pct:+.1f}% · 시총 {_fmt_won(h.market_cap)}{when}"
    )


def _footer() -> str:
    look = max(1, CONFIG.signal_lookback)
    fresh = "오늘 신규 완성" if look == 1 else f"최근 {look}영업일 내 신규 완성"
    return (
        f"{RULE}\n"
        f"🔎 조건: 종가&gt;{_ma(CONFIG.ma_long)} &amp; "
        f"{_ma(CONFIG.ma_fast)}&gt;{_ma(CONFIG.ma_slow)} · {fresh}\n"
        f"💡 이격 = 종가가 {_ma(CONFIG.ma_long)}보다 몇 % 위인지 "
        f"(작을수록 눌림 구간)\n"
        f"👉 종목명을 누르면 차트로 이동합니다"
    )


def build_message(hits: list[Hit], base_date) -> str:
    ts = pd.Timestamp(base_date)
    date_fmt = f"{ts.strftime('%Y.%m.%d')}({_WEEKDAYS[ts.weekday()]})"

    if not hits:
        return (
            f"📈 <b>Stage 2 진입 신호</b>\n"
            f"🗓 {date_fmt} 종가 기준\n\n"
            f"오늘 새로 완성된 셋업이 없습니다. 🤙"
        )

    dist = " · ".join(
        f"{m} {n}" for m, n in Counter(_market(h.market) for h in hits).most_common()
    )
    blocks = [
        f"📈 <b>Stage 2 진입 신호</b>\n"
        f"🗓 {date_fmt} 종가 기준\n"
        f"✨ <b>{len(hits)}종목</b> 포착 · {dist}\n"
        f"{RULE}"
    ]

    # 신호 유형별로 묶되, 번호는 전체 순번을 이어서 매긴다.
    groups: dict[str, list[Hit]] = {}
    for h in hits:
        groups.setdefault(_trigger(h), []).append(h)

    no = 0
    for kind in _TRIGGER_ORDER:
        members = groups.get(kind)
        if not members:
            continue
        blocks.append(_group_title(kind, len(members)))
        for h in members:
            no += 1
            blocks.append(_entry(no, h))

    blocks.append(_footer())
    return "\n\n".join(blocks)


# ── 전송 ─────────────────────────────────────────────────────
def _chunk(text: str, limit: int = MAX_LEN) -> list[str]:
    """빈 줄(블록) 경계에서 분할해 종목 카드가 중간에 잘리지 않게 한다."""
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    cur = ""
    for block in text.split("\n\n"):
        cand = f"{cur}\n\n{block}" if cur else block
        if len(cand) > limit and cur:
            parts.append(cur)
            cur = block
        else:
            cur = cand
    if cur:
        parts.append(cur)

    # 블록 하나가 한도를 넘는 예외 상황은 줄 단위로 한 번 더 자른다.
    out: list[str] = []
    for part in parts:
        while len(part) > limit:
            cut = part.rfind("\n", 0, limit)
            cut = cut if cut > 0 else limit
            out.append(part[:cut])
            part = part[cut:].lstrip("\n")
        out.append(part)
    return out


def send(text: str) -> None:
    CONFIG.validate_telegram()
    url = TELEGRAM_API.format(token=CONFIG.telegram_bot_token)
    parts = _chunk(text)
    total = len(parts)
    for i, part in enumerate(parts, 1):
        body = part if total == 1 else f"{part}\n\n<i>({i}/{total})</i>"
        resp = requests.post(
            url,
            json={
                "chat_id": CONFIG.telegram_chat_id,
                "text": body,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"텔레그램 전송 실패: {resp.status_code} {resp.text}")


def notify(hits: list[Hit], base_date: str) -> None:
    send(build_message(hits, base_date))
