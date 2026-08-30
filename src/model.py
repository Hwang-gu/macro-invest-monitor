from __future__ import annotations

import json
from datetime import date
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .config import (
    ASSET_KEYS,
    FORWARD_DAYS,
    FUTURE_HORIZONS,
    MARKET_KEYS,
    MIN_HISTORY_DAYS,
    MODELS_DIR,
    RANDOM_STATE,
    SECTOR_KEYS,
    series_by_key,
)
from .process import load_events

FEATURE_CANDIDATES = [
    "us_3m_chg_21", "us_2y_chg_21", "us_10y_chg_21",
    "us_curve_10_2", "us_curve_10_3m", "kr_curve",
    "us_real_10y", "us_real_3m",
    "us_cpi_yoy", "kr_cpi_yoy",
    "usdkkrw_mom_21", "usdkkrw_mom_63",
    "dxy_mom_21", "vix_mom_21", "vix",
    "gold_mom_21", "gold_mom_63",
    "sp500_mom_21", "sp500_mom_63", "nasdaq_mom_21", "nasdaq_mom_63",
    "kospi_mom_21", "kosdaq_mom_21",
    "bitcoin_mom_21", "bitcoin_mom_63",
    "us_semi_mom_21", "us_finance_mom_21",
    "event_war", "event_disease", "event_tech", "event_crisis",
]


def _feature_matrix(features: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in FEATURE_CANDIDATES if c in features.columns]
    x = features[cols].copy()
    if "bitcoin_mom_21" in x:
        x["bitcoin_mom_21"] = x["bitcoin_mom_21"].fillna(0.0)
    if "bitcoin_mom_63" in x:
        x["bitcoin_mom_63"] = x["bitcoin_mom_63"].fillna(0.0)
    return x


def _forward_return(price: pd.Series, days: int = FORWARD_DAYS) -> pd.Series:
    return price.shift(-days) / price - 1.0


def _horizon_label(days: int) -> str:
    for _hid, n, label in FUTURE_HORIZONS:
        if n == days:
            return label
    return f"{days}거래일"


def _mom_col(key: str, days: int) -> str:
    if days >= 126:
        return f"{key}_mom_126"
    if days >= 63:
        return f"{key}_mom_63"
    return f"{key}_mom_21"


def _train_one_horizon(
    x: pd.DataFrame,
    panel: pd.DataFrame,
    targets: list[str],
    days: int,
) -> tuple[dict[str, Pipeline], dict[str, dict[str, float]]]:
    models: dict[str, Pipeline] = {}
    metrics: dict[str, dict[str, float]] = {}
    for key in targets:
        y = _forward_return(panel[key], days)
        df = pd.concat([x, y.rename("y")], axis=1).dropna()
        if len(df) < MIN_HISTORY_DAYS:
            continue
        split = int(len(df) * 0.8)
        x_train, x_test = df.drop(columns=["y"]).iloc[:split], df.drop(columns=["y"]).iloc[split:]
        y_train, y_test = df["y"].iloc[:split], df["y"].iloc[split:]
        pipe = Pipeline([
            ("scaler", StandardScaler()),
            ("ridge", Ridge(alpha=5.0, random_state=RANDOM_STATE)),
        ])
        pipe.fit(x_train, y_train)
        pred = pipe.predict(x_test)
        ss_res = float(np.sum((y_test - pred) ** 2))
        ss_tot = float(np.sum((y_test - y_test.mean()) ** 2)) or np.nan
        r2 = 1.0 - ss_res / ss_tot if ss_tot else np.nan
        hit = float(np.mean(np.sign(pred) == np.sign(y_test)))
        models[key] = pipe
        metrics[key] = {
            "n": float(len(df)),
            "test_r2": float(r2) if r2 == r2 else 0.0,
            "hit_rate": hit,
            "test_mean_pred": float(np.mean(pred)),
            "test_mean_actual": float(y_test.mean()),
        }
    return models, metrics


def train_models(panel: pd.DataFrame, features: pd.DataFrame) -> dict[str, Any]:
    x = _feature_matrix(features)
    targets = [k for k in list(ASSET_KEYS) + list(MARKET_KEYS) + list(SECTOR_KEYS) if k in panel.columns]
    by_horizon: dict[str, dict[str, Any]] = {}
    for _hid, days, _label in FUTURE_HORIZONS:
        models, metrics = _train_one_horizon(x, panel, targets, days)
        by_horizon[str(days)] = {"models": models, "metrics": metrics}
        print(f"[model] horizon {days}d n_targets={len(models)}")
    default = by_horizon.get(str(FORWARD_DAYS)) or next(iter(by_horizon.values()))
    payload = {
        "models": default["models"],
        "metrics": default["metrics"],
        "features": list(x.columns),
        "by_horizon": by_horizon,
        "default_days": FORWARD_DAYS,
    }
    joblib.dump(payload, MODELS_DIR / "ridge_bundle.joblib")
    (MODELS_DIR / "metrics.json").write_text(
        json.dumps({k: v["metrics"] for k, v in by_horizon.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def _horizon_slice(bundle: dict[str, Any], days: int) -> dict[str, Any]:
    by = bundle.get("by_horizon") or {}
    slice_ = by.get(str(int(days)))
    if not slice_:
        return bundle
    return {
        "models": slice_.get("models") or {},
        "metrics": slice_.get("metrics") or {},
        "features": bundle.get("features") or slice_.get("features") or [],
    }


def load_models() -> dict[str, Any]:
    path = MODELS_DIR / "ridge_bundle.joblib"
    if not path.exists():
        raise FileNotFoundError("학습된 모델이 없습니다. 먼저 히스토리 파이프라인을 실행하세요.")
    return joblib.load(path)


def _score_latest(bundle: dict[str, Any], features: pd.DataFrame) -> dict[str, float]:
    x = _feature_matrix(features).dropna()
    if x.empty:
        return {}
    row = x.iloc[[-1]]
    cols = bundle["features"]
    row = row.reindex(columns=cols, fill_value=0.0)
    scores = {}
    for key, model in bundle["models"].items():
        try:
            scores[key] = float(model.predict(row)[0])
        except Exception:  # noqa: BLE001
            continue
    return scores


def _active_events(asof: pd.Timestamp) -> list[dict[str, Any]]:
    events = load_events()
    window_start = asof - pd.Timedelta(days=45)
    active = events[(events["end_date"] >= window_start) & (events["date"] <= asof)]
    return active.to_dict(orient="records")


def _regime(features: pd.DataFrame) -> dict[str, Any]:
    row = features.dropna(how="all").iloc[-1]
    curve = float(row.get("us_curve_10_2", np.nan))
    real = float(row.get("us_real_10y", np.nan))
    vix = float(row.get("vix", np.nan))
    us3m_chg = float(row.get("us_3m_chg_21", np.nan))
    fx_mom = float(row.get("usdkkrw_mom_21", np.nan))
    cpi = float(row.get("us_cpi_yoy", np.nan))
    kr_cpi = float(row.get("kr_cpi_yoy", np.nan))

    inverted = curve < 0 if curve == curve else False
    risk_off = (vix > 20 if vix == vix else False) or inverted
    easing = us3m_chg < -0.10 if us3m_chg == us3m_chg else False
    krw_strong = fx_mom < -0.01 if fx_mom == fx_mom else False
    krw_weak = fx_mom > 0.01 if fx_mom == fx_mom else False

    return {
        "asof": str(features.index.max().date()),
        "us_curve_10_2": curve,
        "us_real_10y": real,
        "vix": vix,
        "us_3m_chg_21": us3m_chg,
        "usdkkrw_mom_21": fx_mom,
        "us_cpi_yoy": cpi,
        "kr_cpi_yoy": kr_cpi,
        "inverted_curve": inverted,
        "risk_off": risk_off,
        "easing": easing,
        "krw_strong": krw_strong,
        "krw_weak": krw_weak,
        "us_3m": float(row.get("us_3m", np.nan)),
        "us_10y": float(row.get("us_10y", np.nan)),
        "kr_call": float(row.get("kr_call", np.nan)),
        "kr_10y": float(row.get("kr_10y", np.nan)),
        "usdkkrw": float(row.get("usdkkrw", np.nan)),
        "kr_cpi_last": str(features["kr_cpi"].last_valid_index().date()) if "kr_cpi" in features and features["kr_cpi"].last_valid_index() is not None else None,
        "us_cpi_last": str(features["us_cpi"].last_valid_index().date()) if "us_cpi" in features and features["us_cpi"].last_valid_index() is not None else None,
    }


def allocate(
    panel: pd.DataFrame,
    features: pd.DataFrame,
    bundle: dict[str, Any] | None = None,
    horizon_days: int | None = None,
) -> dict[str, Any]:
    days = int(horizon_days or FORWARD_DAYS)
    bundle = bundle or load_models()
    slice_ = _horizon_slice(bundle, days)
    raw_scores = _score_latest(slice_, features)
    metrics = slice_.get("metrics", {})
    last = features.iloc[-1]
    adj_scale = min(1.0, (21 / max(days, 1)) ** 0.5)
    scores: dict[str, float] = {}
    for key, pred in raw_scores.items():
        hit = float((metrics.get(key) or {}).get("hit_rate", 0.5))
        r2 = float((metrics.get(key) or {}).get("test_r2", -1.0))
        mom_raw = last.get(_mom_col(key, days), last.get(f"{key}_mom_21", 0.0))
        mom = float(mom_raw) if mom_raw == mom_raw else 0.0
        mom = float(np.clip(mom, -0.15, 0.15))
        model_w = 0.15 if r2 < 0 else min(0.45, max(0.15, (hit - 0.5) * 2))
        scores[key] = model_w * pred + (1.0 - model_w) * mom
    regime = _regime(features)
    events = _active_events(features.index.max())
    meta = series_by_key()

    def adj(key: str, base: float) -> float:
        s = base
        bump = adj_scale
        if regime["risk_off"] and key in {"gold"}:
            s += 0.015 * bump
        if regime["risk_off"] and key in {"kosdaq", "nasdaq", "bitcoin"}:
            s -= 0.01 * bump
        if regime["easing"] and key in {"gold", "bitcoin", "nasdaq", "kosdaq"}:
            s += 0.01 * bump
        if regime["krw_strong"] and key in {"kospi", "kr_semi", "kr_ship"}:
            s -= 0.008 * bump
        if regime["krw_weak"] and key in {"kospi", "kr_semi", "kr_ship"}:
            s += 0.008 * bump
        if regime["inverted_curve"] and key in {"us_finance", "kr_finance"}:
            s -= 0.006 * bump
        if not regime["inverted_curve"] and key in {"us_finance", "kr_finance"}:
            s += 0.004 * bump
        for ev in events:
            bias = ev.get("bias") or {}
            if key in bias:
                s += bump * {"positive": 0.01, "negative": -0.01, "mixed": 0.0, "up": 0.005}.get(bias[key], 0.0)
            if bias.get("stocks") and key in ASSET_KEYS + MARKET_KEYS and key not in {"gold", "bitcoin"}:
                s += bump * {"positive": 0.008, "negative": -0.008, "mixed": 0.0}.get(bias["stocks"], 0.0)
        return s

    asset_scores = {k: adj(k, scores.get(k, 0.0)) for k in ASSET_KEYS if k in scores or k in panel.columns}
    for k in list(asset_scores):
        if k not in scores:
            asset_scores[k] = adj(k, 0.0)

    ranked_assets = sorted(asset_scores.items(), key=lambda kv: kv[1], reverse=True)
    pick_asset = ranked_assets[0][0] if ranked_assets else "gold"

    market_scores = {k: adj(k, scores.get(k, 0.0)) for k in MARKET_KEYS}
    market_pick = max(market_scores, key=market_scores.get) if market_scores else None
    sector_pool = [k for k in SECTOR_KEYS if k in scores or k in panel.columns]
    if market_pick in {"kospi", "kosdaq"}:
        prefer = [k for k in sector_pool if k.startswith("kr_")]
    else:
        prefer = [k for k in sector_pool if k.startswith("us_")]
    use = prefer or sector_pool
    sector_scores = {k: adj(k, scores.get(k, 0.0)) for k in use}
    sector_pick = max(sector_scores, key=sector_scores.get) if sector_scores else None
    if pick_asset not in MARKET_KEYS:
        chosen_market, chosen_sector = None, None
    else:
        chosen_market, chosen_sector = market_pick, sector_pick

    def ko(key: str | None) -> str | None:
        if key is None:
            return None
        return meta[key].label_ko if key in meta else key

    report = {
        "asof": regime["asof"],
        "generated": date.today().isoformat(),
        "horizon_days": days,
        "horizon_label": _horizon_label(days),
        "asset": pick_asset,
        "asset_label": ko(pick_asset),
        "market": chosen_market,
        "market_label": ko(chosen_market),
        "sector": chosen_sector,
        "sector_label": ko(chosen_sector),
        "if_stocks_market": market_pick,
        "if_stocks_market_label": ko(market_pick),
        "if_stocks_sector": sector_pick,
        "if_stocks_sector_label": ko(sector_pick),
        "asset_scores": asset_scores,
        "market_scores": market_scores,
        "sector_scores": sector_scores,
        "model_scores": scores,
        "metrics": slice_.get("metrics", {}),
        "regime": regime,
        "active_events": [
            {"name_ko": e["name_ko"], "category": e["category"], "severity": e["severity"], "date": str(e["date"])[:10]}
            for e in events
        ],
        "disclaimer": "연구용 점수이며 투자 권유가 아닙니다. 과거 상관은 미래 수익을 보장하지 않습니다.",
    }
    report["forecast"] = _forecast_tree(report)
    return report


def _forecast_tree(report: dict[str, Any]) -> dict[str, Any]:
    from .config import KOSPI_STOCKS

    asset = report["asset"]
    stage1 = "금" if asset == "gold" else "비트코인" if asset == "bitcoin" else "주식"
    market = report.get("if_stocks_market") or report.get("market")
    sector = report.get("if_stocks_sector") or report.get("sector")
    stock = KOSPI_STOCKS.get(sector) if sector else None
    reasons = []
    regime = report.get("regime") or {}
    if regime.get("krw_strong"):
        reasons.append("최근 원화 강세 → 코스피 수출주(반도체·조선) 감점")
    if regime.get("easing"):
        reasons.append("단기금리 하락 → 금·비트코인·성장주 가점")
    if regime.get("risk_off"):
        reasons.append("위험회피 국면 → 금 가점, 코스닥·나스닥·비트코인 감점")
    for ev in report.get("active_events") or []:
        reasons.append(f"진행 이슈: {ev.get('name_ko')}")
    kospi_pick = market == "kospi"
    return {
        "stage1_asset_class": stage1,
        "stage1_key": asset,
        "stage2_market": report.get("if_stocks_market_label") or report.get("market_label"),
        "stage2_key": market,
        "stage3_sector": report.get("if_stocks_sector_label") or report.get("sector_label"),
        "stage3_key": sector,
        "stage4_stock": stock["name"] if kospi_pick and stock else None,
        "stage4_ticker": stock["ticker"] if kospi_pick and stock else None,
        "stage4_note": (
            "코스피 업종 대용 대표주입니다. 동일 업종 ETF·바스켓으로 나눠 담는 편이 안전합니다."
            if kospi_pick and stock
            else None
        ),
        "reasons": reasons,
        "horizon": f"향후 {report.get('horizon_label') or _horizon_label(int(report.get('horizon_days') or 21))}의 상대 점수",
    }
