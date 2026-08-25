from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
import os

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

START = date(2000, 1, 1)
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
MODELS_DIR = ROOT / "data" / "models"
REPORTS_DIR = ROOT / "data" / "reports"
EVENTS_PATH = ROOT / "data" / "events.json"
WORKBOOK_DIR = ROOT / "data" / "workbook"
WORKBOOK_PATH = WORKBOOK_DIR / "macro_ledger.xlsx"
BRIEF_HTML = REPORTS_DIR / "daily_brief.html"
APP_DIR = REPORTS_DIR / "app"

for _d in (RAW_DIR, PROCESSED_DIR, MODELS_DIR, REPORTS_DIR, WORKBOOK_DIR, APP_DIR):
    _d.mkdir(parents=True, exist_ok=True)



@dataclass(frozen=True)
class Series:
    key: str
    label_ko: str
    group: str
    source: str
    ticker: str
    frequency: str = "daily"
    unit: str = "price"
    note: str = ""


# group: asset / rates / fx / inflation / risk / sector
UNIVERSE: tuple[Series, ...] = (
    Series("kospi", "코스피", "asset", "yahoo", "^KS11", note="한국 대형주"),
    Series("kosdaq", "코스닥", "asset", "yahoo", "^KQ11", note="한국 성장/중소형"),
    Series("nasdaq", "나스닥 종합", "asset", "yahoo", "^IXIC"),
    Series("sp500", "S&P 500", "asset", "yahoo", "^GSPC"),
    Series("gold", "금 선물(근월)", "asset", "yahoo", "GC=F", note="금현물 대용"),
    Series("bitcoin", "비트코인", "asset", "yahoo", "BTC-USD", note="2014-09 이후"),
    Series("usdkkrw", "원/달러", "fx", "yahoo", "KRW=X", unit="krw_per_usd"),
    Series("vix", "VIX", "risk", "yahoo", "^VIX", unit="index"),
    Series("dxy", "달러인덱스", "fx", "yahoo", "DX-Y.NYB", unit="index"),
    Series("us_3m", "미국 3개월 국채", "rates", "fred", "DGS3MO", unit="percent"),
    Series("us_2y", "미국 2년 국채", "rates", "fred", "DGS2", unit="percent"),
    Series("us_10y", "미국 10년 국채", "rates", "fred", "DGS10", unit="percent"),
    Series("us_ffr", "미국 기준금리", "rates", "fred", "FEDFUNDS", frequency="monthly", unit="percent"),
    Series("us_cpi", "미국 CPI", "inflation", "fred", "CPIAUCSL", frequency="monthly", unit="index"),
    Series("kr_call", "한국 기준금리", "rates", "fred", "IRSTCI01KRM156N", frequency="monthly", unit="percent", note="한은 기준금리. BOK_API_KEY면 ECOS 일별, 없으면 BIS 일별. 최후 FRED 콜금리"),
    Series("kr_10y", "한국 장기국채(10년)", "rates", "fred", "IRLTLT01KRM156N", frequency="monthly", unit="percent"),
    Series("kr_cpi", "한국 CPI", "inflation", "fred", "KORCPIALLMINMEI", frequency="monthly", unit="index", note="FRED OECD 월간은 2023-11 이후 단절될 수 있음"),
    Series("kr_infl_wb", "한국 인플레(연간, WB)", "inflation", "fred", "FPCPITOTLZGKOR", frequency="yearly", unit="percent", note="월간 CPI가 끊기면 전년비 대체"),
    Series("us_semi", "미국 반도체(SMH)", "sector", "yahoo", "SMH", note="필라델피아 반도체 상장 ETF"),
    Series("us_bio", "미국 바이오(IBB)", "sector", "yahoo", "IBB"),
    Series("us_finance", "미국 금융(XLF)", "sector", "yahoo", "XLF"),
    Series("us_robotics", "미국 로봇(BOTZ)", "sector", "yahoo", "BOTZ", note="2016-09 이후"),
    Series("kr_semi", "한국 반도체(SK하이닉스)", "sector", "yahoo", "000660.KS", note="섹터 대용"),
    Series("kr_bio", "한국 바이오(셀트리온)", "sector", "yahoo", "068270.KS", note="섹터 대용, 2005-"),
    Series("kr_finance", "한국 금융(신한지주)", "sector", "yahoo", "055550.KS", note="섹터 대용"),
    Series("kr_ship", "한국 조선(HD한국조선해양)", "sector", "yahoo", "009540.KS", note="섹터 대용"),
    Series("kr_robot", "한국 자동화(LS일렉트릭)", "sector", "yahoo", "010120.KS", note="로봇/자동화 대용"),
)

FDR_FALLBACK = {
    "kospi": "KS11",
    "kosdaq": "KQ11",
    "nasdaq": "IXIC",
    "sp500": "US500",
    "usdkkrw": "USD/KRW",
    "bitcoin": "BTC/USD",
}

YAHOO_FALLBACK = {
    "kospi": "KS11.KS",
    "kosdaq": "KQ11.KS",
}

ASSET_KEYS = ("gold", "bitcoin", "kospi", "kosdaq", "nasdaq")
MARKET_KEYS = ("kospi", "kosdaq", "nasdaq")
SECTOR_KEYS = (
    "us_semi",
    "us_bio",
    "us_finance",
    "us_robotics",
    "kr_semi",
    "kr_bio",
    "kr_finance",
    "kr_ship",
    "kr_robot",
)

FORWARD_DAYS = 21
MIN_HISTORY_DAYS = 400
RANDOM_STATE = 42

# 코스피 선택 시 보여주는 대표 종목 (섹터 대용과 동일 시리즈)
KOSPI_STOCKS = {
    "kr_semi": {"ticker": "000660.KS", "name": "SK하이닉스", "sector": "반도체"},
    "kr_bio": {"ticker": "068270.KS", "name": "셀트리온", "sector": "바이오"},
    "kr_finance": {"ticker": "055550.KS", "name": "신한지주", "sector": "금융"},
    "kr_ship": {"ticker": "009540.KS", "name": "HD한국조선해양", "sector": "조선"},
    "kr_robot": {"ticker": "010120.KS", "name": "LS일렉트릭", "sector": "로봇/자동화"},
}


def series_by_key() -> dict[str, Series]:
    return {s.key: s for s in UNIVERSE}


def gemini_api_key() -> str | None:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    return key or None


def bok_api_key() -> str | None:
    for name in ("BOK_API_KEY", "BOK_API_KEY", "ECOS_KEY"):
        key = os.getenv(name, "").strip()
        if key:
            return key
    return None


def ted_accounts() -> list[dict[str, str]]:
    accounts: list[dict[str, str]] = []
    manager_id = os.getenv("TED_MANAGER_ID", "").strip()
    manager_pw = os.getenv("TED_MANAGER_PW", "").strip()
    if manager_id and manager_pw:
        accounts.append({"role": "Manager", "id": manager_id, "pw": manager_pw})
    user_id = os.getenv("TED_USER_ID", "").strip()
    user_pw = os.getenv("TED_USER_PW", "").strip()
    if user_id and user_pw:
        accounts.append({"role": "User", "id": user_id, "pw": user_pw})
    return accounts


def mail_settings() -> dict[str, str]:
    return {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": os.getenv("SMTP_PORT", "587").strip(),
        "user": os.getenv("SMTP_USER", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", "").strip(),
        "mail_from": os.getenv("MAIL_FROM", "").strip(),
        "mail_to": os.getenv("MAIL_TO", "").strip(),
    }
