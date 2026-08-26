from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .config import (
    ASSET_KEYS,
    EVENTS_PATH,
    PROCESSED_DIR,
    START,
    Series,
    UNIVERSE,
    series_by_key,
)


REQUIRED_EVENT_FIELDS = ("id", "date", "end_date", "category", "severity", "name_ko", "summary_ko")
ALLOWED_CATEGORIES = {
    "war", "disease", "technology", "financial_crisis", "geopolitics", "policy",
    "technology", "financial_crisis", "geopolitics",
}
CATEGORY_ALIASES = {
    "technology": "technology",
    "financial_crisis": "financial_crisis",
    "geopolitics": "geopolitics",
}


def load_events() -> pd.DataFrame:
    try:
        payload = json.loads(EVENTS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"data/events.json 형식이 잘못되었습니다. {exc.lineno}번째 줄 근처를 확인하세요. "
            "마지막 이슈 뒤에 쉼표가 남아 있거나, 큰따옴표가 빠진 경우가 많습니다."
        ) from exc
    rows = payload.get("events")
    if not isinstance(rows, list) or not rows:
        raise ValueError("data/events.json 의 events 배열이 비어 있습니다.")
    for i, row in enumerate(rows, start=1):
        missing = [k for k in REQUIRED_EVENT_FIELDS if k not in row]
        if missing:
            raise ValueError(f"events.json {i}번째 이슈에 필드가 없습니다: {', '.join(missing)}")
        cat = str(row.get("category", ""))
        if cat not in ALLOWED_CATEGORIES:
            raise ValueError(
                f"events.json 이슈 '{row.get('id')}' 의 category '{cat}' 는 사용할 수 없습니다. "
                "war / disease / technology / financial_crisis / geopolitics / policy 중 하나여야 합니다."
            )
        row["category"] = CATEGORY_ALIASES.get(cat, cat)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["end_date"] = pd.to_datetime(df["end_date"])
    if (df["end_date"] < df["date"]).any():
        bad = df.loc[df["end_date"] < df["date"], "id"].tolist()
        raise ValueError(f"종료일이 시작일보다 앞선 이슈: {bad}")
    return df.sort_values("date").reset_index(drop=True)


def to_panel(raw: dict[str, pd.Series]) -> pd.DataFrame:
    """거래일 달력에 맞춰 가격·금리를 정렬하고, 월간 지표는 전방 보간합니다."""
    frames = []
    for spec in UNIVERSE:
        if spec.key not in raw:
            continue
        s = raw[spec.key].copy()
        s.index = pd.to_datetime(s.index).normalize()
        s = s[~s.index.duplicated(keep="last")].sort_index()
        s.name = spec.key
        frames.append(s)
    if not frames:
        raise ValueError("원본 데이터가 없습니다.")
    panel = pd.concat(frames, axis=1).sort_index()
    panel = panel[panel.index >= pd.Timestamp(START)]
    if panel.empty:
        raise ValueError("2000-01-01 이후 원본 데이터가 없습니다.")
    start = max(pd.Timestamp(START), panel.index.min())
    biz = pd.bdate_range(start, panel.index.max())
    panel = panel.reindex(biz)
    meta = series_by_key()
    for col in panel.columns:
        spec = meta.get(col)
        if spec is None:
            continue
        if spec.frequency == "monthly":
            panel[col] = panel[col].ffill(limit=80)
        elif spec.frequency == "yearly":
            panel[col] = panel[col].ffill(limit=520)
        else:
            panel[col] = panel[col].ffill(limit=8)
    return panel


def _yoy(series: pd.Series, periods: int = 252) -> pd.Series:
    return series.pct_change(periods) * 100.0


def _monthly_yoy(series: pd.Series) -> pd.Series:
    m = series.resample("ME").last().dropna()
    yoy = m.pct_change(12) * 100.0
    return yoy.reindex(series.index, method="ffill", limit=80)


def build_features(panel: pd.DataFrame) -> pd.DataFrame:
    extras: dict[str, pd.Series] = {}
    skip = {"us_3m", "us_2y", "us_10y", "us_ffr", "kr_call", "kr_10y", "us_cpi", "kr_cpi", "kr_infl_wb"}
    price_like = [c for c in panel.columns if c not in skip]
    for col in price_like:
        ret = panel[col].pct_change()
        extras[f"{col}_ret"] = ret
        extras[f"{col}_mom_21"] = panel[col].pct_change(21)
        extras[f"{col}_mom_63"] = panel[col].pct_change(63)
        extras[f"{col}_mom_126"] = panel[col].pct_change(126)
        extras[f"{col}_vol_21"] = ret.rolling(21).std() * np.sqrt(252)

    for rate in ("us_3m", "us_2y", "us_10y", "us_ffr", "kr_call", "kr_10y"):
        if rate in panel:
            extras[f"{rate}_chg"] = panel[rate].diff()
            extras[f"{rate}_chg_21"] = panel[rate].diff(21)

    if {"us_10y", "us_2y"} <= set(panel.columns):
        extras["us_curve_10_2"] = panel["us_10y"] - panel["us_2y"]
    if {"us_10y", "us_3m"} <= set(panel.columns):
        extras["us_curve_10_3m"] = panel["us_10y"] - panel["us_3m"]
    if {"kr_10y", "kr_call"} <= set(panel.columns):
        extras["kr_curve"] = panel["kr_10y"] - panel["kr_call"]

    if "us_cpi" in panel:
        extras["us_cpi_yoy"] = _monthly_yoy(panel["us_cpi"])
    if "kr_cpi" in panel:
        monthly = _monthly_yoy(panel["kr_cpi"])
        last_obs = panel["kr_cpi"].last_valid_index()
        stale = last_obs is None or (panel.index.max() - last_obs).days > 180
        if stale and "kr_infl_wb" in panel:
            extras["kr_cpi_yoy"] = panel["kr_infl_wb"]
        else:
            extras["kr_cpi_yoy"] = monthly
    if "us_cpi_yoy" in extras and "us_10y" in panel:
        extras["us_real_10y"] = panel["us_10y"] - extras["us_cpi_yoy"]
    if "us_cpi_yoy" in extras and "us_3m" in panel:
        extras["us_real_3m"] = panel["us_3m"] - extras["us_cpi_yoy"]

    events = load_events()
    extras["event_war"] = pd.Series(0.0, index=panel.index)
    extras["event_disease"] = pd.Series(0.0, index=panel.index)
    extras["event_tech"] = pd.Series(0.0, index=panel.index)
    extras["event_crisis"] = pd.Series(0.0, index=panel.index)
    for _, ev in events.iterrows():
        mask = (panel.index >= ev["date"]) & (panel.index <= ev["end_date"])
        cat = ev["category"]
        col = {
            "war": "event_war",
            "disease": "event_disease",
            "technology": "event_tech",
            "financial_crisis": "event_crisis",
            "geopolitics": "event_crisis",
            "policy": "event_crisis",
        }.get(cat)
        if col:
            extras[col] = extras[col].mask(mask, 1.0)

    extra_df = pd.DataFrame(extras, index=panel.index)
    return pd.concat([panel, extra_df], axis=1)


def monthly_returns(panel: pd.DataFrame, keys: tuple[str, ...] | None = None) -> pd.DataFrame:
    keys = keys or ASSET_KEYS
    cols = [k for k in keys if k in panel.columns]
    m = panel[cols].resample("ME").last()
    return m.pct_change()


def save_processed(panel: pd.DataFrame, features: pd.DataFrame) -> None:
    panel.to_parquet(PROCESSED_DIR / "panel.parquet")
    features.to_parquet(PROCESSED_DIR / "features.parquet")
    panel.to_csv(PROCESSED_DIR / "panel.csv", date_format="%Y-%m-%d")
    features.to_csv(PROCESSED_DIR / "features.csv", date_format="%Y-%m-%d")


def load_processed() -> tuple[pd.DataFrame, pd.DataFrame]:
    panel = pd.read_parquet(PROCESSED_DIR / "panel.parquet")
    features = pd.read_parquet(PROCESSED_DIR / "features.parquet")
    return panel, features
