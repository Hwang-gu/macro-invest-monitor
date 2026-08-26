from __future__ import annotations

import hashlib
import json
import os
import shutil
from typing import Any

import numpy as np
import pandas as pd

from .config import APP_DIR, ROOT, START, ted_accounts
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


def _extra_user_records() -> list[dict[str, Any]]:
    path = ROOT / "data" / "ted_users.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        user_id = str(item.get("id", "")).strip()
        hashed = str(item.get("hash", "")).strip().lower()
        key = user_id.lower()
        if not user_id or key in seen or len(hashed) != 64:
            continue
        if any(ch not in "0123456789abcdef" for ch in hashed):
            continue
        seen.add(key)
        row: dict[str, Any] = {"role": "User", "id": user_id, "hash": hashed}
        updated = item.get("updated")
        if isinstance(updated, (int, float)) and updated > 0:
            row["updated"] = int(updated)
        rows.append(row)
    return rows


def _monthly_values(series: pd.Series, ndigits: int) -> list[float | None]:
    return [None if v != v else round(float(v), ndigits) for v in series]


def _chart_bundle(panel: pd.DataFrame) -> dict[str, Any]:
    cols = [c for c in ["us_ffr", "kr_call", "kospi", "kosdaq", "nasdaq", "gold", "bitcoin"] if c in panel.columns]
    monthly = panel[cols].resample("ME").last()
    monthly = monthly[monthly.index >= pd.Timestamp(START)]
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
    start = pd.Timestamp(START)
    for _, ev in events.iterrows():
        ev_end = pd.Timestamp(ev["end_date"])
        ev_start = pd.Timestamp(ev["date"])
        if ev_end < start:
            continue
        rows.append({
            "start": max(ev_start, start).strftime("%Y-%m-%d"),
            "end": ev_end.strftime("%Y-%m-%d"),
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
    extra_users = _extra_user_records()
    token = os.getenv("TED_SYNC_TOKEN", "").strip()
    boot = {
        "asof": report.get("asof"),
        "auth": [
            {
                "role": a["role"],
                "id": a["id"],
                "hash": _hash_account(a["role"], a["id"], a["pw"]),
                "source": "env",
            }
            for a in ted_accounts()
        ]
        + extra_users,
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
    sync_js = APP_DIR / "sync.js"
    if token:
        sync_js.write_text(
            "window.TED_SYNC_TOKEN = " + json.dumps(token) + ";\n",
            encoding="utf-8",
        )
    elif sync_js.exists():
        sync_js.unlink()
    (APP_DIR / "users.json").write_text(
        json.dumps(extra_users, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
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
  e.respondWith(fetch(e.request, {cache: "no-store"}).catch(() => caches.match(e.request)));
});
""",
        encoding="utf-8",
    )
    (APP_DIR / ".nojekyll").write_text("", encoding="utf-8")
