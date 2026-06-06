# 📡 KRX 추세 · 골든크로스 모니터

KOSPI / KOSDAQ 전 종목을 매 영업일 스크리닝하여, 아래 **두 조건을 동시에**
만족하는 종목을 텔레그램으로 보내주는 프로젝트입니다.

마크 미너비니의 **Stage 2 진입** 셋업을 잡습니다.

> **조건 1 (추세)** — 당일 KRX 마감 종가 > **200일 이동평균선**
> **조건 2 (신호)** — **100일선 > 150일선** (단기선이 장기선을 상향 돌파한 상태)

두 조건은 **서로 다른 날** 충족될 수 있습니다. 모니터는 *두 조건이 모두 충족된
상태*가 되고, 그 중 **하나가 오늘(기준일) 새로 돌파**되어 **셋업이 완성된 날**
그 종목을 포착합니다. (예: 골든크로스는 5/30, 200일선 돌파는 오늘 → 오늘 포착)

각 선/룩백/이평방식(SMA·EMA)은 `.env` 로 모두 조정할 수 있습니다.

---

## ✨ 특징

- **FinanceDataReader 기반** — KRX 사이트 변경/캡차에 취약한 `pykrx` 의존성을
  걷어내고, 안정적인 FDR 로 전 종목 데이터를 수집합니다.
- **똑똑한 캐싱** — 가격 이력은 최초 1회만 종목별 백필(약 10~15분),
  이후 매 영업일은 `StockListing` 의 당일 종가 한 줄만 추가하므로 빠릅니다.
  (`data/close_prices.parquet`)
- **벡터화 연산** — 이동평균/골든크로스 판정을 pandas 로 한 번에 계산.
- **감각적인 알림** — 종목명·시장·종가·등락률·골든크로스 신선도(🆕/D-n)·
  200일선 이격도·거래대금을 카드 형태로 정리.
- **운영 친화** — 주말/공휴일 자동 스킵(`--skip-if-closed`), dry-run, 연결 테스트.

---

## 🚀 빠른 시작

### 1) 설치
```powershell
pip install -r requirements.txt
```

### 2) 텔레그램 봇 만들기
1. 텔레그램에서 **@BotFather** 와 대화 → `/newbot` → 토큰 발급
2. 만든 봇과 1회 대화(아무 메시지)한 뒤, **@userinfobot** 등으로 본인 `chat id` 확인
   - 그룹/채널로 받으려면 해당 방에 봇을 초대하고 그 chat id 사용

### 3) 환경설정
```powershell
copy .env.example .env
notepad .env   # TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 입력
```

### 4) 연결 테스트
```powershell
python run.py --test-telegram
```

### 5) 실행
```powershell
python run.py --dry-run    # 전송 없이 콘솔 미리보기 (첫 실행은 백필로 시간 소요)
python run.py              # 스크리닝 후 텔레그램 전송
```

---

## ⚙️ 설정 (`.env`)

| 키 | 기본값 | 설명 |
|----|--------|------|
| `TELEGRAM_BOT_TOKEN` | — | 봇 토큰 (필수) |
| `TELEGRAM_CHAT_ID` | — | 수신 chat id (필수) |
| `MA_LONG` | `200` | 추세 필터용 장기선 |
| `MA_FAST` | `100` | 골든크로스 단기선 |
| `MA_SLOW` | `150` | 골든크로스 장기선 |
| `SIGNAL_LOOKBACK` | `1` | 셋업 완성(둘 중 하나 신규 돌파)을 최근 N영업일까지 인정 (1=오늘만) |
| `MA_TYPE` | `sma` | `sma`(단순) 또는 `ema`(지수) |
| `MARKETS` | `KOSPI,KOSDAQ` | 대상 시장 |
| `EXCLUDE_SPAC` | `true` | 스팩 제외 |
| `EXCLUDE_PREFERRED` | `true` | 우선주 제외(코드 끝자리≠0) |
| `MIN_TRADING_VALUE` | `0` | 최소 거래대금(원) 필터, 0=미적용 |
| `MIN_MARKET_CAP` | `100000000000` | 최소 시가총액(원) 필터, 0=미적용 (기본 1000억) |

> 💡 오늘 정확히 셋업이 완성된 종목은 날에 따라 0개일 수 있습니다.
> 더 많은 후보를 보려면 `SIGNAL_LOOKBACK` 을 3~5 정도로 키워보세요.

---

## ☁️ 매 영업일 자동 실행 — GitHub Actions (추천)

내 PC가 꺼져 있어도 GitHub 서버가 매일 돌려줍니다. 워크플로는
`.github/workflows/monitor.yml` 에 포함되어 있습니다.

1. **GitHub에 푸시**
   ```powershell
   git remote add origin https://github.com/<사용자명>/<레포명>.git
   git push -u origin main
   ```
2. **Secrets 등록** — 레포 → *Settings* → *Secrets and variables* → *Actions* →
   *New repository secret* 으로 아래 2개 추가
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. **동작 확인** — *Actions* 탭 → "KRX 추세·골든크로스 모니터" →
   *Run workflow* 로 수동 실행(테스트). 정상이면 매 평일 자동 실행됩니다.

- 실행 시각: `cron: "0 9 * * 1-5"` = **매주 월~금 18:00 KST**(09:00 UTC).
  바꾸려면 yml 의 cron 을 수정 (UTC 기준).
- **가격 캐시**(`actions/cache`)로 첫 실행만 전 종목 백필하고, 이후는 빠르게 갱신.
- 공휴일은 `--skip-if-closed` 로 자동 스킵됩니다.

> ⚠️ GitHub cron 은 서버 부하 시 수~수십 분 지연될 수 있습니다(시간 엄수 X).
> 무료 사용량: public 레포 무제한, private 레포도 월 2,000분으로 충분합니다.

---

## ⏰ (대안) 내 PC에서 자동 실행 — Windows 작업 스케줄러

1. `run_daily.bat` 가 장 마감 후 실행되도록 등록합니다.
2. **작업 스케줄러** → *작업 만들기*
   - 트리거: 매주, 월~금, 시작 시간 `18:00`
   - 동작: 프로그램 시작 → `run_daily.bat` (시작 위치: 프로젝트 폴더)
3. `--skip-if-closed` 덕분에 임시공휴일이면 자동으로 아무 작업 없이 종료합니다.
4. 로그는 `data/run.log` 에 누적됩니다.

PowerShell 한 줄 등록 예:
```powershell
schtasks /Create /TN "KRX_Monitor" /TR "%CD%\run_daily.bat" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 18:00
```

---

## 🗂 구조

```
200_ema_monitor/
├── run.py                # 엔트리포인트 (CLI)
├── run_daily.bat         # 스케줄러용 배치
├── config.py             # .env 설정 로딩
├── requirements.txt
├── .env.example
└── ema_monitor/
    ├── data.py           # FDR 수집 + parquet 캐시
    ├── screener.py       # 이동평균/골든크로스 판정
    ├── notifier.py       # 텔레그램 메시지 구성·전송
    └── pipeline.py       # 수집→스크리닝→알림 오케스트레이션
```

---

## 🧪 CLI 옵션

```
python run.py                 # 스크리닝 + 텔레그램 전송
python run.py --dry-run       # 전송 없이 콘솔 미리보기
python run.py --refresh       # 캐시 무시하고 전체 재수집
python run.py --skip-if-closed# 거래일 아니면 즉시 종료(스케줄러용)
python run.py --test-telegram # 연결 테스트 메시지 전송
python run.py -v              # 상세 로그
```

---

## ⚠️ 참고

- 이 프로젝트는 **투자 정보 제공/학습용**이며 투자 권유가 아닙니다.
- 첫 실행 또는 `--refresh` 시 전 종목 가격 이력을 받아오므로 시간이 걸립니다.
  이후 실행은 캐시 증분 갱신으로 빠릅니다.
- "이동평균선"은 한국 증시 관례에 따라 기본값을 **단순이동평균(SMA)** 으로
  두었습니다. 지수이동평균을 원하면 `MA_TYPE=ema`.
