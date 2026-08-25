from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from .analyze import (
    correlation_bundle,
    event_study,
    save_analysis,
    transmission_channels,
)
from .collect import collect_all, load_raw
from .config import APP_DIR, BRIEF_HTML, PROCESSED_DIR, REPORTS_DIR, WORKBOOK_PATH
from .model import allocate, train_models
from .narrative import build_commentary
from .notify import send_brief_if_configured
from .process import build_features, save_processed, to_panel
from .mobile import write_mobile_app
from .viz import write_html_report
from .workbook import update_workbook


def run(mode: str = "daily", skip_collect: bool = False) -> dict:
    full = mode == "history"
    if not skip_collect:
        print(f"== 데이터 수집 ({'전체' if full else '증분'}) ==")
        collect_all(full=full)
    else:
        print("수집 생략, 저장된 원본을 사용합니다.")

    raw = load_raw()
    print(f"원본 시리즈 {len(raw)}개")
    panel = to_panel(raw)
    features = build_features(panel)
    save_processed(panel, features)
    print(f"패널 {panel.index.min().date()} ~ {panel.index.max().date()}  ({len(panel)}일)")

    print("== 상관·파급경로·이벤트 ==")
    corr = correlation_bundle(features)
    channels = transmission_channels(features)
    study = event_study(panel)
    save_analysis(corr, channels, study)

    print("== 모델 학습 ==")
    bundle = train_models(panel, features)
    print(f"학습된 대상 {len(bundle['models'])}개")

    print("== 배분 점수 ==")
    report = allocate(panel, features, bundle)
    commentary = build_commentary(report, channels)
    report["commentary"] = commentary

    latest = REPORTS_DIR / "latest.json"
    stamp = REPORTS_DIR / f"{report['asof']}.json"
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    latest.write_text(text, encoding="utf-8")
    stamp.write_text(text, encoding="utf-8")

    summary = {
        "asof": report["asof"],
        "asset": report["asset_label"],
        "market": report.get("market_label"),
        "sector": report.get("sector_label"),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }
    print("추천:", json.dumps(summary, ensure_ascii=False))
    print(commentary["display"][:1200])

    print("== 엑셀 장부·브리핑 ==")
    update_workbook(panel, features, report, channels, corr)
    write_html_report(BRIEF_HTML, report, channels, panel=panel)
    write_mobile_app(report, panel=panel, channels=channels)
    print(f"엑셀: {WORKBOOK_PATH}")
    print(f"브리핑: {BRIEF_HTML}")
    print(f"모바일앱: {APP_DIR / 'index.html'}")
    print(send_brief_if_configured(report))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="매크로 배분 파이프라인")
    parser.add_argument("--mode", choices=["history", "daily"], default="daily")
    parser.add_argument("--skip-collect", action="store_true")
    args = parser.parse_args()
    run(mode=args.mode, skip_collect=args.skip_collect)


if __name__ == "__main__":
    main()
