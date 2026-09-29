from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

import requests
from lxml import html as lhtml

from .config import ROOT, gemini_api_key

KST = timezone(timedelta(hours=9))
NEWS_PER_KEYWORD = 3
CAT_ORDER = ("gold", "stock", "bitcoin", "others")
CAT_LABELS = {
    "gold": "Gold",
    "stock": "Stock",
    "bitcoin": "Bitcoin",
    "others": "Others",
}
# lean: conservative | progressive | center
PRESS_BY_HOST = {
    "chosun.com": ("조선일보", "conservative"),
    "biz.chosun.com": ("조선비즈", "conservative"),
    "chosunbiz.com": ("조선비즈", "conservative"),
    "joongang.co.kr": ("중앙일보", "conservative"),
    "donga.com": ("동아일보", "conservative"),
    "hankyung.com": ("한국경제", "conservative"),
    "mk.co.kr": ("매일경제", "conservative"),
    "sedaily.com": ("서울경제", "conservative"),
    "munhwa.com": ("문화일보", "conservative"),
    "segye.com": ("세계일보", "conservative"),
    "kmib.co.kr": ("국민일보", "conservative"),
    "newdaily.co.kr": ("뉴데일리", "conservative"),
    "tvchosun.com": ("TV조선", "conservative"),
    "ichannela.com": ("채널A", "conservative"),
    "mbn.co.kr": ("MBN", "conservative"),
    "hani.co.kr": ("한겨레", "progressive"),
    "khan.co.kr": ("경향신문", "progressive"),
    "ohmynews.com": ("오마이뉴스", "progressive"),
    "pressian.com": ("프레시안", "progressive"),
    "seoul.co.kr": ("서울신문", "progressive"),
    "jtbc.co.kr": ("JTBC", "progressive"),
    "mediatoday.co.kr": ("미디어오늘", "progressive"),
    "sisain.co.kr": ("시사인", "progressive"),
    "yna.co.kr": ("연합뉴스", "center"),
    "yonhapnewstv.co.kr": ("연합뉴스TV", "center"),
    "newsis.com": ("뉴시스", "center"),
    "news1.kr": ("뉴스1", "center"),
    "edaily.co.kr": ("이데일리", "center"),
    "mt.co.kr": ("머니투데이", "center"),
    "fnnews.com": ("파이낸셜뉴스", "center"),
    "hankookilbo.com": ("한국일보", "center"),
    "nocutnews.co.kr": ("노컷뉴스", "center"),
    "ytn.co.kr": ("YTN", "center"),
    "kbs.co.kr": ("KBS", "center"),
    "sbs.co.kr": ("SBS", "center"),
    "imbc.com": ("MBC", "center"),
    "inews24.com": ("아이뉴스24", "center"),
    "thelec.kr": ("디일렉", "center"),
    "zdnet.co.kr": ("ZDNet", "center"),
    "bloter.net": ("블로터", "center"),
}
SKIP_HOSTS = ("naver.com", "google.com", "bing.com", "daum.net", "nate.com", "msn.com")
_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": "https://www.naver.com/",
}
_CACHE: dict[str, list[dict[str, Any]]] = {}


def kst_today() -> str:
    return datetime.now(KST).date().isoformat()


def kst_today_ko() -> str:
    today = datetime.now(KST).date()
    return f"{today.year}년 {today.month}월 {today.day}일"


def kst_md() -> str:
    today = datetime.now(KST).date()
    return f"{today.month}/{today.day}"


def mail_subject(subscriber: dict[str, Any]) -> str:
    labels = [CAT_LABELS[c] for c in subscriber.get("categories") or [] if c in CAT_LABELS]
    stamp = kst_md()
    if labels:
        return f"[Marchisio News] {stamp} {', '.join(labels)}"
    return f"[Marchisio News] {stamp}"


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


def fetch_hot_news(keyword: str, limit: int = NEWS_PER_KEYWORD) -> list[dict[str, Any]]:
    cached = _CACHE.get(keyword)
    if cached is not None:
        return cached[:limit]
    articles = _fetch_naver_news(keyword)
    if len(articles) < 12:
        articles = _merge_unique(articles, _fetch_bing_news(keyword))
    articles = _select_balanced(articles, limit)
    _fill_summaries(articles)
    _CACHE[keyword] = articles
    return articles


def build_html(subscriber: dict[str, Any], asof_ko: str | None = None) -> str:
    del asof_ko
    spacer = "<p style='margin:0;padding:0;line-height:10px;font-size:9pt;'>&nbsp;</p>"
    parts = [
        "<div style=\"font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;"
        "font-size:9pt;line-height:1.55;color:#222;max-width:720px\">",
        "<p style='margin:0 0 4px 0;font-size:9pt;'>Good morning Sir. This is Marchisio.</p>",
        spacer,
        spacer,
    ]
    first_kw = True
    for _cat, word in subscriber["items"]:
        if not first_kw:
            parts.append(spacer)
            parts.append(spacer)
        first_kw = False
        parts.append(
            "<p style='margin:16px 0 8px 0;font-size:9pt;font-weight:bold;'>"
            f"&lt; {html.escape(word)} &gt;</p>"
        )
        parts.append(spacer)
        news = fetch_hot_news(word)
        if not news:
            parts.append("<p style='margin:8px 0 16px 0;font-size:9pt;'>오늘 관련 뉴스를 찾지 못했습니다.</p>")
            continue
        for item in news:
            headline = html.escape(_headline(item))
            url = html.escape(item["url"], quote=True)
            parts.append(
                "<p style='margin:16px 0 6px 0;font-size:14pt;font-weight:bold;line-height:1.4;'>"
                f"📌 <span style='font-size:14pt;font-weight:bold;'>{headline}</span></p>"
            )
            for line in item.get("summary") or _fallback_summary(item):
                parts.append(
                    f"<p style='margin:2px 0;font-size:9pt;'>- {html.escape(line)}</p>"
                )
            parts.append(
                "<p style='margin:6px 0 14px 0;font-size:9pt;'>"
                f"URL: <a href='{url}' style='font-size:9pt;'>{html.escape(item['url'])}</a></p>"
            )
    parts.append("</div>")
    return "".join(parts)


def build_text(subscriber: dict[str, Any]) -> str:
    lines = ["Good morning Sir. This is Marchisio.", "", ""]
    first_kw = True
    for _cat, word in subscriber["items"]:
        if not first_kw:
            lines.append("")
        first_kw = False
        lines.append(f"< {word} >")
        lines.append("")
        news = fetch_hot_news(word)
        if not news:
            lines.append("오늘 관련 뉴스를 찾지 못했습니다.")
            lines.append("")
            continue
        for item in news:
            lines.append(f"📌 {_headline(item)}")
            for line in item.get("summary") or _fallback_summary(item):
                lines.append(f"- {line}")
            lines.append(f"URL: {item['url']}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _headline(item: dict[str, Any]) -> str:
    title = _strip_trailing_source((item.get("title") or "").strip())
    source = (item.get("source") or "").strip()
    if source and source not in title:
        return f"{title} - {source}"
    return title


def _fetch_naver_news(keyword: str) -> list[dict[str, Any]]:
    query = quote(keyword)
    urls = [
        f"https://search.naver.com/search.naver?where=news&query={query}&sm=tab_opt&sort=0&nso=so:r,p:1d",
        f"https://search.naver.com/search.naver?where=news&query={query}&sm=tab_opt&sort=0",
        f"https://search.naver.com/search.naver?where=news&query={quote(keyword + ' 한겨레')}&sm=tab_opt&sort=0&nso=so:r,p:1d",
        f"https://search.naver.com/search.naver?where=news&query={quote(keyword + ' 조선일보')}&sm=tab_opt&sort=0&nso=so:r,p:1d",
        f"https://search.naver.com/search.naver?where=news&query={quote(keyword + ' 경향신문')}&sm=tab_opt&sort=0&nso=so:r,p:1d",
        f"https://search.naver.com/search.naver?where=news&query={quote(keyword + ' 중앙일보')}&sm=tab_opt&sort=0&nso=so:r,p:1d",
    ]
    articles: list[dict[str, Any]] = []
    for url in urls:
        try:
            resp = requests.get(url, timeout=20, headers=_UA)
            resp.raise_for_status()
        except requests.RequestException:
            continue
        parsed = _parse_naver_results(resp.text)
        articles = _merge_unique(articles, parsed)
        time.sleep(0.15)
    return articles[:30]


def _parse_naver_results(page: str) -> list[dict[str, Any]]:
    try:
        doc = lhtml.fromstring(page)
    except Exception:  # noqa: BLE001
        return []
    items: list[dict[str, Any]] = []
    index: dict[str, int] = {}
    for anchor in doc.xpath("//a[@href]"):
        href = _clean_url(anchor.get("href") or "")
        title = " ".join((anchor.text_content() or "").split())
        if not href.startswith("http") or len(title) < 8:
            continue
        host = (urlparse(href).hostname or "").lower()
        if any(skip in host for skip in SKIP_HOSTS):
            continue
        name, lean = _press_info(host)
        if href in index:
            row = items[index[href]]
            cleaned = _clean_headline(title)
            if len(cleaned) < len(row["title"]) and len(cleaned) >= 10:
                if len(row["title"]) > len(cleaned) + 10:
                    row["snippet"] = row.get("snippet") or row["title"]
                row["title"] = cleaned
            elif len(title) > len(row["title"]) + 10:
                row["snippet"] = title
            continue
        index[href] = len(items)
        items.append(
            {
                "title": _clean_headline(title),
                "url": href,
                "source": name,
                "lean": lean,
                "press_key": name,
                "snippet": title if len(title) > 80 else "",
                "summary": [],
            }
        )
    return items


def _fetch_bing_news(keyword: str) -> list[dict[str, Any]]:
    url = f"https://www.bing.com/news/search?q={quote(keyword)}&format=rss"
    try:
        resp = requests.get(url, timeout=20, headers=_UA)
        resp.raise_for_status()
    except requests.RequestException:
        return []
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return []
    articles: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = html.unescape((item.findtext("title") or "").strip())
        link = _clean_url(_unwrap_bing_url(item.findtext("link") or ""))
        if not title or not link.startswith("http"):
            continue
        host = (urlparse(link).hostname or "").lower()
        if any(skip in host for skip in SKIP_HOSTS):
            continue
        name, lean = _press_info(host)
        desc = html.unescape(re.sub(r"<[^>]+>", " ", item.findtext("description") or ""))
        articles.append(
            {
                "title": _clean_headline(title),
                "url": link,
                "source": name,
                "lean": lean,
                "press_key": name,
                "snippet": " ".join(desc.split()),
                "summary": [],
            }
        )
    return articles


def _unwrap_bing_url(link: str) -> str:
    parsed = urlparse(link)
    qs = dict(parse_qsl(parsed.query))
    return qs.get("url") or link


def _clean_headline(title: str) -> str:
    title = title.replace("새 창 열림", " ").replace("Keep 저장", " ").replace("Keep", " ")
    title = re.split(r"새 창", title)[0]
    title = _strip_trailing_source(title)
    title = re.sub(r"\s+", " ", title).strip(" -|")
    if len(title) > 90:
        cut = title[:90]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        title = cut.rstrip(".,…") + "…"
    return title


def _strip_trailing_source(title: str) -> str:
    title = re.sub(r"\s+[-–—]\s+[^-–—]{1,40}$", "", title).strip()
    title = re.sub(r"\s+\([^)]{1,20}\)$", "", title).strip()
    return title


def _select_balanced(articles: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    picked: list[dict[str, Any]] = []
    used_press: set[str] = set()

    def try_add(row: dict[str, Any]) -> bool:
        if row in picked:
            return False
        press = row.get("press_key") or row.get("source") or ""
        if press and press in used_press:
            return False
        if any(_too_similar(row["title"], prev["title"]) for prev in picked):
            return False
        picked.append(row)
        if press:
            used_press.add(press)
        return True

    for lean in ("conservative", "progressive", "center"):
        if len(picked) >= limit:
            break
        for row in articles:
            if (row.get("lean") or "center") != lean:
                continue
            if try_add(row):
                break

    for row in articles:
        if len(picked) >= limit:
            break
        try_add(row)

    if len(picked) < limit:
        for row in articles:
            if len(picked) >= limit:
                break
            if row not in picked:
                picked.append(row)
    return picked[:limit]


def _diverse(articles: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    picked: list[dict[str, Any]] = []
    for row in articles:
        if any(_too_similar(row["title"], prev["title"]) for prev in picked):
            continue
        picked.append(row)
        if len(picked) >= limit:
            break
    if len(picked) < limit:
        for row in articles:
            if row in picked:
                continue
            picked.append(row)
            if len(picked) >= limit:
                break
    return picked


def _too_similar(left: str, right: str) -> bool:
    a = _stems(left)
    b = _stems(right)
    if len(a) < 3 or len(b) < 3:
        return False
    overlap = set(a) & set(b)
    extra = 0
    for x in a:
        for y in b:
            if x == y:
                continue
            if min(len(x), len(y)) >= 3 and (x in y or y in x):
                extra += 1
                break
    return len(overlap) + min(extra, 3) >= 4


def _stems(text: str) -> set[str]:
    text = text.replace("美", "").replace("社", "개사")
    out: set[str] = set()
    for tok in re.findall(r"[가-힣A-Za-z0-9]{2,}", text):
        stem = re.sub(r"(에서|으로|에게|까지|부터|하는|된|할|에|로|을|를|이|가|은|는|의)$", "", tok)
        if len(stem) >= 2:
            out.add(stem)
    return out


def _merge_unique(
    first: list[dict[str, Any]], second: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    seen = {_norm_title(row["title"]) for row in first}
    seen_url = {row["url"] for row in first}
    out = list(first)
    for row in second:
        if row["url"] in seen_url or _norm_title(row["title"]) in seen:
            continue
        seen.add(_norm_title(row["title"]))
        seen_url.add(row["url"])
        out.append(row)
    return out


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).casefold()


def _press_info(host: str) -> tuple[str, str]:
    host = (host or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host in PRESS_BY_HOST:
        return PRESS_BY_HOST[host]
    for key, val in PRESS_BY_HOST.items():
        if host.endswith("." + key) or host == key:
            return val
    parts = [p for p in host.split(".") if p not in {"www", "news", "biz", "m"}]
    label = parts[0] if parts else "언론"
    return (label, "center")


def _clean_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    drop = {"input", "from", "ntt", "did", "sid", "division"}
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in drop
    ]
    return urlunparse(parsed._replace(query=urlencode(query), fragment=""))


def _fill_summaries(articles: list[dict[str, Any]]) -> None:
    for article in articles:
        snippet = (article.get("snippet") or "").strip()
        if len(snippet) < 40:
            fetched = _page_snippet(article["url"])
            if fetched:
                article["snippet"] = fetched
    generated = _gemini_summaries(articles)
    for i, article in enumerate(articles):
        lines = generated.get(i) or _fallback_summary(article)
        article["summary"] = lines[:3]


def _page_snippet(url: str) -> str:
    try:
        resp = requests.get(url, timeout=8, headers={**_UA, "Referer": "https://search.naver.com/"})
        resp.raise_for_status()
        text = resp.content.decode("utf-8", errors="replace")[:200000]
    except requests.RequestException:
        return ""
    if _looks_broken(text[:500]):
        return ""
    for pat in (
        r'property=["\']og:description["\'][^>]*content=["\']([^"\']+)',
        r'content=["\']([^"\']+)["\'][^>]*property=["\']og:description["\']',
        r'name=["\']description["\'][^>]*content=["\']([^"\']+)',
    ):
        match = re.search(pat, text, re.I)
        if match:
            return html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    return ""


def _looks_broken(text: str) -> bool:
    if not text:
        return True
    return bool(re.search(r"(?:ì|í|ë|å|Â|Ã){4,}", text)) or "\ufffd" in text[:200]


def _fallback_summary(article: dict[str, Any]) -> list[str]:
    title = (article.get("title") or "관련 소식").strip()
    text = (article.get("snippet") or "").strip()
    if _looks_broken(text) or len(text) < 20:
        text = title
    chunks = [
        re.sub(r"\s+", " ", part).strip(" -")
        for part in re.split(r"(?<=다)\.\s+|(?<=요)\.\s+|[.!?]\s+", text)
        if len(part.strip()) > 8 and not _looks_broken(part)
    ]
    while len(chunks) < 3:
        if not chunks:
            chunks.append(f"{title} 관련 소식이 오늘 오전 주요하게 다뤄졌습니다.")
        elif len(chunks) == 1:
            chunks.append("관련 업계와 투자자들의 관심이 이 이슈에 모이고 있습니다.")
        else:
            chunks.append("자세한 내용은 아래 원문에서 확인할 수 있습니다.")
    return [chunk.rstrip(".") for chunk in chunks[:3]]


def _gemini_summaries(articles: list[dict[str, Any]]) -> dict[int, list[str]]:
    key = gemini_api_key()
    if not key or not articles:
        return {}
    try:
        from google import genai
    except ImportError:
        return {}
    payload = [
        {"i": i, "title": row.get("title") or "", "snippet": (row.get("snippet") or "")[:500]}
        for i, row in enumerate(articles)
    ]
    prompt = f"""다음 뉴스 목록을 각각 한국어로 핵심만 3문장 요약하세요.
규칙:
- 각 뉴스마다 문장 3개. 한 문장은 한 줄.
- 사실과 맥락만. 투자 권유·단정 금지.
- JSON만 출력: [{{"i":0,"lines":["문장1","문장2","문장3"]}}, ...]

뉴스:
{json.dumps(payload, ensure_ascii=False)}
"""
    client = genai.Client(api_key=key)
    raw = ""
    for model in ("gemini-2.0-flash", "gemini-flash-latest", "gemini-2.5-pro"):
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            raw = (getattr(resp, "text", None) or "").strip()
            if raw:
                break
        except Exception as exc:  # noqa: BLE001
            print(f"Gemini 뉴스 요약 생략({model}): {exc}")
            continue
    if not raw:
        return {}
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.I | re.M).strip()
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    out: dict[int, list[str]] = {}
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row.get("i"))
        except (TypeError, ValueError):
            continue
        lines = row.get("lines")
        if not isinstance(lines, list):
            continue
        cleaned = [str(line).strip().lstrip("- ").strip() for line in lines if str(line).strip()]
        if len(cleaned) >= 3:
            out[idx] = cleaned[:3]
    return out
