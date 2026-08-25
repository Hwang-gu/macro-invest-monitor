from __future__ import annotations

import json
from typing import Any

from .config import APP_DIR


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _md_to_html(text: str) -> str:
    parts = []
    for para in (text or "").split("\n\n"):
        line = _esc(para).replace("\n", "<br>")
        while "**" in line:
            if line.count("<b>") > line.count("</b>"):
                line = line.replace("**", "</b>", 1)
            else:
                line = line.replace("**", "<b>", 1)
        parts.append(f"<p>{line}</p>")
    return "".join(parts)


def _bars(mapping: dict | None, labels: dict[str, str]) -> str:
    if not mapping:
        return ""
    items = sorted(mapping.items(), key=lambda kv: kv[1], reverse=True)
    peak = max(abs(v) for _, v in items) or 1.0
    rows = []
    for key, val in items:
        name = labels.get(key, key)
        width = min(100.0, abs(val) / peak * 100.0)
        side = "pos" if val >= 0 else "neg"
        rows.append(
            f'<div class="bar-row"><span>{_esc(name)}</span>'
            f'<div class="bar-track"><i class="{side}" style="width:{width:.1f}%"></i></div>'
            f"<em>{val:+.3f}</em></div>"
        )
    return "".join(rows)


def write_mobile_app(report: dict[str, Any]) -> None:
    """휴대폰 홈 화면에 넣는 가벼운 웹앱을 만듭니다."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    fc = report.get("forecast") or {}
    regime = report.get("regime") or {}
    labels = {
        "gold": "금",
        "bitcoin": "비트코인",
        "kospi": "코스피",
        "kosdaq": "코스닥",
        "nasdaq": "나스닥",
        "us_semi": "미국 반도체",
        "us_bio": "미국 바이오",
        "us_finance": "미국 금융",
        "us_robotics": "미국 로봇",
        "kr_semi": "한국 반도체",
        "kr_bio": "한국 바이오",
        "kr_finance": "한국 금융",
        "kr_ship": "한국 조선",
        "kr_robot": "한국 로봇",
    }
    events = "".join(
        f'<li><b>{_esc(ev.get("name_ko") or "")}</b> <small>{_esc(ev.get("category") or "")}</small></li>'
        for ev in (report.get("active_events") or [])
    ) or "<li>진행 중으로 표시된 이슈가 없습니다.</li>"
    reasons = "".join(f"<li>{_esc(r)}</li>" for r in (fc.get("reasons") or [])) or "<li>추가 근거 없음</li>"
    stock = fc.get("stage4_stock") or "—"
    if fc.get("stage4_ticker"):
        stock = f"{fc['stage4_stock']} ({fc['stage4_ticker']})"
    body = _md_to_html((report.get("commentary") or {}).get("display") or "")
    payload = json.dumps(report, ensure_ascii=False, default=str).replace("</", "<\\/")

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
  <meta name="apple-mobile-web-app-capable" content="yes"/>
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"/>
  <meta name="theme-color" content="#0f1720"/>
  <link rel="manifest" href="manifest.json"/>
  <title>매크로 배분 · { _esc(str(report.get("asof") or "")) }</title>
  <style>
    :root {{ color-scheme: dark; }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #0f1720; color: #e8eef4; line-height: 1.45;
      padding: calc(18px + env(safe-area-inset-top)) 16px calc(28px + env(safe-area-inset-bottom));
    }}
    h1 {{ font-size: 1.15rem; margin: 0 0 4px; }}
    .sub {{ color: #9db0c2; font-size: 0.85rem; margin-bottom: 16px; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
    .card {{
      background: #182230; border: 1px solid #2a3b4d; border-radius: 14px;
      padding: 12px 14px; margin-bottom: 10px;
    }}
    .card.wide {{ grid-column: 1 / -1; }}
    .label {{ font-size: 0.72rem; color: #8ea3b7; letter-spacing: .04em; }}
    .value {{ font-size: 1.12rem; font-weight: 700; margin-top: 4px; }}
    p {{ margin: 0 0 10px; }}
    ul {{ margin: 0; padding-left: 18px; }}
    li {{ margin: 6px 0; }}
    .bar-row {{ display: grid; grid-template-columns: 7.5rem 1fr 3.4rem; gap: 8px; align-items: center; font-size: 0.82rem; margin: 6px 0; }}
    .bar-track {{ height: 8px; background: #243445; border-radius: 99px; overflow: hidden; }}
    .bar-track i {{ display: block; height: 100%; border-radius: 99px; }}
    .bar-track .pos {{ background: #3dd68c; }}
    .bar-track .neg {{ background: #e36b6b; }}
    .metrics {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 0.86rem; }}
    .metrics div {{ background: #121c27; border-radius: 10px; padding: 8px 10px; }}
    .note {{ color: #8ea3b7; font-size: 0.78rem; }}
  </style>
</head>
<body>
  <h1>매크로 배분 모니터</h1>
  <div class="sub">기준일 { _esc(str(report.get("asof") or "")) } · { _esc(str(fc.get("horizon") or "향후 약 21거래일")) }</div>
  <div class="grid">
    <div class="card"><div class="label">1. 자산군</div><div class="value">{_esc(str(fc.get("stage1_asset_class") or report.get("asset_label") or "—"))}</div></div>
    <div class="card"><div class="label">2. 주식이라면</div><div class="value">{_esc(str(fc.get("stage2_market") or "—"))}</div></div>
    <div class="card"><div class="label">3. 업종</div><div class="value">{_esc(str(fc.get("stage3_sector") or "—"))}</div></div>
    <div class="card"><div class="label">4. 코스피 종목</div><div class="value">{_esc(stock)}</div></div>
  </div>
  <div class="card">
    <div class="label">금리 · 환율</div>
    <div class="metrics" style="margin-top:8px">
      <div>미국 3개월<br><b>{regime.get("us_3m", float("nan")):.2f}%</b></div>
      <div>미국 10년<br><b>{regime.get("us_10y", float("nan")):.2f}%</b></div>
      <div>한국 기준금리<br><b>{regime.get("kr_call", float("nan")):.2f}%</b></div>
      <div>원/달러<br><b>{regime.get("usdkkrw", float("nan")):.1f}</b></div>
    </div>
  </div>
  <div class="card"><div class="label">오늘 해설</div>{body}</div>
  <div class="card"><div class="label">근거</div><ul>{reasons}</ul></div>
  <div class="card"><div class="label">진행 이슈</div><ul>{events}</ul></div>
  <div class="card"><div class="label">자산군 점수</div>{_bars(report.get("asset_scores"), labels)}</div>
  <div class="card"><div class="label">주식 시장 점수</div>{_bars(report.get("market_scores"), labels)}</div>
  <div class="card"><div class="label">업종 점수</div>{_bars(report.get("sector_scores"), labels)}</div>
  <p class="note">{_esc(str(report.get("disclaimer") or ""))} 홈 화면에 추가하면 앱처럼 열립니다. 매일 오전 7시(한국시간) 클라우드에서 갱신됩니다.</p>
  <script type="application/json" id="report">{payload}</script>
  <script>if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js");</script>
</body>
</html>
"""
    (APP_DIR / "index.html").write_text(html, encoding="utf-8")
    (APP_DIR / "latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (APP_DIR / "manifest.json").write_text(
        json.dumps(
            {
                "name": "매크로 배분 모니터",
                "short_name": "매크로배분",
                "start_url": "./",
                "display": "standalone",
                "background_color": "#0f1720",
                "theme_color": "#0f1720",
                "lang": "ko",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
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
