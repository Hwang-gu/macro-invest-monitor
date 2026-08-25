from __future__ import annotations

import time
from datetime import date, timedelta
from io import StringIO
from typing import Optional

import pandas as pd
import requests

from .config import (
    FDR_FALLBACK,
    RAW_DIR,
    START,
    Series,
    UNIVERSE,
    YAHOO_FALLBACK,
    bok_api_key,
)

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
ECOS_URL = "https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/100000/{stat}/{cycle}/{start}/{end}/{item}"


def _start_str(start: date | None = None) -> str:
    return (start or START).isoformat()


def _read_existing(key: str) -> pd.Series | None:
    path = RAW_DIR / f"{key}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["date"], index_col="date")
    if df.empty or "value" not in df.columns:
        return None
    s = df["value"].astype(float)
    s.name = key
    return s.sort_index()


def _save(key: str, series: pd.Series) -> pd.Series:
    series = series.dropna().sort_index()
    series = series[~series.index.duplicated(keep="last")]
    series.name = "value"
    out = series.to_frame()
    out.index.name = "date"
    path = RAW_DIR / f"{key}.csv"
    out.to_csv(path, date_format="%Y-%m-%d")
    return series


def _merge(old: pd.Series | None, new: pd.Series) -> pd.Series:
    new = new.dropna()
    if old is None or old.empty:
        return new
    combined = pd.concat([old, new])
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    return combined


def fetch_yahoo(ticker: str, start: date, key: str) -> pd.Series:
    import yfinance as yf

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            df = yf.download(
                ticker,
                start=start.isoformat(),
                auto_adjust=True,
                progress=False,
                threads=False,
                interval="1d",
            )
            if df is None or df.empty:
                raise ValueError(f"empty yahoo response for {ticker}")
            if isinstance(df.columns, pd.MultiIndex):
                flattened = None
                for level in range(df.columns.nlevels):
                    vals = df.columns.get_level_values(level)
                    if "Close" in set(vals) or "Adj Close" in set(vals):
                        flattened = vals
                        break
                df.columns = flattened if flattened is not None else [
                    "_".join(str(x) for x in c) for c in df.columns
                ]
            col = "Close" if "Close" in df.columns else "Adj Close" if "Adj Close" in df.columns else df.columns[0]
            s = df[col].astype(float)
            s.index = pd.to_datetime(s.index).tz_localize(None)
            s.name = key
            return s
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"yahoo failed {ticker}: {last_err}") from last_err


def fetch_fdr(code: str, start: date, key: str) -> pd.Series:
    import FinanceDataReader as fdr

    df = fdr.DataReader(code, start.isoformat())
    if df is None or df.empty:
        raise ValueError(f"empty FDR response for {code}")
    col = "Close" if "Close" in df.columns else "Adj Close" if "Adj Close" in df.columns else df.columns[-1]
    s = df[col].astype(float)
    s.index = pd.to_datetime(s.index).tz_localize(None)
    s.name = key
    return s


def fetch_fred(series_id: str, start: date, key: str) -> pd.Series:
    url = FRED_CSV.format(sid=series_id)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text))
    date_col = df.columns[0]
    val_col = df.columns[1]
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    values = pd.to_numeric(df[val_col].replace(".", pd.NA), errors="coerce")
    s = pd.Series(values.values, index=df[date_col], name=key)
    s = s.dropna()
    s = s[s.index >= pd.Timestamp(start)]
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s


BIS_KR_POLICY = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D.KR?format=csv"


def fetch_bis_kr_base() -> pd.Series:
    """BIS 한국 정책금리(한은 기준금리와 동일). 인증키 불필요."""
    resp = requests.get(BIS_KR_POLICY, timeout=60)
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text))
    if "TIME_PERIOD" not in df.columns or "OBS_VALUE" not in df.columns:
        raise ValueError("BIS 기준금리 응답 형식이 예상과 다릅니다.")
    idx = pd.to_datetime(df["TIME_PERIOD"], errors="coerce")
    val = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
    s = pd.Series(val.to_numpy(), index=idx, name="kr_call").dropna()
    s = s[s.index >= pd.Timestamp(START)]
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s.sort_index()


def fetch_ecos_optional(key: str) -> pd.Series | None:
    """한국은행 기준금리. 인증키가 있으면 ECOS에서 일별로 받습니다."""
    api_key = bok_api_key()
    if not api_key or key != "kr_call":
        return None
    start = START.strftime("%Y%m%d")
    end = date.today().strftime("%Y%m%d")
    attempts = (
        ("722Y001", "D", "0101000"),
        ("722Y001", "D", "0101000"),
        ("722Y001", "M", "0101000"),
    )
    last_msg = ""
    for stat, cycle, item in attempts:
        url = ECOS_URL.format(
            key=api_key, stat=stat, cycle=cycle, start=start, end=end, item=item
        )
        try:
            data = requests.get(url, timeout=60).json()
        except Exception as exc:  # noqa: BLE001
            last_msg = str(exc)
            continue
        err = data.get("RESULT") or data.get("result")
        if isinstance(err, dict) and err.get("CODE") not in {None, "INFO-000"}:
            last_msg = str(err.get("MESSAGE") or err)
            continue
        block = data.get("StatisticSearch") or data.get("StatisticSearch") or {}
        rows = block.get("row") or []
        if not rows:
            continue
        idx = pd.to_datetime([r["TIME"] for r in rows])
        val = pd.to_numeric([r["DATA_VALUE"] for r in rows], errors="coerce")
        s = pd.Series(val, index=idx, name=key).dropna()
        if s.empty:
            continue
        print(f"[kr_call] ECOS 한국은행 기준금리 n={len(s)} last={s.index.max().date()}")
        return s
    if last_msg:
        print(f"[kr_call] ECOS 실패 → BIS 일별 기준금리로 대체 ({last_msg})")
    return None


def _incremental_start(existing: pd.Series | None) -> date:
    if existing is None or existing.empty:
        return START
    last = existing.index.max().date()
    return last - timedelta(days=14)


def collect_one(spec: Series, full: bool = False) -> pd.Series:
    existing = None if full else _read_existing(spec.key)
    start = START if full else _incremental_start(existing)
    series: Optional[pd.Series] = None
    errors: list[str] = []

    if spec.source == "fred":
        ecos = fetch_ecos_optional(spec.key)
        if ecos is not None:
            series = ecos
        elif spec.key == "kr_call":
            try:
                series = fetch_bis_kr_base()
                print(
                    f"[kr_call] BIS 한은 기준금리(일별) n={len(series)} last={series.index.max().date()}"
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"bis: {exc}")
        if series is None:
            try:
                series = fetch_fred(spec.ticker, start, spec.key)
                if spec.key == "kr_call" and series is not None and not series.empty:
                    print(
                        f"[kr_call] FRED 콜금리(최후 대체) n={len(series)} last={series.index.max().date()}"
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
    else:
        tickers = [spec.ticker]
        if spec.key in YAHOO_FALLBACK:
            tickers.append(YAHOO_FALLBACK[spec.key])
        for ticker in tickers:
            try:
                series = fetch_yahoo(ticker, start, spec.key)
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"yahoo {ticker}: {exc}")
        if series is None and spec.key in FDR_FALLBACK:
            try:
                series = fetch_fdr(FDR_FALLBACK[spec.key], start, spec.key)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"fdr: {exc}")

    if series is None or series.empty:
        if existing is not None and not existing.empty:
            return existing
        raise RuntimeError(f"{spec.key} 수집 실패: {'; '.join(errors)}")

    merged = _merge(existing, series)
    return _save(spec.key, merged)


def collect_all(full: bool = False, pause: float = 0.4) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    failures: list[str] = []
    for spec in UNIVERSE:
        try:
            out[spec.key] = collect_one(spec, full=full)
            print(f"[ok] {spec.key:12} n={len(out[spec.key]):5} last={out[spec.key].index.max().date()}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{spec.key}: {exc}")
            print(f"[fail] {spec.key}: {exc}")
        time.sleep(pause)
    if failures:
        print("일부 시리즈 실패:\n  " + "\n  ".join(failures))
    if len(out) < 8:
        raise RuntimeError("핵심 시리즈가 충분히 모이지 않았습니다.")
    return out


def load_raw() -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    for spec in UNIVERSE:
        s = _read_existing(spec.key)
        if s is not None and not s.empty:
            out[spec.key] = s
    return out
