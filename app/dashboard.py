from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import PROCESSED_DIR, REPORTS_DIR, WORKBOOK_PATH, series_by_key  # noqa: E402
from src.process import load_events  # noqa: E402
from src.viz import add_issue_bands, channel_rows, prices_with_issues, today_rule_sankey, transmission_sankey  # noqa: E402

st.set_page_config(page_title="매크로 배분 모니터", layout="wide")
st.title("매크로 → 금 / 비트코인 / 주식 배분 모니터")
st.caption("2000년 이후 지수·금리·환율·물가·금·비트코인과 전쟁·질병·기술 이슈를 묶어, 앞으로 약 1개월 관점의 상대 점수를 보여 줍니다. 투자 권유가 아닙니다.")


@st.cache_data(ttl=300)
def load_latest() -> dict | None:
    path = REPORTS_DIR / "latest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@st.cache_data(ttl=300)
def load_panel() -> pd.DataFrame | None:
    pq = PROCESSED_DIR / "panel.parquet"
    csv = PROCESSED_DIR / "panel.csv"
    if pq.exists():
        return pd.read_parquet(pq)
    if csv.exists():
        df = pd.read_csv(csv, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index)
        return df
    return None


@st.cache_data(ttl=300)
def load_corr() -> pd.DataFrame | None:
    path = PROCESSED_DIR / "corr_full.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, index_col=0)


@st.cache_data(ttl=300)
def load_channels() -> list:
    path = PROCESSED_DIR / "transmission.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


@st.cache_data(ttl=300)
def load_study() -> pd.DataFrame | None:
    path = PROCESSED_DIR / "event_study.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)


report = load_latest()
panel = load_panel()

if report is None or panel is None:
    st.warning("아직 데이터가 없습니다. 프로젝트 폴더에서 `python -m src --mode history` 를 먼저 실행하세요.")
    st.stop()

meta = series_by_key()
r = report["regime"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("자산군", report["asset_label"])
c2.metric("주식 시장", report.get("market_label") or report.get("if_stocks_market_label") or "—")
c3.metric("업종", report.get("sector_label") or report.get("if_stocks_sector_label") or "—")
c4.metric("기준일", report["asof"])
if report.get("asset") not in {"kospi", "kosdaq", "nasdaq"}:
    st.caption("자산군이 주식이 아닐 때, 가운데 두 칸은 ‘만약 주식을 산다면’ 순위입니다.")

fc = report.get("forecast") or {}
if fc:
    st.subheader("Forecast Model (단계별)")
    f1, f2, f3, f4 = st.columns(4)
    f1.metric("1. 자산군", fc.get("stage1_asset_class") or "—")
    f2.metric("2. 주식이라면", fc.get("stage2_market") or "—")
    f3.metric("3. 업종", fc.get("stage3_sector") or "—")
    f4.metric("4. 코스피 종목", fc.get("stage4_stock") or "—")
    if fc.get("stage4_ticker"):
        st.caption(f"{fc.get('stage4_stock')} ({fc.get('stage4_ticker')}) · {fc.get('stage4_note') or ''}")
    if fc.get("reasons"):
        st.write("근거: " + " · ".join(fc["reasons"]))

st.info(report["commentary"]["display"])
st.caption(f"엑셀 장부: `{WORKBOOK_PATH}`  ·  Daily Data / Issue / Graph / Forecast Model 네 시트. 메일 설정이 있으면 엑셀+HTML을 첨부해 보냅니다.")

channels = load_channels()
st.subheader("규칙이 보이는 흐름")
st.caption("왼쪽이 원인, 오른쪽이 결과입니다. 선이 굵을수록 2000년 이후 월간 상관이 큽니다. 파랑은 같이 오르고, 빨강은 반대로 움직입니다.")
if channels:
    st.plotly_chart(transmission_sankey(channels), use_container_width=True)
    today_fig = today_rule_sankey(report)
    if today_fig is not None:
        st.plotly_chart(today_fig, use_container_width=True)
    rule_df = pd.DataFrame(channel_rows(channels))
    show = rule_df[["경로", "동월상관", "교과서", "데이터판정", "세기", "최강시차월", "가설"]]
    st.dataframe(show, use_container_width=True, hide_index=True)

with st.expander("금리·환율·물가 스냅샷", expanded=True):
    s1, s2, s3, s4, s5, s6 = st.columns(6)
    s1.metric("미국 3개월", f"{r.get('us_3m', float('nan')):.2f}%")
    s2.metric("미국 10년", f"{r.get('us_10y', float('nan')):.2f}%")
    s3.metric("장단기 10-2", f"{r.get('us_curve_10_2', float('nan')):.2f}%p")
    s4.metric("실질 10년", f"{r.get('us_real_10y', float('nan')):.2f}%")
    s5.metric("원/달러", f"{r.get('usdkkrw', float('nan')):.1f}")
    s6.metric("VIX", f"{r.get('vix', float('nan')):.1f}")
    st.write(
        f"미국 CPI 전년비 {r.get('us_cpi_yoy', float('nan')):.2f}% · "
        f"한국 CPI 전년비 {r.get('kr_cpi_yoy', float('nan')):.2f}% · "
        f"한국 콜 {r.get('kr_call', float('nan')):.2f}% · 한국 장기국채 {r.get('kr_10y', float('nan')):.2f}%"
    )
    if r.get("kr_cpi_last"):
        st.caption(f"한국 CPI 원자료 마지막 관측: {r['kr_cpi_last']} (FRED OECD가 끊기면 World Bank 연간 인플레로 대체). 미국 CPI 마지막 관측: {r.get('us_cpi_last') or '—'}")
    flags = []
    if r.get("easing"):
        flags.append("단기금리 하락(완화)")
    if r.get("inverted_curve"):
        flags.append("장단기 역전")
    if r.get("krw_strong"):
        flags.append("원화 강세")
    if r.get("krw_weak"):
        flags.append("원화 약세")
    if r.get("risk_off"):
        flags.append("위험회피")
    if flags:
        st.write("국면 플래그: " + " · ".join(flags))


def score_chart(title: str, mapping: dict, height: int = 280) -> None:
    if not mapping:
        return
    df = pd.DataFrame(
        [{"이름": meta[k].label_ko if k in meta else k, "예상 21일 수익률 점수": v} for k, v in mapping.items()]
    ).sort_values("예상 21일 수익률 점수")
    fig = px.bar(df, x="예상 21일 수익률 점수", y="이름", orientation="h", title=title)
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, use_container_width=True)


left, right = st.columns(2)
with left:
    score_chart("자산군 점수 (금 / 비트코인 / 주가지수)", report.get("asset_scores") or {})
with right:
    score_chart("주식 시장 점수", report.get("market_scores") or report.get("asset_scores") or {})
if report.get("sector_scores"):
    score_chart("업종 점수 (대용 지수·대표주)", report["sector_scores"], height=360)

st.subheader("가격 추이 + 이슈 구간")
st.caption("색 띠가 Issue 시트와 같은 기간입니다. 전쟁·위기·코로나·정책. 고강도만 이름이 붙습니다. 비트코인은 2014년 이후.")
events = load_events()
st.plotly_chart(prices_with_issues(panel, events), use_container_width=True)

macro_cols = [c for c in ["us_3m", "us_2y", "us_10y", "kr_call", "kr_10y"] if c in panel.columns]
fx_cols = [c for c in ["usdkkrw", "dxy"] if c in panel.columns]
m1, m2 = st.columns(2)
with m1:
    rates = panel[macro_cols].rename(columns={k: meta[k].label_ko for k in macro_cols})
    fig_r = px.line(rates, title="미국·한국 국채/콜 금리")
    fig_r.update_yaxes(title="금리 (%)")
    fig_r.update_xaxes(title="날짜")
    fig_r.update_layout(height=360, legend_title="금리")
    add_issue_bands(fig_r, events, annotate=False)
    st.plotly_chart(fig_r, use_container_width=True)
with m2:
    fx = panel[fx_cols].rename(columns={k: meta[k].label_ko for k in fx_cols})
    fig_f = px.line(fx, title="원/달러 · 달러인덱스")
    fig_f.update_yaxes(title="환율 / 지수")
    fig_f.update_xaxes(title="날짜")
    fig_f.update_layout(height=360, legend_title="환율")
    st.plotly_chart(fig_f, use_container_width=True)

st.subheader("월간 변화 상관 (전체 표본)")
corr = load_corr()
if corr is not None:
    fig_c = px.imshow(corr, color_continuous_scale="RdBu", color_continuous_midpoint=0, aspect="auto",
                      title="월간 변화량 상관계수")
    fig_c.update_layout(height=640)
    st.plotly_chart(fig_c, use_container_width=True)
    st.caption("금리·CPI는 월간 차이, 지수는 월간 수익률. 표본: 2000년(비트코인·일부 업종은 상장 이후) ~ 최근. 출처: Yahoo Finance, FRED")

st.subheader("이슈 이후 약 60거래일 수익률")
study = load_study()
if study is not None and not study.empty:
    show_cols = [c for c in ["date", "name_ko", "category", "gold", "bitcoin", "kospi", "kosdaq", "nasdaq", "usdkkrw"] if c in study.columns]
    pretty = study[show_cols].copy()
    pretty.columns = [{"date": "날짜", "name_ko": "이슈", "category": "유형", "gold": "금", "bitcoin": "비트코인",
                       "kospi": "코스피", "kosdaq": "코스닥", "nasdaq": "나스닥", "usdkkrw": "원/달러"}[c] for c in show_cols]
    pct_cols = [c for c in pretty.columns if c not in {"날짜", "이슈", "유형"}]
    st.dataframe(pretty.style.format({c: "{:.1%}" for c in pct_cols}), use_container_width=True, hide_index=True)

st.subheader("모형 검증 (후반 20% 기간)")
metrics = report.get("metrics") or {}
if metrics:
    mdf = pd.DataFrame(metrics).T
    mdf.index = [meta[k].label_ko if k in meta else k for k in mdf.index]
    st.dataframe(mdf, use_container_width=True)
    st.caption("R²가 낮거나 음수여도 정상입니다. 금융 시계열은 예측이 어렵고, 이 점수는 상대 순위용입니다.")

if report.get("active_events"):
    st.subheader("최근·진행 중 이슈")
    st.table(pd.DataFrame(report["active_events"]))

st.divider()
st.markdown(
    report["disclaimer"]
    + " 업종은 ETF·대표주로 대체했습니다(한국 반도체=SK하이닉스, 바이오=셀트리온, 금융=신한지주, 조선=HD한국조선해양, 로봇=LS일렉트릭). "
    "이슈 목록은 `data/events.json`에서 수정할 수 있습니다."
)
if report["commentary"].get("gemini"):
    st.caption("해설에 Gemini를 사용했습니다.")
