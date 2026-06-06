@echo off
REM ── KRX 추세·골든크로스 모니터 일일 실행 (Windows 작업 스케줄러용) ──
REM 장 마감 후(예: 평일 18:00) 실행되도록 등록하세요.

cd /d "%~dp0"

REM 가상환경을 쓴다면 아래 주석 해제
REM call .venv\Scripts\activate.bat

python run.py --skip-if-closed >> "%~dp0data\run.log" 2>&1
