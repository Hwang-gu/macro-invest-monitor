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
    Series("dow", "다우존스", "asset", "yahoo", "^DJI", note="Dow Jones Industrial Average"),
    Series("gold", "금 선물(근월)", "asset", "yahoo", "GC=F", note="금현물 대용"),
    Series("bitcoin", "비트코인", "asset", "yahoo", "BTC-USD", note="2014-09 이후"),
    Series("usdkkrw", "원/달러", "fx", "yahoo", "KRW=X", unit="krw_per_usd"),
    Series("usdjpy", "엔/달러", "fx", "yahoo", "JPY=X", unit="jpy_per_usd"),
    Series("vix", "VIX", "risk", "yahoo", "^VIX", unit="index"),
    Series("dxy", "달러인덱스", "fx", "yahoo", "DX-Y.NYB", unit="index"),
    Series("us_3m", "미국 3개월 국채", "rates", "fred", "DGS3MO", unit="percent"),
    Series("us_2y", "미국 2년 국채", "rates", "fred", "DGS2", unit="percent"),
    Series("us_10y", "미국 10년 국채", "rates", "fred", "DGS10", unit="percent"),
    Series("us_ffr", "미국 기준금리", "rates", "fred", "FEDFUNDS", frequency="monthly", unit="percent", note="월간. 일별 정렬 시 21거래일 발표 시차"),
    Series("us_cpi", "미국 CPI", "inflation", "fred", "CPIAUCSL", frequency="monthly", unit="index", note="월간. 일별 정렬 시 21거래일 발표 시차"),
    Series("kr_call", "한국 기준금리", "rates", "fred", "IRSTCI01KRM156N", frequency="monthly", unit="percent", note="한은 기준금리. BOK_API_KEY면 ECOS 일별, 없으면 BIS 일별. 최후 FRED 월간. 월간일 때만 21거래일 시차"),
    Series("kr_10y", "한국 장기국채(10년)", "rates", "fred", "IRLTLT01KRM156N", frequency="monthly", unit="percent", note="월간. 일별 정렬 시 21거래일 발표 시차"),
    Series("kr_cpi", "한국 CPI", "inflation", "fred", "KORCPIALLMINMEI", frequency="monthly", unit="index", note="FRED OECD 월간은 2023-11 이후 단절될 수 있음. 연간 인플레로 대체하지 않음"),
    Series("us_semi", "미국 반도체(SMH)", "sector", "yahoo", "SMH", note="필라델피아 반도체 상장 ETF"),
    Series("us_bio", "미국 바이오(IBB)", "sector", "yahoo", "IBB"),
    Series("us_finance", "미국 금융(XLF)", "sector", "yahoo", "XLF"),
    Series("us_robotics", "미국 로봇(BOTZ)", "sector", "yahoo", "BOTZ", note="2016-09 이후"),
    Series("kr_semi", "한국 반도체(KODEX 반도체)", "sector", "yahoo", "091160.KS", note="KRX 반도체 ETF, 2006-06 상장"),
    Series("kr_bio", "한국 바이오(TIGER 헬스케어)", "sector", "yahoo", "143860.KS", note="KRX 헬스케어 ETF, 2011-07 상장"),
    Series("kr_finance", "한국 금융(KODEX 은행)", "sector", "yahoo", "091170.KS", note="KRX 은행 ETF, 2006-06 상장"),
    Series("kr_ship", "한국 조선(TIGER 200 중공업)", "sector", "yahoo", "139280.KS", note="조선·중공업 섹터 ETF. 조선TOP10은 2024 상장이라 학습 기간이 부족"),
    Series("kr_robot", "한국 로봇(KODEX 로봇액티브)", "sector", "yahoo", "445290.KS", note="로봇/자동화 ETF, 2022-11 상장"),
)

FDR_FALLBACK = {
    "kospi": "KS11",
    "kosdaq": "KQ11",
    "nasdaq": "IXIC",
    "sp500": "US500",
    "dow": "DJI",
    "usdkkrw": "USD/KRW",
    "usdjpy": "USD/JPY",
    "bitcoin": "BTC/USD",
    "kr_semi": "091160",
    "kr_bio": "143860",
    "kr_finance": "091170",
    "kr_ship": "139280",
    "kr_robot": "445290",
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
# Future 탭 기간. id, 거래일, 화면 표기
FUTURE_HORIZONS: tuple[tuple[str, int, str], ...] = (
    ("1W", 5, "1주일"),
    ("1M", 21, "1개월"),
    ("3M", 63, "3개월"),
    ("6M", 126, "6개월"),
    ("1Y", 252, "1년"),
)
MIN_HISTORY_DAYS = 400
RANDOM_STATE = 42

# 월간 거시지표를 일별 패널에 붙일 때 발표 시차 (약 1개월)
MACRO_PUBLICATION_LAG_BDAYS = 21
DAILY_FFILL_LIMIT = 15
MONTHLY_FFILL_LIMIT = 130  # 약 6개월. 더 긴 공백은 학습에서 drop
YEARLY_FFILL_LIMIT = 260
DENSE_MONTHLY_OBS_RATIO = 0.35  # 이보다 관측이 촘촘하면 일별로 보고 시차를 적용하지 않음
FEATURE_COVERAGE_MIN = 0.65  # 피처 결측이 이보다 많으면 해당 일을 학습에서 제외

# 전진 탐색 교차검증
WALK_FORWARD_SPLITS = 5
WALK_FORWARD_MIN_TEST = 20

# 코스피 선택 시 보여주는 국내 섹터 ETF (개별 종목 대용 없음)
KOSPI_STOCKS = {
    "kr_semi": {"ticker": "091160.KS", "name": "KODEX 반도체", "sector": "반도체"},
    "kr_bio": {"ticker": "143860.KS", "name": "TIGER 헬스케어", "sector": "바이오"},
    "kr_finance": {"ticker": "091170.KS", "name": "KODEX 은행", "sector": "금융"},
    "kr_ship": {"ticker": "139280.KS", "name": "TIGER 200 중공업", "sector": "조선"},
    "kr_robot": {"ticker": "445290.KS", "name": "KODEX 로봇액티브", "sector": "로봇/자동화"},
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
