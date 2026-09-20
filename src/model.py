from __future__ import annotations

import json
from datetime import date
from typing import Any, Callable

import joblib
import numpy as np
import pandas as pd

from sklearn.model_selection import TimeSeriesSplit

from .config import (
    ASSET_KEYS,
    FEATURE_COVERAGE_MIN,
    FORWARD_DAYS,
    FUTURE_HORIZONS,
    MARKET_KEYS,
    MIN_HISTORY_DAYS,
    MODELS_DIR,
    RANDOM_STATE,
    SECTOR_KEYS,
    WALK_FORWARD_MIN_TEST,
    WALK_FORWARD_SPLITS,
    series_by_key,
)
from .process import load_events

FEATURE_CANDIDATES = [
    "us_3m_chg_21", "us_2y_chg_21", "us_10y_chg_21",
    "us_curve_10_2", "us_curve_10_3m", "kr_curve",
    "us_real_10y", "us_real_3m",
    "us_cpi_yoy", "kr_cpi_yoy",
    "usdkkrw_mom_21", "usdkkrw_mom_63",
    "dxy_mom_21", "vix_mom_21", "vix", "vix_high",
    "curve_inverted", "risk_off",
    "gold_mom_21", "gold_mom_63",
    "sp500_mom_21", "sp500_mom_63", "nasdaq_mom_21", "nasdaq_mom_63",
    "kospi_mom_21", "kosdaq_mom_21",
    "bitcoin_mom_21", "bitcoin_mom_63",
    "us_semi_mom_21", "us_finance_mom_21",
    "event_war", "event_disease", "event_tech",
    "event_crisis", "event_geopolitics", "event_policy",
]

EstimatorFactory = Callable[[], Any]


def _feature_matrix(features: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in FEATURE_CANDIDATES if c in features.columns]
    return features[cols].copy()


def _forward_log_return(price: pd.Series, days: int = FORWARD_DAYS) -> pd.Series:
    future = price.shift(-days)
    ratio = future / price
    ratio = ratio.where(ratio > 0)
    return np.log(ratio)


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


def _make_estimator() -> Any:
    try:
        import lightgbm as lgb

        return lgb.LGBMRegressor(
            n_estimators=120,
            learning_rate=0.05,
            max_depth=4,
            num_leaves=15,
            min_child_samples=40,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            random_state=RANDOM_STATE,
            verbosity=-1,
            n_jobs=1,
        )
    except ImportError:
        from sklearn.ensemble import HistGradientBoostingRegressor

        return HistGradientBoostingRegressor(
            max_depth=4,
            learning_rate=0.05,
            max_iter=120,
            min_samples_leaf=40,
            l2_regularization=1.0,
            random_state=RANDOM_STATE,
        )


def _prepare_xy(x: pd.DataFrame, y: pd.Series) -> pd.DataFrame:
    df = pd.concat([x, y.rename("y")], axis=1)
    df = df.dropna(subset=["y"])
    feat = df.drop(columns=["y"])
    coverage = feat.notna().mean(axis=1)
    df = df.loc[coverage >= FEATURE_COVERAGE_MIN]
    return df


def _r2_hit(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float]:
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2)) or np.nan
    r2 = 1.0 - ss_res / ss_tot if ss_tot else np.nan
    hit = float(np.mean(np.sign(y_pred) == np.sign(y_true)))
    return (float(r2) if r2 == r2 else -1.0), hit


def _walk_forward(
    factory: EstimatorFactory,
    x: pd.DataFrame,
    y: pd.Series,
    embargo: int,
) -> dict[str, float] | None:
    n = len(x)
    n_splits = WALK_FORWARD_SPLITS
    min_train = MIN_HISTORY_DAYS
    if n < min_train + WALK_FORWARD_MIN_TEST * 2:
        return None
    splitter = TimeSeriesSplit(n_splits=n_splits)
    oos_pred: list[np.ndarray] = []
    oos_true: list[np.ndarray] = []
    n_folds = 0
    for train_idx, test_idx in splitter.split(x):
        cutoff = int(test_idx[0]) - max(embargo, 0)
        train_idx = train_idx[train_idx < max(cutoff, 0)]
        if len(train_idx) < min_train or len(test_idx) < WALK_FORWARD_MIN_TEST:
            continue
        model = factory()
        model.fit(x.iloc[train_idx], y.iloc[train_idx])
        pred = np.asarray(model.predict(x.iloc[test_idx]), dtype=float)
        oos_pred.append(pred)
        oos_true.append(y.iloc[test_idx].to_numpy(dtype=float))
        n_folds += 1
    if n_folds == 0:
        return None
    pred = np.concatenate(oos_pred)
    true = np.concatenate(oos_true)
    r2, hit = _r2_hit(true, pred)
    return {
        "test_r2": r2,
        "hit_rate": hit,
        "n_folds": float(n_folds),
        "n_oos": float(len(true)),
        "test_mean_pred": float(np.mean(pred)),
        "test_mean_actual": float(np.mean(true)),
    }


def _train_one_horizon(
    x: pd.DataFrame,
    panel: pd.DataFrame,
    targets: list[str],
    days: int,
) -> tuple[dict[str, Any], dict[str, dict[str, float]]]:
    models: dict[str, Any] = {}
    metrics: dict[str, dict[str, float]] = {}
    for key in targets:
        y = _forward_log_return(panel[key], days)
        df = _prepare_xy(x, y)
        if len(df) < MIN_HISTORY_DAYS:
            continue
        x_all = df.drop(columns=["y"])
        y_all = df["y"]
        wf = _walk_forward(_make_estimator, x_all, y_all, embargo=days)
        model = _make_estimator()
        model.fit(x_all, y_all)
        models[key] = model
        if wf is None:
            metrics[key] = {
                "n": float(len(df)),
                "test_r2": -1.0,
                "hit_rate": 0.5,
                "n_folds": 0.0,
                "n_oos": 0.0,
                "test_mean_pred": float("nan"),
                "test_mean_actual": float("nan"),
            }
        else:
            metrics[key] = {"n": float(len(df)), **wf}
    return models, metrics


def train_models(panel: pd.DataFrame, features: pd.DataFrame) -> dict[str, Any]:
    x = _feature_matrix(features)
    targets = [k for k in list(ASSET_KEYS) + list(MARKET_KEYS) + list(SECTOR_KEYS) if k in panel.columns]
    by_horizon: dict[str, dict[str, Any]] = {}
    for _hid, days, _label in FUTURE_HORIZONS:
        models, metrics = _train_one_horizon(x, panel, targets, days)
        by_horizon[str(days)] = {"models": models, "metrics": metrics}
        print(f"[model] horizon {days}d n_targets={len(models)}", flush=True)
    default = by_horizon.get(str(FORWARD_DAYS)) or next(iter(by_horizon.values()))
    payload = {
        "models": default["models"],
        "metrics": default["metrics"],
        "features": list(x.columns),
        "by_horizon": by_horizon,
        "default_days": FORWARD_DAYS,
        "estimator": "lightgbm",
        "target": "log_return",
    }
    joblib.dump(payload, MODELS_DIR / "model_bundle.joblib")
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
    for name in ("model_bundle.joblib", "lgbm_bundle.joblib", "ridge_bundle.joblib"):
        path = MODELS_DIR / name
        if path.exists():
            return joblib.load(path)
    raise FileNotFoundError("학습된 모델이 없습니다. 먼저 히스토리 파이프라인을 실행하세요.")


def _score_latest(bundle: dict[str, Any], features: pd.DataFrame) -> dict[str, float]:
    x = _feature_matrix(features)
    if x.empty:
        return {}
    row = x.iloc[[-1]]
    cols = bundle["features"]
    row = row.reindex(columns=cols)
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


def _blend_score(pred: float | None, mom: float, r2: float, hit: float) -> float:
    if pred is None or r2 != r2 or r2 < 0:
        return mom
    model_w = min(0.45, max(0.15, (hit - 0.5) * 2))
    return model_w * pred + (1.0 - model_w) * mom


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
    all_keys = list(dict.fromkeys(list(ASSET_KEYS) + list(MARKET_KEYS) + list(SECTOR_KEYS)))
    scores: dict[str, float] = {}
    for key in all_keys:
        if key not in panel.columns:
            continue
        mom_raw = last.get(_mom_col(key, days), last.get(f"{key}_mom_21", 0.0))
        mom = float(mom_raw) if mom_raw == mom_raw else 0.0
        mom = float(np.clip(mom, -0.15, 0.15))
        hit = float((metrics.get(key) or {}).get("hit_rate", 0.5))
        r2 = float((metrics.get(key) or {}).get("test_r2", -1.0))
        pred = raw_scores.get(key)
        scores[key] = _blend_score(pred, mom, r2, hit)

    regime = _regime(features)
    events = _active_events(features.index.max())
    meta = series_by_key()

    asset_scores = {k: scores.get(k, 0.0) for k in ASSET_KEYS if k in scores or k in panel.columns}
    ranked_assets = sorted(asset_scores.items(), key=lambda kv: kv[1], reverse=True)
    pick_asset = ranked_assets[0][0] if ranked_assets else "gold"

    market_scores = {k: scores.get(k, 0.0) for k in MARKET_KEYS if k in scores or k in panel.columns}
    market_pick = max(market_scores, key=market_scores.get) if market_scores else None
    sector_pool = [k for k in SECTOR_KEYS if k in scores or k in panel.columns]
    if market_pick in {"kospi", "kosdaq"}:
        prefer = [k for k in sector_pool if k.startswith("kr_")]
    else:
        prefer = [k for k in sector_pool if k.startswith("us_")]
    use = prefer or sector_pool
    sector_scores = {k: scores.get(k, 0.0) for k in use}
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
    etf = KOSPI_STOCKS.get(sector) if sector else None
    reasons = []
    regime = report.get("regime") or {}
    if regime.get("krw_strong"):
        reasons.append("최근 원화 강세 — 수출주 실적 눈높이에는 부담일 수 있음")
    if regime.get("easing"):
        reasons.append("단기금리 하락 — 금·성장 자산에 우호적일 수 있는 국면")
    if regime.get("risk_off"):
        reasons.append("VIX 상승 또는 커브 역전 — 위험회피 성격이 강한 국면")
    if regime.get("inverted_curve"):
        reasons.append("장단기 금리 역전 — 금융 섹터에 부담이 될 수 있음")
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
        "stage4_stock": etf["name"] if kospi_pick and etf else None,
        "stage4_ticker": etf["ticker"] if kospi_pick and etf else None,
        "stage4_note": (
            "코스피 업종은 개별 종목이 아니라 해당 섹터 ETF 수익률로 평가합니다."
            if kospi_pick and etf
            else None
        ),
        "reasons": reasons,
        "horizon": f"향후 {report.get('horizon_label') or _horizon_label(int(report.get('horizon_days') or 21))}의 상대 점수",
    }
