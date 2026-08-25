from __future__ import annotations

import hashlib
import json
import shutil
from typing import Any

import numpy as np
import pandas as pd

from .config import APP_DIR, ROOT, ted_accounts
from .narrative import future_briefing, present_briefing
from .process import load_events

TEMPLATE = ROOT / "src" / "ted_app.html"
LOGO = ROOT / "src" / "logo.jpg"
CAT_KO = {
    "war": "전쟁",
    "disease": "질병",
    "technology": "신기술",
    "financial_crisis": "금융위기",
    "geopolitics": "지정학",
    "policy": "정책",
}


def _hash_account(role: str, user_id: str, pw: str) -> str:
    return hashlib.sha256(f"{role}|{user_id}|{pw}".encode("utf-8")).hexdigest()


def _monthly_values(series: pd.Series, ndigits: int) -> list[float | None]:
    return [None if v != v else round(float(v), ndigits) for v in series]


def _chart_bundle(panel: pd.DataFrame) -> dict[str, Any]:
    cols = [c for c in ["us_ffr", "kr_call", "kospi", "kosdaq", "nasdaq", "gold", "bitcoin"] if c in panel.columns]
    monthly = panel[cols].resample("ME").last()
    dates = [d.strftime("%Y-%m") for d in monthly.index]
    bundle: dict[str, Any] = {"dates": dates}
    digits = {"us_ffr": 3, "kr_call": 3, "kospi": 2, "kosdaq": 2, "nasdaq": 2, "gold": 2, "bitcoin": 1}
    for key in ("us_ffr", "kr_call", "kospi", "kosdaq", "nasdaq", "gold", "bitcoin"):
        if key in monthly:
            bundle[key] = _monthly_values(monthly[key], digits[key])
        else:
            bundle[key] = [None] * len(dates)
    return bundle


def _events_payload() -> list[dict[str, str]]:
    events = load_events()
    rows = []
    for _, ev in events.iterrows():
        rows.append({
            "start": pd.Timestamp(ev["date"]).strftime("%Y-%m-%d"),
            "end": pd.Timestamp(ev["end_date"]).strftime("%Y-%m-%d"),
            "name": str(ev["name_ko"]),
            "category": str(ev["category"]),
            "category_ko": CAT_KO.get(str(ev["category"]), str(ev["category"])),
        })
    return rows


def _weights(scores: dict[str, float] | None) -> dict[str, float]:
    if not scores:
        return {}
    keys = list(scores)
    xs = np.array([float(scores[k]) for k in keys], dtype=float)
    xs = np.clip(xs, -0.25, 0.25)
    e = np.exp((xs - np.nanmax(xs)) * 10.0)
    e = np.where(np.isfinite(e), e, 0.0)
    total = float(e.sum()) or 1.0
    return {k: round(float(w / total), 4) for k, w in zip(keys, e)}


def _seasonal_note(panel: pd.DataFrame, asof: str) -> dict[str, Any]:
    if "kosdaq" not in panel.columns:
        return {}
    m = panel["kosdaq"].resample("ME").last().pct_change().dropna()
    if m.empty:
        return {}
    by_month = m.groupby(m.index.month).mean()
    month = pd.Timestamp(asof).month
    nxt = 1 if month == 12 else month + 1
    avg = float(by_month.get(nxt, np.nan))
    if avg != avg:
        return {}
    winter = month in {11, 12, 1, 2}
    direction = "우상향" if avg > 0 else "우하향"
    note = (
        f"과거 코스닥의 {nxt}월 평균 월간 수익률은 {avg:+.1%}입니다. "
        + ("겨울 전후 구간에 해당합니다. " if winter else "")
        + f"단순 계절 평균일 뿐, 올해 {direction}을 단정하지 않습니다."
    )
    return {"next_month": nxt, "avg": avg, "note": note}


def write_mobile_app(
    report: dict[str, Any],
    panel: pd.DataFrame | None = None,
    channels: list[dict[str, Any]] | None = None,
) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    seasonal = _seasonal_note(panel, str(report.get("asof"))) if panel is not None else {}
    boot = {
        "asof": report.get("asof"),
        "auth": [
            {"role": a["role"], "id": a["id"], "hash": _hash_account(a["role"], a["id"], a["pw"])}
            for a in ted_accounts()
        ],
        "chart": _chart_bundle(panel) if panel is not None else {"dates": []},
        "events": _events_payload(),
        "present": present_briefing(report, channels),
        "future": future_briefing(report, seasonal),
        "weights": _weights(report.get("asset_scores")),
        "disclaimer": report.get("disclaimer"),
    }
    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "__BOOT__", json.dumps(boot, ensure_ascii=False, default=str).replace("</", "<\\/")
    )
    (APP_DIR / "index.html").write_text(html, encoding="utf-8")
    (APP_DIR / "latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (APP_DIR / "manifest.json").write_text(
        json.dumps(
            {
                "name": "Ted Investment",
                "short_name": "Ted Investment",
                "start_url": "./",
                "display": "standalone",
                "background_color": "#070b14",
                "theme_color": "#070b14",
                "lang": "ko",
                "icons": [
                    {
                        "src": "logo.jpg",
                        "sizes": "512x512",
                        "type": "image/jpeg",
                        "purpose": "any",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if LOGO.exists():
        shutil.copy2(LOGO, APP_DIR / "logo.jpg")
    (APP_DIR / "sw.js").write_text(
        """self.addEventListener("install", e => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(clients.claim()));
self.addEventListener("fetch", e => {
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
""",
        encoding="utf-8",
    )
    (APP_DIR / ".nojekyll").write_text("", encoding="utf-8")
