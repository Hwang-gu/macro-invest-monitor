from __future__ import annotations

import html
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import requests

from .config import ROOT

KST = timezone(timedelta(hours=9))
NEWS_PER_KEYWORD = 3
CAT_ORDER = ("gold", "stock", "bitcoin", "others")
CAT_LABELS = {
    "gold": "Gold",
    "stock": "Stock",
    "bitcoin": "Bitcoin",
    "others": "Others",
}
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
_CACHE: dict[str, list[dict[str, str]]] = {}


def kst_today() -> str:
    return datetime.now(KST).date().isoformat()


def kst_today_ko() -> str:
    today = datetime.now(KST).date()
    return f"{today.year}년 {today.month}월 {today.day}일"


def load_subscribers() -> list[dict[str, Any]]:
    path = ROOT / "data" / "ted_newsletters.json"
    allowed = set(CAT_ORDER)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    out: list[dict[str, Any]] = []
    for key, row in data.items():
        email = str(key or "").strip().lower()
        if not email or "@" not in email or not isinstance(row, dict):
            continue
        if row.get("active") is False:
            continue
        raw_cats = row.get("categories") if isinstance(row.get("categories"), list) else []
        categories: list[str] = []
        for cat in raw_cats:
            name = str(cat or "").strip().lower()
            if name in allowed and name not in categories:
                categories.append(name)
        keywords: dict[str, list[str]] = {cat: [] for cat in CAT_ORDER}
        raw_kw = row.get("keywords")
        if isinstance(raw_kw, dict):
            for cat in CAT_ORDER:
                raw = raw_kw.get(cat)
                if isinstance(raw, list):
                    words = [str(s).strip() for s in raw if str(s).strip()]
                else:
                    words = _split_keywords(raw)
                keywords[cat] = words
        else:
            shared = raw_kw if isinstance(raw_kw, list) else _split_keywords(raw_kw)
            shared = [str(s).strip() for s in shared if str(s).strip()]
            for cat in categories:
                keywords[cat] = list(shared)
        if not categories:
            categories = [cat for cat in CAT_ORDER if keywords[cat]]
        items = subscriber_keyword_items(categories, keywords)
        if not items:
            continue
        out.append(
            {
                "email": email,
                "categories": categories,
                "keywords": keywords,
                "items": items,
            }
        )
    return out


def subscriber_keyword_items(
    categories: list[str], keywords: dict[str, list[str]]
) -> list[tuple[str, str]]:
    seen: set[str] = set()
    items: list[tuple[str, str]] = []
    for cat in categories:
        for word in keywords.get(cat) or []:
            key = word.casefold()
            if key in seen:
                continue
            seen.add(key)
            items.append((cat, word))
    return items


def _split_keywords(raw: Any) -> list[str]:
    return [s.strip() for s in str(raw or "").replace("，", ",").split(",") if s.strip()]


def fetch_hot_news(keyword: str, limit: int = NEWS_PER_KEYWORD) -> list[dict[str, str]]:
    cached = _CACHE.get(keyword)
    if cached is not None:
        return cached[:limit]
    articles = _fetch_google_news(keyword, today_only=True)
    if len(articles) < limit:
        extra = _fetch_google_news(keyword, today_only=False)
        articles = _merge_unique(articles, extra)
    articles = articles[:limit]
    _CACHE[keyword] = articles
    return articles


def build_html(subscriber: dict[str, Any], asof_ko: str) -> str:
    sections: list[str] = [
        "<div style=\"font-family:'Apple SD Gothic Neo',Malgun Gothic,sans-serif;"
        "font-size:15px;line-height:1.55;color:#222;max-width:640px\">",
        f"<p>앱에서 설정하신 관심 키워드 기준, <b>{html.escape(asof_ko)}</b> "
        "오전 가장 주목받는 뉴스입니다.</p>",
    ]
    current_cat = ""
    for cat, word in subscriber["items"]:
        if cat != current_cat:
            current_cat = cat
            sections.append(
                f"<h2 style='margin:22px 0 8px;font-size:18px'>{html.escape(CAT_LABELS.get(cat, cat))}</h2>"
            )
        sections.append(
            f"<h3 style='margin:14px 0 6px;font-size:16px'>키워드 · {html.escape(word)}</h3>"
        )
        news = fetch_hot_news(word)
        if not news:
            sections.append("<p style='color:#666'>오늘 관련 뉴스를 찾지 못했습니다.</p>")
            continue
        sections.append("<ol style='padding-left:20px;margin:0 0 8px'>")
        for item in news:
            title = html.escape(item["title"])
            link = html.escape(item["url"], quote=True)
            meta = " · ".join(p for p in (item.get("source"), item.get("when")) if p)
            meta_html = f"<br><span style='color:#666;font-size:13px'>{html.escape(meta)}</span>" if meta else ""
            sections.append(
                f"<li style='margin:0 0 10px'><a href='{link}'>{title}</a>{meta_html}</li>"
            )
        sections.append("</ol>")
    sections.append(
        "<p style='margin-top:28px;color:#666;font-size:13px'>"
        "수신 설정은 Ted Investment 앱의 Apply for news letter에서 바꿀 수 있습니다."
        "</p></div>"
    )
    return "".join(sections)


def _fetch_google_news(keyword: str, today_only: bool) -> list[dict[str, str]]:
    query = _google_query(keyword, today_only)
    url = (
        "https://news.google.com/rss/search?q="
        f"{quote(query)}&hl=ko&gl=KR&ceid=KR:ko"
    )
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": _UA})
        resp.raise_for_status()
    except requests.RequestException:
        return []
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return []
    articles: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in root.findall(".//item"):
        title = _clean_title(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        key = re.sub(r"\s+", " ", title).casefold()
        if key in seen:
            continue
        seen.add(key)
        source_el = item.find("source")
        source = (source_el.text or "").strip() if source_el is not None else ""
        if not source:
            source = _source_from_title(item.findtext("title") or "")
        articles.append(
            {
                "title": title,
                "url": link,
                "source": source,
                "when": _format_when(item.findtext("pubDate") or ""),
            }
        )
    time.sleep(0.2)
    return articles


def _google_query(keyword: str, today_only: bool) -> str:
    kw = keyword.strip()
    core = f'"{kw}"' if " " in kw else kw
    return f"{core} when:1d" if today_only else core


def _merge_unique(
    first: list[dict[str, str]], second: list[dict[str, str]]
) -> list[dict[str, str]]:
    seen = {re.sub(r"\s+", " ", row["title"]).casefold() for row in first}
    out = list(first)
    for row in second:
        key = re.sub(r"\s+", " ", row["title"]).casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _clean_title(raw: str) -> str:
    title = html.unescape(raw).strip()
    title = re.sub(r"\s+[-–—]\s+[^-–—]+$", "", title).strip()
    return title


def _source_from_title(raw: str) -> str:
    title = html.unescape(raw).strip()
    parts = re.split(r"\s+[-–—]\s+", title)
    return parts[-1].strip() if len(parts) > 1 else ""


def _format_when(raw: str) -> str:
    if not raw:
        return ""
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(KST)
    return local.strftime("%m/%d %H:%M")
