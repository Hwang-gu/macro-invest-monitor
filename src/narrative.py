from __future__ import annotations

from typing import Any

from .config import gemini_api_key


def rule_commentary(report: dict[str, Any], channels: list[dict[str, Any]] | None = None) -> str:
    r = report["regime"]
    lines = []
    asof = report["asof"]
    lines.append(f"{asof} 기준, 앞으로 약 {report['horizon_days']}거래일 관점의 배분 점수입니다.")
    lines.append(
        f"1순위 자산군은 **{report['asset_label']}** 입니다."
        + (f" 주식 안에서는 **{report['market_label']}** 을 우선합니다." if report.get("market_label") else "")
        + (f" 업종은 **{report['sector_label']}** 쪽이 상대적으로 유리합니다." if report.get("sector_label") else "")
    )
    if report.get("asset") not in {"kospi", "kosdaq", "nasdaq"}:
        lines.append(
            "주식을 고르지 않은 날이지만, 주식만 본다면 "
            f"**{report.get('if_stocks_market_label') or '—'}**, 업종은 "
            f"**{report.get('if_stocks_sector_label') or '—'}** 점수가 상대적으로 높습니다."
        )

    def fmt(v: float | None, suffix: str = "") -> str:
        if v is None or v != v:
            return "n/a"
        return f"{v:.2f}{suffix}"

    lines.append(
        "금리·물가 스냅샷: "
        f"미국 3개월 {fmt(r.get('us_3m'), '%')}, 10년 {fmt(r.get('us_10y'), '%')}, "
        f"장단기(10-2) {fmt(r.get('us_curve_10_2'), '%p')}, "
        f"실질 10년 {fmt(r.get('us_real_10y'), '%')}, "
        f"미국 CPI 전년비 {fmt(r.get('us_cpi_yoy'), '%')}, "
        f"한국 CPI 전년비 {fmt(r.get('kr_cpi_yoy'), '%')}, "
        f"원/달러 {fmt(r.get('usdkkrw'))}."
    )

    if r.get("easing"):
        lines.append(
            "최근 1개월 미국 단기금리가 내려가는 구간입니다. "
            "전형적으로는 달러 약세·원화 강세, 수입물가 안정, 금·성장주·비트코인 우호 환경이 겹칠 수 있습니다. "
            "다만 원화가 강해지면 한국 수출 기업(반도체·조선 등) 실적 눈높이는 낮아질 수 있습니다."
        )
    elif r.get("us_3m_chg_21") == r.get("us_3m_chg_21") and r.get("us_3m_chg_21") > 0.10:
        lines.append(
            "단기금리가 오르는 구간입니다. 실질 기회비용이 커져 금·비트코인·고밸류에이션 성장주에 역풍이 될 수 있고, "
            "원/달러가 오르면 수입 물가 압력과 수출주 실적 기대가 동시에 커질 수 있습니다."
        )

    if r.get("krw_strong"):
        lines.append("원/달러가 최근 하락(원화 강세) 중입니다. 소비자물가에는 우호적이나 코스피 수출주에는 부담입니다.")
    elif r.get("krw_weak"):
        lines.append("원/달러가 최근 상승(원화 약세) 중입니다. 수출주에는 우호적이나 수입 물가·CPI 경로를 같이 봐야 합니다.")

    if r.get("inverted_curve"):
        lines.append("미국 장단기 금리가 역전되어 있습니다. 경기 둔화 신호로 금융주보다 방어 자산 가중치를 높이는 근거가 됩니다.")
    if r.get("risk_off"):
        lines.append("변동성(VIX) 또는 금리 역전으로 위험회피 점수를 가산했습니다.")

    events = report.get("active_events") or []
    if events:
        names = ", ".join(e["name_ko"] for e in events[:5])
        lines.append(f"최근·진행 중 이슈: {names}. 전쟁·질병은 금, 신기술은 나스닥·반도체·로봇 점수를 조정합니다.")

    if channels:
        notable = sorted(channels, key=lambda c: abs(c.get("corr_0") or 0), reverse=True)[:3]
        bits = [f"{c['title']} (동월 상관 {c['corr_0']:+.2f})" for c in notable]
        lines.append("데이터로 본 파급경로 중 상관이 큰 항목: " + "; ".join(bits) + ".")

    lines.append(report["disclaimer"])
    return "\n\n".join(lines)


def gemini_commentary(report: dict[str, Any], channels: list[dict[str, Any]] | None = None) -> str | None:
    key = gemini_api_key()
    if not key:
        return None
    try:
        from google import genai
    except ImportError:
        return None

    prompt = f"""당신은 매크로 투자 리서치 어시스턴트입니다. 아래 JSON은 연구용 점수이며 투자 권유가 아닙니다.
한국어로, 단정하지 말고, 인과를 '경향/가능성'으로만 설명하세요.
사용자가 관심 있는 경로: 미국 단기금리 → 원/달러 → 수입물가/CPI → 수출기업 실적.
금 vs 비트코인 vs 주식, 주식이면 코스피/코스닥/나스닥, 그다음 바이오/반도체/금융/로봇/조선.
200~350단어, 마크다운, 과한 확신 금지.

리포트:
{report}

파급경로(상위):
{(channels or [])[:8]}
"""
    client = genai.Client(api_key=key)
    last_err = None
    for model in ("gemini-2.5-pro", "gemini-2.0-flash", "gemini-flash-latest"):
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            text = getattr(resp, "text", None)
            if text:
                return text.strip()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            continue
    if last_err:
        print(f"Gemini 해설 생략: {last_err}")
    return None


def build_commentary(report: dict[str, Any], channels: list[dict[str, Any]] | None = None) -> dict[str, str]:
    rules = rule_commentary(report, channels)
    llm = gemini_commentary(report, channels)
    return {
        "rules": rules,
        "gemini": llm or "",
        "display": llm or rules,
    }
