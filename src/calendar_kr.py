from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

KST = timezone(timedelta(hours=9))


def kst_today_date() -> date:
    return datetime.now(KST).date()


@lru_cache(maxsize=8)
def _kr_holidays(year: int) -> Any:
    try:
        import holidays

        return holidays.country_holidays("KR", years=year)
    except Exception:  # noqa: BLE001
        return {}


def is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def holiday_name(day: date) -> str | None:
    names = _kr_holidays(day.year)
    try:
        name = names.get(day)
    except Exception:  # noqa: BLE001
        return None
    if name:
        return str(name)
    return None


def mail_day_status(day: date | None = None) -> tuple[bool, str]:
    """평일(월~금)이면서 한국 공휴일이 아니면 발송합니다."""
    day = day or kst_today_date()
    stamp = day.isoformat()
    if is_weekend(day):
        return False, f"{stamp}는 주말이라 뉴스레터를 건너뛰었습니다."
    name = holiday_name(day)
    if name:
        return False, f"{stamp}는 공휴일({name})이라 뉴스레터를 건너뛰었습니다."
    return True, ""
