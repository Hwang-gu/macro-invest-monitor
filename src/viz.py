from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go

NODE_KO = {
    "us_3m": "미국 단기금리",
    "us_real_10y": "미국 실질금리",
    "us_curve_10_2": "장단기 스프레드",
    "vix": "VIX",
    "nasdaq": "나스닥",
    "usdkkrw": "원/달러",
    "kr_cpi_yoy": "한국 CPI",
    "gold": "금",
    "bitcoin": "비트코인",
    "kospi": "코스피",
    "kosdaq": "코스닥",
    "kr_semi": "한국 반도체",
    "kr_ship": "한국 조선",
    "us_finance": "미국 금융",
}

# 교과서 부호: +면 왼쪽이 오를 때 오른쪽도 오를 것으로 기대
TEXTBOOK = {
    ("us_3m", "usdkkrw"): "+",
    ("usdkkrw", "kr_cpi_yoy"): "+",
    ("us_3m", "kospi"): "-",
    ("usdkkrw", "kospi"): "+",
    ("us_real_10y", "gold"): "-",
    ("us_real_10y", "bitcoin"): "-",
    ("us_curve_10_2", "us_finance"): "+",
    ("nasdaq", "kosdaq"): "+",
    ("nasdaq", "kr_semi"): "+",
    ("usdkkrw", "kr_ship"): "+",
    ("vix", "gold"): "+",
}


ISSUE_FILL = {
    "war": "rgba(180,60,60,0.13)",
    "disease": "rgba(120,80,160,0.13)",
    "financial_crisis": "rgba(90,90,90,0.13)",
    "policy": "rgba(50,110,170,0.12)",
    "technology": "rgba(40,130,90,0.10)",
    "geopolitics": "rgba(170,110,40,0.12)",
}


def add_issue_bands(fig: go.Figure, events: pd.DataFrame, annotate: bool = True) -> go.Figure:
    """이슈 기간을 배경 띠로 표시합니다. 고강도만 이름을 붙입니다."""
    shown = 0
    for _, ev in events.iterrows():
        color = ISSUE_FILL.get(str(ev.get("category")), "rgba(120,120,120,0.10)")
        label = ev["name_ko"] if annotate and ev.get("severity") == "high" and shown < 8 else None
        kwargs: dict[str, Any] = dict(
            x0=ev["date"],
            x1=ev["end_date"],
            fillcolor=color,
            line_width=0,
        )
        if label:
            kwargs.update(
                annotation_text=label,
                annotation_position="top left",
                annotation_font_size=10,
            )
            shown += 1
        fig.add_vrect(**kwargs)
    return fig


def prices_with_issues(panel: pd.DataFrame, events: pd.DataFrame) -> go.Figure:
    from .config import series_by_key

    meta = series_by_key()
    cols = [c for c in ["gold", "bitcoin", "kospi", "kosdaq", "nasdaq", "sp500"] if c in panel.columns]
    norm = panel[cols].copy()
    for c in cols:
        first = norm[c].dropna().iloc[0]
        norm[c] = norm[c] / first * 100.0
    fig = go.Figure()
    for c in cols:
        fig.add_trace(go.Scatter(x=norm.index, y=norm[c], mode="lines", name=meta[c].label_ko if c in meta else c))
    add_issue_bands(fig, events)
    fig.update_layout(
        title="자산 상대 추이 (각자 시작=100) — 색 띠는 이슈 구간",
        yaxis_title="지수 (시작=100)",
        xaxis_title="날짜",
        height=480,
        legend_title="자산",
        margin=dict(l=10, r=10, t=48, b=10),
    )
    return fig


def strength_label(corr: float) -> str:
    a = abs(corr)
    if a >= 0.35:
        return "강한 규칙"
    if a >= 0.20:
        return "중간 규칙"
    if a >= 0.10:
        return "약한 경향"
    return "규칙 아님"


def channel_rows(channels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for ch in channels:
        src, dst = ch["src"], ch["dst"]
        c0 = float(ch["corr_0"])
        sign = "+" if c0 > 0 else "−"
        textbook = TEXTBOOK.get((src, dst), "")
        match = "맞음" if textbook and ((textbook == "+" and c0 > 0) or (textbook == "-" and c0 < 0)) else (
            "반대" if textbook else "—"
        )
        if abs(c0) < 0.08:
            match = "불명확"
        rows.append({
            "경로": ch["title"],
            "동월상관": round(c0, 3),
            "부호": sign,
            "교과서": textbook or "—",
            "데이터판정": match,
            "세기": strength_label(c0),
            "최강시차월": ch["best_lag"],
            "가설": ch["meaning"],
            "src": src,
            "dst": dst,
        })
    return rows


def transmission_sankey(channels: list[dict[str, Any]]) -> go.Figure:
    labels: list[str] = []
    index: dict[str, int] = {}

    def idx(key: str) -> int:
        if key not in index:
            index[key] = len(labels)
            labels.append(NODE_KO.get(key, key))
        return index[key]

    sources, targets, values, colors, hover = [], [], [], [], []
    for ch in channels:
        c0 = float(ch["corr_0"])
        if abs(c0) < 0.02:
            continue
        sources.append(idx(ch["src"]))
        targets.append(idx(ch["dst"]))
        values.append(max(abs(c0), 0.04) * 100)
        colors.append("rgba(185, 70, 70, 0.45)" if c0 < 0 else "rgba(50, 110, 170, 0.45)")
        hover.append(f"{ch['title']}<br>동월 상관 {c0:+.2f} · {strength_label(c0)}")

    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(
            label=labels,
            pad=18,
            thickness=16,
            line=dict(color="#888", width=0.4),
        ),
        link=dict(
            source=sources,
            target=targets,
            value=values,
            color=colors,
            customdata=hover,
            hovertemplate="%{customdata}<extra></extra>",
        ),
    ))
    fig.update_layout(
        title="2000년 이후 월간 변화의 파급 흐름 (굵기 = 상관 크기, 파랑 +, 빨강 −)",
        height=520,
        margin=dict(l=10, r=10, t=48, b=10),
        font=dict(size=13),
    )
    return fig


def today_rule_sankey(report: dict[str, Any]) -> go.Figure | None:
    regime = report.get("regime") or {}
    left: list[str] = []
    if regime.get("krw_strong"):
        left.append("원화 강세")
    if regime.get("krw_weak"):
        left.append("원화 약세")
    if regime.get("easing"):
        left.append("단기금리 하락")
    if regime.get("inverted_curve"):
        left.append("장단기 역전")
    if regime.get("risk_off"):
        left.append("위험회피")
    cats = {e.get("category") for e in (report.get("active_events") or [])}
    if "war" in cats:
        left.append("전쟁 이슈")
    if "technology" in cats:
        left.append("기술 이슈")
    if "policy" in cats:
        left.append("금리인하 사이클")
    if not left:
        return None

    edges = {
        "원화 강세": [("코스피", -1), ("한국 반도체", -1), ("한국 조선", -1)],
        "원화 약세": [("코스피", 1), ("한국 반도체", 1), ("한국 조선", 1)],
        "단기금리 하락": [("금", 1), ("비트코인", 1), ("나스닥", 1), ("코스닥", 1)],
        "장단기 역전": [("미국 금융", -1), ("한국 금융", -1)],
        "위험회피": [("금", 1), ("비트코인", -1), ("코스닥", -1), ("나스닥", -1)],
        "전쟁 이슈": [("금", 1)],
        "기술 이슈": [("나스닥", 1), ("한국 반도체", 1), ("미국 로봇", 1)],
        "금리인하 사이클": [("금", 1), ("비트코인", 1), ("나스닥", 1)],
    }
    labels: list[str] = []
    index: dict[str, int] = {}

    def idx(name: str) -> int:
        if name not in index:
            index[name] = len(labels)
            labels.append(name)
        return index[name]

    sources, targets, values, colors = [], [], [], []
    for src in left:
        for dst, sign in edges.get(src, []):
            sources.append(idx(src))
            targets.append(idx(dst))
            values.append(10)
            colors.append("rgba(185, 70, 70, 0.5)" if sign < 0 else "rgba(40, 130, 90, 0.5)")

    fig = go.Figure(go.Sankey(
        node=dict(label=labels, pad=16, thickness=16, line=dict(color="#888", width=0.4)),
        link=dict(source=sources, target=targets, value=values, color=colors),
    ))
    fig.update_layout(
        title="오늘 켜진 국면 → 점수에 실제로 더해지는 방향 (초록 가점, 빨강 감점)",
        height=420,
        margin=dict(l=10, r=10, t=48, b=10),
    )
    return fig


def write_html_report(
    path,
    report: dict[str, Any],
    channels: list[dict[str, Any]],
    panel: pd.DataFrame | None = None,
) -> None:
    from .process import load_events

    flow = transmission_sankey(channels)
    today = today_rule_sankey(report)
    rows = channel_rows(channels)
    table = "".join(
        "<tr>"
        f"<td>{r['경로']}</td><td>{r['동월상관']:+.2f}</td>"
        f"<td>{r['교과서']}</td><td>{r['데이터판정']}</td>"
        f"<td>{r['세기']}</td></tr>"
        for r in rows
    )
    pick = report.get("asset_label") or ""
    market = report.get("market_label") or report.get("if_stocks_market_label") or "—"
    sector = report.get("sector_label") or report.get("if_stocks_sector_label") or "—"
    fc = report.get("forecast") or {}
    stock_line = ""
    if fc.get("stage4_stock"):
        stock_line = f"<br/><b>코스피 종목:</b> {fc['stage4_stock']} ({fc.get('stage4_ticker')})"
    body = (report.get("commentary") or {}).get("display") or ""
    body_html = "<p>" + body.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
    parts = []
    if panel is not None:
        parts.append(prices_with_issues(panel, load_events()).to_html(full_html=False, include_plotlyjs="cdn"))
    parts.append(flow.to_html(full_html=False, include_plotlyjs=False if parts else "cdn"))
    if today is not None:
        parts.append(today.to_html(full_html=False, include_plotlyjs=False))
    price_html = parts[0] if panel is not None else ""
    flow_html = parts[1] if panel is not None else parts[0]
    today_html = parts[-1] if today is not None else "<p>켜진 국면 플래그가 없습니다.</p>"
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8"/>
  <title>매크로 브리핑 {report.get('asof')}</title>
  <style>
    body {{ font-family: "Malgun Gothic", sans-serif; max-width: 1080px; margin: 24px auto; color: #222; }}
    h1, h2 {{ font-weight: 600; }}
    .box {{ background: #f4f4f4; padding: 12px 16px; margin: 12px 0; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid #ddd; padding: 6px 8px; text-align: left; }}
    .note {{ color: #555; font-size: 13px; }}
  </style>
</head>
<body>
  <h1>매크로 배분 브리핑 · {report.get("asof")}</h1>
  <div class="box">
    <b>1단계 자산군:</b> {pick}<br/>
    <b>2단계 시장 / 3단계 업종:</b> {market} / {sector}
    {stock_line}
  </div>
  {body_html}
  <h2>그래프 (이슈 구간 음영)</h2>
  <p class="note">색 띠 = 전쟁·위기·팬데믹·정책. 고강도 이슈만 이름이 붙어 있습니다.</p>
  {price_html}
  <h2>역사 데이터로 본 파급 흐름</h2>
  {flow_html}
  <h2>교과서 vs 데이터</h2>
  <table>
    <tr><th>경로</th><th>동월 상관</th><th>교과서</th><th>데이터</th><th>세기</th></tr>
    {table}
  </table>
  <h2>오늘 점수에 들어간 규칙</h2>
  {today_html}
  <p class="note">{report.get("disclaimer", "")}</p>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
