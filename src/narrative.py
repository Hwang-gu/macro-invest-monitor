from __future__ import annotations

from datetime import datetime
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


def _fmt(v: float | None, suffix: str = "", digits: int = 2) -> str:
    if v is None or v != v:
        return "n/a"
    return f"{v:.{digits}f}{suffix}"


def _asof_dot(asof: str | None) -> str:
    raw = str(asof or "")[:10]
    try:
        d = datetime.strptime(raw, "%Y-%m-%d")
        return f"{d.year}. {d.month}. {d.day}"
    except ValueError:
        return raw


def _band(v: float) -> str:
    if v <= -0.10:
        return "낮음"
    if v <= -0.03:
        return "다소 낮음"
    if v < 0.03:
        return "중립"
    if v < 0.10:
        return "다소 높음"
    return "높음"


def present_briefing(report: dict[str, Any], channels: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Present 탭: 거시·미시 현황을 서술형으로 정리합니다."""
    r = report.get("regime") or {}
    fc = report.get("forecast") or {}
    us3 = r.get("us_3m_chg_21")
    try:
        freeze = us3 is not None and us3 == us3 and abs(float(us3)) < 0.08
        hiking = us3 is not None and us3 == us3 and float(us3) > 0.08
    except (TypeError, ValueError):
        freeze, hiking = False, False
    semi = report.get("sector_scores") or {}
    kr_semi = float(semi.get("kr_semi") or 0)
    us_semi = float(semi.get("us_semi") or 0)
    asset = report.get("asset_scores") or {}
    kospi_s = float(asset.get("kospi") or 0)
    kosdaq_s = float(asset.get("kosdaq") or 0)
    nasdaq_s = float(asset.get("nasdaq") or 0)
    gold_s = float(asset.get("gold") or 0)
    btc_s = float(asset.get("bitcoin") or 0)

    paragraphs: list[str] = []
    if freeze:
        paragraphs.append(
            f"미국 단기금리는 최근 한 달 변화가 {_fmt(us3, '%p')}로 사실상 동결 구간에 가깝습니다. "
            "한·미 정책금리가 함께 멈춰 있으면 환율·자산 가격은 금리 자체보다 성장·지정학 이슈에 더 민감해지는 경향이 있습니다."
        )
    elif hiking:
        paragraphs.append(
            f"미국 단기금리가 최근 한 달 {_fmt(us3, '%p')} 오르는 구간입니다. "
            "금리 상승은 성장주·비트코인에는 부담, 원화 약세가 겹치면 수출 대형주에는 실적 기대를 키울 수 있습니다."
        )

    if r.get("krw_strong"):
        paragraphs.append("원/달러는 최근 하락(원화 강세)입니다. 수입 물가에는 우호적이나 코스피 수출 대형주 실적 눈높이에는 부담입니다.")
    elif r.get("krw_weak"):
        paragraphs.append("원/달러는 최근 상승(원화 약세)입니다. 반도체·조선 등 수출주에는 우호, 수입 물가에는 부담입니다.")

    if kr_semi > 0.02 or us_semi > 0.02 or nasdaq_s > kospi_s:
        paragraphs.append(
            "미시적으로는 AI·고대역폭 메모리 수요가 이어지며 반도체 쪽 상대 무게가 큽니다. "
            "한국에서는 SK하이닉스 대용 시계열이 그 경로를 대표하고, 대형 반도체 비중이 큰 코스피가 중소형(코스닥)보다 "
            f"{'앞서' if kospi_s > kosdaq_s else '덜 앞선 채'} 움직이고 있습니다."
        )
    elif kosdaq_s > kospi_s + 0.02:
        paragraphs.append("코스닥의 상대 무게가 코스피보다 큽니다. 대형주 주도라기보다 성장·중소형 쪽이 상대적으로 덜 눌린 국면으로 읽힙니다.")
    else:
        paragraphs.append("주식 안에서는 코스피·코스닥·나스닥의 상대 무게가 크게 갈리지 않습니다.")

    pick = fc.get("stage1_asset_class") or report.get("asset_label")
    if pick:
        paragraphs.append(f"지금 상대 무게가 가장 큰 자산군은 {pick}입니다.")

    events = report.get("active_events") or []
    if events:
        names = ", ".join(e.get("name_ko") or "" for e in events[:5])
        paragraphs.append(f"진행 중 이슈({names})가 금·성장주·방산/조선 무게에 가점·감점으로 들어가 있습니다.")

    if channels:
        notable = sorted(channels, key=lambda c: abs(c.get("corr_0") or 0), reverse=True)[:2]
        bits = [f"{c['title']} (동월 상관 {c['corr_0']:+.2f})" for c in notable]
        paragraphs.append("2000년 이후 데이터로 본 파급 경로: " + "; ".join(bits) + ".")

    names = {"gold": "금", "bitcoin": "비트코인", "kospi": "코스피", "kosdaq": "코스닥", "nasdaq": "나스닥"}
    scores = [
        {"name": names[k], "band": _band(float(v))}
        for k, v in sorted(asset.items(), key=lambda kv: kv[1], reverse=True)
        if k in names
    ]

    return {
        "title": f"{_asof_dot(report.get('asof'))} Ted's Briefing",
        "rates": [
            {"label": "한국은행 기준금리", "value": _fmt(r.get("kr_call"), "%")},
            {"label": "미국 단기금리", "value": _fmt(r.get("us_3m"), "%")},
            {"label": "미국 10년 금리", "value": _fmt(r.get("us_10y"), "%")},
            {"label": "원/달러", "value": _fmt(r.get("usdkkrw"), digits=1)},
        ],
        "paragraphs": paragraphs,
        "scores": scores,
        "footnote": (
            "상대 무게는 자산끼리 견준 점수입니다. 대략 -0.25(낮음)에서 +0.25(높음) 사이이고, "
            "중립은 0 근처입니다. 높을수록 그 자산에 상대적으로 더 무게를 둔다는 뜻이며, "
            "절대 수익률이나 매수·매도 신호가 아닙니다."
        ),
    }


def future_briefing(report: dict[str, Any], seasonal: dict[str, Any] | None = None) -> dict[str, Any]:
    """Future 탭: 상대 점수 기반 비중 방향을 짧게 제시합니다."""
    fc = report.get("forecast") or {}
    asset = report.get("asset_scores") or {}
    seasonal = seasonal or {}
    parts = [
        f"{fc.get('horizon') or '향후 약 21거래일'}의 상대 방향입니다. "
        "절대 수익 예고가 아니라 지금 점수상 어디에 더 무게를 둘지입니다."
    ]
    pick = fc.get("stage1_asset_class") or report.get("asset_label")
    parts.append(f"핵심 축은 **{pick}** 입니다.")
    parts.append(
        f"주식을 담는다면 **{fc.get('stage2_market') or '—'}**, "
        f"업종은 **{fc.get('stage3_sector') or '—'}** 쪽 점수가 높습니다."
    )
    if fc.get("stage4_stock"):
        parts.append(
            f"코스피로 내려가면 대표 종목 대용은 {fc['stage4_stock']}"
            + (f" ({fc.get('stage4_ticker')})" if fc.get("stage4_ticker") else "")
            + " 입니다. 업종 ETF·바스켓이 더 안전합니다."
        )
    names = {"gold": "금", "bitcoin": "비트코인", "kospi": "코스피", "kosdaq": "코스닥", "nasdaq": "나스닥"}
    ranked = sorted(asset.items(), key=lambda kv: kv[1], reverse=True)
    scores = [{"name": names[k], "band": _band(float(v))} for k, v in ranked if k in names]
    if seasonal.get("note"):
        parts.append(seasonal["note"])
    if fc.get("reasons"):
        parts.append("가점·감점 근거: " + " / ".join(fc["reasons"][:4]) + ".")
    return {
        "title": _asof_dot(report.get("asof")),
        "paragraphs": parts,
        "scores": scores,
        "footnote": (
            "상대 무게는 자산끼리 견준 점수입니다. 대략 -0.25(낮음)에서 +0.25(높음) 사이이고, "
            "중립은 0 근처입니다."
        ),
    }


def build_commentary(report: dict[str, Any], channels: list[dict[str, Any]] | None = None) -> dict[str, str]:
    rules = rule_commentary(report, channels)
    llm = gemini_commentary(report, channels)
    return {
        "rules": rules,
        "gemini": llm or "",
        "display": llm or rules,
    }
