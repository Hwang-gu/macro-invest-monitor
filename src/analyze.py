from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from .config import ASSET_KEYS, PROCESSED_DIR, SECTOR_KEYS, series_by_key
from .process import load_events


CORE_LEVELS = [
    "kospi", "kosdaq", "nasdaq", "sp500", "gold", "bitcoin",
    "usdkkrw", "vix", "dxy",
    "us_3m", "us_2y", "us_10y", "kr_call", "kr_10y",
    "us_cpi_yoy", "kr_cpi_yoy", "us_real_10y", "us_curve_10_2",
    "us_finance", "kr_semi", "kr_ship",
]


def _labels(keys: list[str]) -> list[str]:
    meta = series_by_key()
    extra = {
        "us_cpi_yoy": "미국 CPI 전년비",
        "kr_cpi_yoy": "한국 CPI 전년비",
        "us_real_10y": "미국 실질 10년금리",
        "us_curve_10_2": "미국 장단기 스프레드(10-2)",
    }
    return [meta[k].label_ko if k in meta else extra.get(k, k) for k in keys]


def monthly_change_table(features: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in CORE_LEVELS if c in features.columns]
    monthly = features[cols].resample("ME").last()
    rets = monthly.pct_change()
    rate_cols = [c for c in monthly.columns if c in {
        "us_3m", "us_2y", "us_10y", "kr_call", "kr_10y",
        "us_cpi_yoy", "kr_cpi_yoy", "us_real_10y", "us_curve_10_2", "vix",
    }]
    for c in rate_cols:
        rets[c] = monthly[c].diff()
    return rets.dropna(how="all")


def correlation_bundle(features: pd.DataFrame) -> dict[str, Any]:
    monthly = monthly_change_table(features)
    cols = [c for c in CORE_LEVELS if c in monthly.columns]
    corr = monthly[cols].corr()
    corr.columns = _labels(cols)
    corr.index = _labels(cols)

    rolling = monthly[cols].rolling(36, min_periods=24).corr()
    latest_roll = None
    if not rolling.empty:
        last_date = rolling.index.get_level_values(0).max()
        latest_roll = rolling.xs(last_date)
        latest_roll.columns = _labels(cols)
        latest_roll.index = _labels(cols)

    return {
        "full_sample": corr,
        "rolling_36m": latest_roll,
        "monthly": monthly[cols],
        "keys": cols,
        "labels": _labels(cols),
    }


def cross_corr(x: pd.Series, y: pd.Series, max_lag: int = 12) -> pd.DataFrame:
    """양(+) lag = x가 y를 선행."""
    df = pd.concat([x, y], axis=1).dropna()
    if len(df) < max_lag + 30:
        return pd.DataFrame(columns=["lag", "corr"])
    a, b = df.iloc[:, 0], df.iloc[:, 1]
    rows = []
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            c = a.iloc[-lag:].reset_index(drop=True).corr(b.iloc[:lag].reset_index(drop=True))
        elif lag > 0:
            c = a.iloc[:-lag].reset_index(drop=True).corr(b.iloc[lag:].reset_index(drop=True))
        else:
            c = a.corr(b)
        rows.append({"lag": lag, "corr": c})
    return pd.DataFrame(rows)


def transmission_channels(features: pd.DataFrame) -> list[dict[str, Any]]:
    """사용자가 예시로 든 파급경로를 월간 변화로 검증합니다."""
    m = monthly_change_table(features)
    channels = [
        ("미국 단기금리 → 원/달러", "us_3m", "usdkkrw",
         "단기금리 하락 시 달러 약세·원화 강세(원/달러 하락)가 나타나는지"),
        ("원/달러 → 한국 CPI", "usdkkrw", "kr_cpi_yoy",
         "원화 약세(원/달러 상승)가 수입물가·CPI를 밀어 올리는지"),
        ("미국 단기금리 → 코스피", "us_3m", "kospi",
         "금리 하락이 한국 주식에 바로 호재인지, 환율 경로로 상쇄되는지"),
        ("원/달러 → 코스피(수출)", "usdkkrw", "kospi",
         "원화 약세가 수출 기업 실적 기대로 주가에 긍정적일 수 있음"),
        ("미국 실질금리 → 금", "us_real_10y", "gold",
         "실질금리 하락은 금에 우호적인 전형적 경로"),
        ("미국 실질금리 → 비트코인", "us_real_10y", "bitcoin",
         "유동성·기회비용 경로. 비트코인은 2014년 이후만 관측"),
        ("미국 장단기 스프레드 → 금융", "us_curve_10_2", "us_finance",
         "커브 스티프닝은 은행 순이자마진에 우호적"),
        ("나스닥 → 코스닥", "nasdaq", "kosdaq",
         "글로벌 성장 선호가 국내 성장주로 전이되는지"),
        ("나스닥 → 한국 반도체", "nasdaq", "kr_semi",
         "AI/반도체 동조화"),
        ("원/달러 → 한국 조선", "usdkkrw", "kr_ship",
         "원화 약세·글로벌 교역이 조선 수주/실적 기대와 맞는지"),
        ("VIX → 금/주식 상대", "vix", "gold",
         "공포 국면의 안전자산 수요"),
    ]
    out = []
    for title, src, dst, meaning in channels:
        if src not in m.columns or dst not in m.columns:
            continue
        cc = cross_corr(m[src], m[dst], max_lag=12)
        if cc.empty:
            continue
        best = cc.loc[cc["corr"].abs().idxmax()]
        contemp = float(cc.loc[cc["lag"] == 0, "corr"].iloc[0])
        out.append({
            "title": title,
            "src": src,
            "dst": dst,
            "meaning": meaning,
            "corr_0": contemp,
            "best_lag": int(best["lag"]),
            "best_corr": float(best["corr"]),
            "curve": cc.to_dict(orient="records"),
        })
    return out


def event_study(panel: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    events = load_events()
    assets = [k for k in list(ASSET_KEYS) + ["usdkkrw"] if k in panel.columns]
    rows = []
    for _, ev in events.iterrows():
        loc = panel.index.searchsorted(ev["date"])
        if loc < 5 or loc >= len(panel) - 5:
            continue
        start = max(0, loc - 5)
        base = panel.iloc[start:loc + 1]
        fwd = panel.iloc[loc: min(len(panel), loc + window + 1)]
        row: dict[str, Any] = {
            "id": ev["id"],
            "name_ko": ev["name_ko"],
            "category": ev["category"],
            "severity": ev["severity"],
            "date": ev["date"].date().isoformat(),
        }
        for a in assets:
            pre = base[a].dropna()
            post = fwd[a].dropna()
            if len(pre) < 2 or len(post) < 5:
                row[a] = np.nan
                continue
            p0 = pre.iloc[-1]
            p1 = post.iloc[-1]
            row[a] = float(p1 / p0 - 1.0) if p0 else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def event_category_avg(study: pd.DataFrame) -> pd.DataFrame:
    num = study.drop(columns=["id", "name_ko", "category", "severity", "date"], errors="ignore")
    grouped = study[["category"]].join(num).groupby("category").mean(numeric_only=True)
    return grouped


def save_analysis(corr: dict[str, Any], channels: list[dict[str, Any]], study: pd.DataFrame) -> None:
    corr["full_sample"].to_csv(PROCESSED_DIR / "corr_full.csv", encoding="utf-8-sig")
    if corr["rolling_36m"] is not None:
        corr["rolling_36m"].to_csv(PROCESSED_DIR / "corr_rolling_36m.csv", encoding="utf-8-sig")
    study.to_csv(PROCESSED_DIR / "event_study.csv", index=False, encoding="utf-8-sig")
    slim = [{k: v for k, v in ch.items() if k != "curve"} for ch in channels]
    (PROCESSED_DIR / "transmission.json").write_text(
        json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (PROCESSED_DIR / "transmission_full.json").write_text(
        json.dumps(channels, ensure_ascii=False, indent=2), encoding="utf-8"
    )
