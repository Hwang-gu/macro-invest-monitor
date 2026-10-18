from __future__ import annotations

import html
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

import requests
from lxml import html as lhtml

from .config import REPORTS_DIR, ROOT, gemini_api_key

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
    "joins.com": ("중앙일보", "conservative"),
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
PREFERRED_PRESS = {
    "조선일보",
    "조선비즈",
    "중앙일보",
    "동아일보",
    "한겨레",
    "한국경제",
    "문화일보",
    "국민일보",
}
PREFERRED_QUERY_NAMES = (
    "조선일보",
    "중앙일보",
    "동아일보",
    "한겨레",
    "한국경제",
    "문화일보",
    "국민일보",
)
NAVER_OID_PRESS = {
    "005": "국민일보",
    "015": "한국경제",
    "020": "동아일보",
    "021": "문화일보",
    "023": "조선일보",
    "025": "중앙일보",
    "028": "한겨레",
    "032": "경향신문",
    "009": "매일경제",
    "001": "연합뉴스",
}
PREFERRED_OIDS = ("023", "025", "020", "028", "015", "021", "005")
PRESS_HOME_URLS = (
    "https://www.chosun.com/",
    "https://www.joongang.co.kr/",
    "https://www.donga.com/",
    "https://www.hani.co.kr/",
    "https://www.hankyung.com/",
    "https://www.munhwa.com/",
    "https://www.kmib.co.kr/",
)
DIGEST_PATH = REPORTS_DIR / "news_digest.json"
_VIEW_RE = re.compile(r"([0-9][0-9,]*)\s*(?:회|명|view)", re.I)
_OID_RE = re.compile(r"/article/(\d{3})/", re.I)
_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": "https://www.naver.com/",
}
_CACHE: dict[str, list[dict[str, Any]]] = {}
_DIGEST: dict[str, Any] | None = None
_RANKING_POOL: list[dict[str, Any]] | None = None
_HOME_POOL: list[dict[str, Any]] | None = None


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
    cached = _digest_articles(keyword)
    if cached:
        return cached[:limit]
    mem = _CACHE.get(keyword)
    if mem is not None:
        return mem[:limit]
    articles = _collect_keyword_news(keyword, limit)
    _CACHE[keyword] = articles
    return articles


def collect_morning_digest(force: bool | None = None) -> Path:
    """평일 06:30 기준으로 조회수·상단 노출 뉴스를 모아 저장합니다."""
    global _DIGEST, _CACHE
    if force is None:
        force = os.getenv("TED_NEWS_FORCE", "").strip().lower() in {"1", "true", "yes", "on"}
    existing = _load_digest(allow_stale=True)
    if (
        not force
        and existing.get("asof") == kst_today()
        and isinstance(existing.get("keywords"), dict)
        and existing["keywords"]
    ):
        print(f"이미 {existing['asof']} 뉴스 스냅샷이 있어 재수집하지 않습니다.")
        return DIGEST_PATH
    ranking = _ranking_pool()
    homepage = _homepage_pool()
    print(f"랭킹 {len(ranking)}건, 언론사 상단 {len(homepage)}건")
    keywords: list[str] = []
    seen: set[str] = set()
    for sub in load_subscribers():
        for _cat, word in sub.get("items") or []:
            key = word.casefold()
            if key in seen:
                continue
            seen.add(key)
            keywords.append(word)
    digest = {
        "asof": kst_today(),
        "collected_at": datetime.now(KST).isoformat(timespec="minutes"),
        "keywords": {},
    }
    for word in keywords:
        rows = _collect_keyword_news(word, NEWS_PER_KEYWORD)
        digest["keywords"][word] = [{k: v for k, v in row.items() if k != "body"} for row in rows]
        print(f"  {word}: {len(digest['keywords'][word])}건")
    DIGEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIGEST_PATH.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
    _DIGEST = digest
    _CACHE = {word: rows for word, rows in digest["keywords"].items()}
    return DIGEST_PATH


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
            "<p style='margin:16px 0 8px 0;font-size:10pt;font-weight:bold;'>"
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
                "<p style='margin:16px 0 6px 0;font-size:12pt;font-weight:bold;line-height:1.4;'>"
                f"📌 <span style='font-size:12pt;font-weight:bold;'>{headline}</span></p>"
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
    ]
    articles: list[dict[str, Any]] = []
    for url in urls:
        parsed = _get_naver_search(url)
        for i, row in enumerate(parsed):
            row["search_rank"] = min(int(row.get("search_rank") or 99), i)
        articles = _merge_unique(articles, parsed)
        time.sleep(0.15)
    have = {row.get("source") for row in articles}
    for press in PREFERRED_QUERY_NAMES:
        if press in have:
            continue
        parsed = _get_naver_search(
            "https://search.naver.com/search.naver?where=news&query="
            f"{quote(keyword + ' ' + press)}&sm=tab_opt&sort=0&nso=so:r,p:1d"
        )
        articles = _merge_unique(articles, parsed)
        have = {row.get("source") for row in articles}
        time.sleep(0.12)
    return articles[:40]


def _get_naver_search(url: str) -> list[dict[str, Any]]:
    try:
        resp = requests.get(url, timeout=20, headers=_UA)
        resp.raise_for_status()
    except requests.RequestException:
        return []
    return _parse_naver_results(resp.text)


def _digest_articles(keyword: str) -> list[dict[str, Any]]:
    keywords = _load_digest().get("keywords")
    if not isinstance(keywords, dict):
        return []
    rows = keywords.get(keyword)
    if not isinstance(rows, list):
        for key, value in keywords.items():
            if str(key).casefold() == keyword.casefold() and isinstance(value, list):
                rows = value
                break
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and row.get("title") and row.get("url")]


def _load_digest(allow_stale: bool = False) -> dict[str, Any]:
    global _DIGEST
    if _DIGEST is not None and not allow_stale:
        return _DIGEST
    if not DIGEST_PATH.exists():
        _DIGEST = {}
        return _DIGEST
    try:
        data = json.loads(DIGEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _DIGEST = {}
        return _DIGEST
    if not isinstance(data, dict):
        _DIGEST = {}
        return _DIGEST
    if not allow_stale and data.get("asof") != kst_today():
        _DIGEST = {}
        return _DIGEST
    _DIGEST = data
    return _DIGEST


def _collect_keyword_news(keyword: str, limit: int) -> list[dict[str, Any]]:
    articles = _fetch_naver_news(keyword)
    articles = _merge_unique(articles, _keyword_hits(_ranking_pool(), keyword, unwrap=True))
    articles = _merge_unique(articles, _keyword_hits(_homepage_pool(), keyword, unwrap=False))
    ranking_thin = _naver_signals_thin()
    google = _fetch_google_news(keyword)
    if google:
        print(f"  google {keyword}: {len(google)}건 (네이버 조회수·랭킹 부족={ranking_thin})")
        articles = _merge_unique(articles, google)
    elif ranking_thin or len(articles) < 12:
        articles = _merge_unique(articles, _fetch_bing_news(keyword))
    if len(articles) < 12:
        articles = _merge_unique(articles, _fetch_bing_news(keyword))
    for i, row in enumerate(articles):
        row["score"] = _news_score(row, i)
    articles.sort(key=lambda row: int(row.get("score") or 0), reverse=True)
    articles = _dedupe_stories(articles)
    picked = _select_balanced(articles, limit)
    _fill_summaries(picked)
    return picked


def _keyword_hits(pool: list[dict[str, Any]], keyword: str, unwrap: bool) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in pool:
        title = str(row.get("title") or "")
        if not _matches_keyword(title, keyword):
            continue
        item = dict(row)
        url = str(item.get("url") or "")
        if unwrap:
            url = _unwrap_naver_article(url)
            item["url"] = url
        host = (urlparse(url).hostname or "").lower()
        if any(skip in host for skip in SKIP_HOSTS):
            continue
        name, lean = _press_info(host)
        if item.get("source") in PREFERRED_PRESS:
            name = item.get("source") or name
            lean = _lean_for_press(name) or lean
        item["source"] = name
        item["lean"] = lean
        item["press_key"] = name
        item.setdefault("snippet", "")
        item.setdefault("summary", [])
        out.append(item)
        if len(out) >= 8:
            break
    return out


def _matches_keyword(title: str, keyword: str) -> bool:
    text = re.sub(r"\s+", "", title).casefold()
    key = re.sub(r"\s+", "", keyword).casefold()
    if not key:
        return False
    return key in text


def _lean_for_press(name: str) -> str:
    for _host, (press, lean) in PRESS_BY_HOST.items():
        if press == name:
            return lean
    return "center"


def _news_score(row: dict[str, Any], search_index: int) -> int:
    source = str(row.get("source") or "")
    if source in PREFERRED_PRESS:
        score = 100
    elif source and source != "언론" and len(source) > 1:
        score = 45
    else:
        score = 15
    views = int(row.get("views") or 0)
    rank = int(row.get("rank_pos") or 0)
    if views:
        score += min(views // 1500, 80)
    if rank:
        score += max(0, (20 - rank) * 8)
    if row.get("from_ranking"):
        score += 160
    if row.get("from_home"):
        score += 120 + max(0, (12 - int(row.get("home_pos") or 12)) * 6)
    matched = _best_pool_match(row, _ranking_pool())
    if matched:
        score += 160
        score += min(int(matched.get("views") or 0) // 1500, 80)
        score += max(0, (20 - int(matched.get("rank_pos") or 20)) * 8)
    home = _best_pool_match(row, _homepage_pool())
    if home:
        score += 110 + max(0, (12 - int(home.get("home_pos") or 12)) * 6)
    score += max(0, 35 - int(row.get("search_rank") or search_index))
    if row.get("from_google"):
        bonus = 90 if _naver_signals_thin() else 55
        score += bonus + max(0, (12 - int(row.get("google_rank") or 12)) * 6)
    return score


def _naver_signals_thin() -> bool:
    pool = _ranking_pool()
    if len(pool) < 6:
        return True
    return not any(int(row.get("views") or 0) > 0 for row in pool)


def _best_pool_match(row: dict[str, Any], pool: list[dict[str, Any]]) -> dict[str, Any] | None:
    title = str(row.get("title") or "")
    url = str(row.get("url") or "")
    source = str(row.get("source") or "")
    best: dict[str, Any] | None = None
    for item in pool:
        if url and url == item.get("url"):
            return item
        if source and item.get("source") == source and _too_similar(title, str(item.get("title") or "")):
            return item
        if _too_similar(title, str(item.get("title") or "")):
            best = best or item
    return best


def _ranking_pool() -> list[dict[str, Any]]:
    global _RANKING_POOL
    if _RANKING_POOL is not None:
        return _RANKING_POOL
    stamp = datetime.now(KST).strftime("%Y%m%d")
    urls = [f"https://news.naver.com/main/ranking/popularDay.naver?date={stamp}"]
    urls.extend(f"https://media.naver.com/press/{oid}/ranking?type=popular&date={stamp}" for oid in PREFERRED_OIDS)
    pool: list[dict[str, Any]] = []
    for url in urls:
        pool = _merge_unique(pool, _parse_ranking_page(url))
        time.sleep(0.12)
    _RANKING_POOL = pool
    return pool


def _homepage_pool() -> list[dict[str, Any]]:
    global _HOME_POOL
    if _HOME_POOL is not None:
        return _HOME_POOL
    pool: list[dict[str, Any]] = []
    for url in PRESS_HOME_URLS:
        pool = _merge_unique(pool, _parse_press_home(url))
        time.sleep(0.12)
    _HOME_POOL = pool
    return pool


def _parse_ranking_page(url: str) -> list[dict[str, Any]]:
    try:
        resp = requests.get(url, timeout=20, headers=_UA)
        resp.raise_for_status()
    except requests.RequestException:
        return []
    try:
        doc = lhtml.fromstring(resp.text)
    except Exception:  # noqa: BLE001
        return []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    rank = 0
    for anchor in doc.xpath("//a[@href]"):
        href = _clean_url(anchor.get("href") or "")
        title = " ".join((anchor.text_content() or "").split())
        title = _clean_headline(title)
        if len(title) < 8:
            continue
        if href.startswith("/"):
            parsed = urlparse(url)
            href = f"{parsed.scheme}://{parsed.netloc}{href}"
        host = (urlparse(href).hostname or "").lower()
        oid_match = _OID_RE.search(href)
        press = NAVER_OID_PRESS.get(oid_match.group(1)) if oid_match else ""
        if not press:
            if any(skip in host for skip in SKIP_HOSTS):
                continue
            press, _lean = _press_info(host)
        key = _norm_title(title)
        if key in seen:
            continue
        seen.add(key)
        rank += 1
        parent = " ".join((anchor.getparent().text_content() if anchor.getparent() is not None else "")[:80].split())
        items.append(
            {
                "title": title,
                "url": href,
                "source": press,
                "lean": _lean_for_press(press),
                "press_key": press,
                "snippet": "",
                "summary": [],
                "views": _parse_views(parent),
                "rank_pos": rank,
                "from_ranking": True,
            }
        )
        if rank >= 40:
            break
    return items


def _parse_press_home(url: str) -> list[dict[str, Any]]:
    try:
        resp = requests.get(url, timeout=12, headers=_UA)
        resp.raise_for_status()
    except requests.RequestException:
        return []
    try:
        doc = lhtml.fromstring(resp.text)
    except Exception:  # noqa: BLE001
        return []
    host = (urlparse(url).hostname or "").lower()
    name, lean = _press_info(host)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for anchor in doc.xpath("//a[@href]"):
        href = _clean_url(anchor.get("href") or "")
        title = _clean_headline(" ".join((anchor.text_content() or "").split()))
        if href.startswith("/"):
            parsed = urlparse(url)
            href = _clean_url(f"{parsed.scheme}://{parsed.netloc}{href}")
        link_host = (urlparse(href).hostname or "").lower()
        if not href.startswith("http") or len(title) < 10:
            continue
        if any(skip in link_host for skip in SKIP_HOSTS):
            continue
        link_name, _link_lean = _press_info(link_host)
        if link_name != name:
            continue
        key = _norm_title(title)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "title": title,
                "url": href,
                "source": name,
                "lean": lean,
                "press_key": name,
                "snippet": "",
                "summary": [],
                "home_pos": len(items) + 1,
                "from_home": True,
            }
        )
        if len(items) >= 12:
            break
    return items


def _parse_views(text: str) -> int:
    match = _VIEW_RE.search(text or "")
    if not match:
        return 0
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return 0


def _unwrap_naver_article(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "naver.com" not in host:
        return url
    try:
        resp = requests.get(url, timeout=10, headers={**_UA, "Referer": "https://news.naver.com/"}, allow_redirects=True)
        resp.raise_for_status()
    except requests.RequestException:
        return url
    final = _clean_url(str(resp.url or url))
    if "naver.com" not in (urlparse(final).hostname or "").lower():
        return final
    text = resp.text[:180000]
    for pat in (
        r'property=["\']og:url["\'][^>]*content=["\']([^"\']+)',
        r'content=["\']([^"\']+)["\'][^>]*property=["\']og:url["\']',
        r'href=["\'](https?://(?!n\.news\.naver\.com)[^"\']+)["\'][^>]*class=["\'][^"\']*media_end_head_origin',
    ):
        match = re.search(pat, text, re.I)
        if not match:
            continue
        found = _clean_url(html.unescape(match.group(1)))
        if found.startswith("http") and "naver.com" not in (urlparse(found).hostname or "").lower():
            return found
    return url


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
                "search_rank": len(items),
            }
        )
    return items


def _fetch_google_news(keyword: str) -> list[dict[str, Any]]:
    articles = _fetch_google_news_html(keyword)
    if len(articles) < 8:
        articles = _merge_unique(articles, _fetch_google_news_rss(keyword))
    return articles[:25]


def _fetch_google_news_html(keyword: str) -> list[dict[str, Any]]:
    items = _parse_google_news_html(keyword, recent=True)
    if len(items) < 6:
        items = _merge_unique(items, _parse_google_news_html(keyword, recent=False))
    return items


def _parse_google_news_html(keyword: str, recent: bool) -> list[dict[str, Any]]:
    query = quote(f"{keyword} when:1d" if recent else keyword)
    url = f"https://www.google.com/search?tbm=nws&hl=ko&gl=kr&num=20&q={query}"
    try:
        resp = requests.get(url, timeout=20, headers={**_UA, "Referer": "https://www.google.com/"})
        resp.raise_for_status()
    except requests.RequestException:
        return []
    try:
        doc = lhtml.fromstring(resp.text)
    except Exception:  # noqa: BLE001
        return []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for anchor in doc.xpath("//a[@href]"):
        href = _unwrap_google_href(anchor.get("href") or "")
        title = _clean_headline(" ".join((anchor.text_content() or "").split()))
        if not href.startswith("http") or len(title) < 8:
            continue
        host = (urlparse(href).hostname or "").lower()
        if any(skip in host for skip in SKIP_HOSTS):
            continue
        key = _norm_title(title)
        if key in seen:
            continue
        seen.add(key)
        name, lean = _press_info(host)
        items.append(
            {
                "title": title,
                "url": href,
                "source": name,
                "lean": lean,
                "press_key": name,
                "snippet": "",
                "summary": [],
                "from_google": True,
                "google_rank": len(items) + 1,
            }
        )
        if len(items) >= 20:
            break
    return items


def _fetch_google_news_rss(keyword: str) -> list[dict[str, Any]]:
    articles = _parse_google_news_rss(f"{keyword} when:1d")
    if len(articles) < 6:
        articles = _merge_unique(articles, _parse_google_news_rss(keyword))
    return articles


def _parse_google_news_rss(query_text: str) -> list[dict[str, Any]]:
    query = quote(query_text)
    url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
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
    for rank, item in enumerate(root.findall(".//item"), start=1):
        title = html.unescape((item.findtext("title") or "").strip())
        title = _clean_headline(_strip_trailing_source(title))
        link = _unwrap_google_href(item.findtext("link") or "")
        if "google.com" in (urlparse(link).hostname or "").lower():
            desc = item.findtext("description") or ""
            found = re.search(r'href=["\'](https?://[^"\']+)["\']', html.unescape(desc))
            if found:
                link = _unwrap_google_href(found.group(1))
        if "google.com" in (urlparse(link).hostname or "").lower():
            link = _follow_url(link)
        if not title or not link.startswith("http"):
            continue
        host = (urlparse(link).hostname or "").lower()
        if any(skip in host for skip in SKIP_HOSTS):
            continue
        source_el = item.find("source")
        source_name = (source_el.text or "").strip() if source_el is not None else ""
        name, lean = _press_info(host)
        if source_name:
            name = source_name
            lean = _lean_for_press(name) or lean
        desc = html.unescape(re.sub(r"<[^>]+>", " ", item.findtext("description") or ""))
        articles.append(
            {
                "title": title,
                "url": link,
                "source": name,
                "lean": lean,
                "press_key": name,
                "snippet": " ".join(desc.split()),
                "summary": [],
                "from_google": True,
                "google_rank": rank,
            }
        )
    return articles


def _unwrap_google_href(href: str) -> str:
    href = (href or "").strip()
    if href.startswith("/url?"):
        qs = dict(parse_qsl(urlparse(href).query))
        href = qs.get("q") or qs.get("url") or href
    parsed = urlparse(href)
    if parsed.path == "/url":
        qs = dict(parse_qsl(parsed.query))
        href = qs.get("q") or qs.get("url") or href
    return _clean_url(href)


def _follow_url(url: str) -> str:
    try:
        resp = requests.get(url, timeout=10, headers=_UA, allow_redirects=True)
        final = _clean_url(str(resp.url or url))
        host = (urlparse(final).hostname or "").lower()
        if "google.com" not in host:
            return final
    except requests.RequestException:
        return url
    return url


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
        if any(_same_story(row, prev) for prev in picked):
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
    return picked[:limit]


def _dedupe_stories(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for row in articles:
        if any(_same_story(row, prev) for prev in kept):
            continue
        kept.append(row)
    return kept


def _same_story(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_url = _canonical_url(str(left.get("url") or ""))
    right_url = _canonical_url(str(right.get("url") or ""))
    if left_url and right_url and left_url == right_url:
        return True
    if _too_similar(str(left.get("title") or ""), str(right.get("title") or "")):
        return True
    left_snip = str(left.get("snippet") or "")[:120]
    right_snip = str(right.get("snippet") or "")[:120]
    if len(left_snip) >= 40 and len(right_snip) >= 40 and _too_similar(left_snip, right_snip):
        return True
    return False


def _canonical_url(url: str) -> str:
    parsed = urlparse(_clean_url(url))
    host = (parsed.hostname or "").lower()
    for prefix in ("www.", "m.", "news."):
        if host.startswith(prefix) and host.count(".") >= 2:
            host = host[len(prefix) :]
    path = re.sub(r"/+$", "", parsed.path or "").lower()
    return f"{host}{path}"


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
    ln = _norm_title(left)
    rn = _norm_title(right)
    if not ln or not rn:
        return False
    if ln == rn:
        return True
    if min(len(ln), len(rn)) >= 12 and (ln in rn or rn in ln):
        return True
    a = _stems(left)
    b = _stems(right)
    if not a or not b:
        return False
    matched: set[str] = set()
    overlap = 0
    for x in a:
        for y in b:
            if y in matched:
                continue
            if _stems_close(x, y):
                overlap += 1
                matched.add(y)
                break
    union = len(a) + len(b) - overlap
    if overlap >= 4:
        return True
    if overlap >= 3 and overlap / max(union, 1) >= 0.4:
        return True
    if min(len(a), len(b)) <= 5 and overlap >= 2 and overlap / max(union, 1) >= 0.45:
        return True
    return False


def _stems_close(left: str, right: str) -> bool:
    if left == right:
        return True
    if min(len(left), len(right)) >= 3 and (left in right or right in left):
        return True
    if min(len(left), len(right)) >= 3 and left[:2] == right[:2] and abs(len(left) - len(right)) <= 2:
        return True
    strip = r"(원|억원|조원|만원|억|조)$"
    return bool(re.sub(strip, "", left) and re.sub(strip, "", left) == re.sub(strip, "", right))


def _stems(text: str) -> set[str]:
    text = text.replace("美", "").replace("社", "개사")
    skip = {
        "관련",
        "오늘",
        "기자",
        "뉴스",
        "종합",
        "속보",
        "단독",
        "영상",
        "사진",
        "특징주",
        "코스피",
        "코스닥",
        "오후",
        "오전",
        "이번",
        "국내",
        "해외",
    }
    out: set[str] = set()
    for tok in re.findall(r"[가-힣A-Za-z0-9]{2,}", text):
        stem = re.sub(r"(에서|으로|에게|까지|부터|하는|된|할|에|로|을|를|이|가|은|는|의)$", "", tok)
        if len(stem) >= 2 and stem not in skip:
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
        fetched = _page_text(article["url"])
        if fetched:
            article["body"] = fetched
            if len((article.get("snippet") or "").strip()) < 80:
                article["snippet"] = fetched[:700]
    generated = _gemini_summaries(articles)
    for i, article in enumerate(articles):
        lines = generated.get(i)
        if not _usable_summary(lines, article):
            lines = _fallback_summary(article)
        article["summary"] = lines[:3]


def _page_text(url: str) -> str:
    try:
        resp = requests.get(url, timeout=12, headers={**_UA, "Referer": "https://search.naver.com/"})
        resp.raise_for_status()
        raw = resp.content.decode("utf-8", errors="replace")[:250000]
    except requests.RequestException:
        return ""
    if _looks_broken(raw[:500]):
        return ""
    chunks: list[str] = []
    for pat in (
        r'property=["\']og:description["\'][^>]*content=["\']([^"\']+)',
        r'content=["\']([^"\']+)["\'][^>]*property=["\']og:description["\']',
        r'name=["\']description["\'][^>]*content=["\']([^"\']+)',
    ):
        match = re.search(pat, raw, re.I)
        if match:
            desc = html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()
            if desc and not _looks_broken(desc):
                chunks.append(desc)
            break
    try:
        doc = lhtml.fromstring(raw)
    except Exception:  # noqa: BLE001
        return " ".join(chunks)[:2500]
    for xp in (
        "//article//p",
        "//*[@itemprop='articleBody']//p",
        "//*[contains(@class,'article-body')]//p",
        "//*[contains(@class,'article_body')]//p",
        "//*[contains(@class,'news_end')]//p",
        "//*[contains(@id,'article')]//p",
        "//p",
    ):
        found = False
        for node in doc.xpath(xp):
            text = " ".join((node.text_content() or "").split())
            if len(text) < 30 or _looks_broken(text):
                continue
            if re.search(r"(구독|로그인|댓글|광고|copyright|기자\s*페이지)", text, re.I):
                continue
            if text in chunks:
                continue
            chunks.append(text)
            found = True
            if sum(len(part) for part in chunks) >= 1800:
                break
        if found and sum(len(part) for part in chunks) >= 240:
            break
    return " ".join(chunks)[:2500]


def _page_snippet(url: str) -> str:
    return _page_text(url)[:700]


def _looks_broken(text: str) -> bool:
    if not text:
        return True
    return bool(re.search(r"(?:ì|í|ë|å|Â|Ã){4,}", text)) or "\ufffd" in text[:200]


_EMPTY_SUMMARY = re.compile(
    r"(관심이 모이|자세한 내용은|원문에서 확인|주요하게 다뤄|아래 URL|투자자들의 관심|"
    r"주목받고 있|이슈에 모이|확인하시기 바랍니다)"
)


def _usable_summary(lines: list[str] | None, article: dict[str, Any]) -> bool:
    if not lines or len(lines) < 3:
        return False
    cleaned = [str(line).strip() for line in lines if str(line).strip()]
    if len(cleaned) < 3:
        return False
    if any(_EMPTY_SUMMARY.search(line) for line in cleaned):
        return False
    title = str(article.get("title") or "")
    if sum(1 for line in cleaned if _too_similar(line, title)) >= 2:
        return False
    return True


def _fallback_summary(article: dict[str, Any]) -> list[str]:
    title = (article.get("title") or "관련 소식").strip()
    text = (article.get("body") or article.get("snippet") or "").strip()
    if _looks_broken(text) or len(text) < 40:
        text = " ".join(part for part in (article.get("snippet"), title) if part).strip()
    chunks = [
        re.sub(r"\s+", " ", part).strip(" -")
        for part in re.split(r"(?<=다)\.\s+|(?<=요)\.\s+|[.!?]\s+", text)
        if len(part.strip()) > 18 and not _looks_broken(part) and not _EMPTY_SUMMARY.search(part)
    ]
    useful: list[str] = []
    for part in chunks:
        if _too_similar(part, title) and useful:
            continue
        if any(_too_similar(part, prev) for prev in useful):
            continue
        useful.append(part.rstrip("."))
        if len(useful) >= 3:
            break
    if len(useful) < 3:
        extras = [p.strip(" ,") for p in re.split(r"[,;·]| 그리고 | 또한 ", text) if len(p.strip()) > 18]
        for part in extras:
            if _EMPTY_SUMMARY.search(part) or _too_similar(part, title):
                continue
            if any(_too_similar(part, prev) for prev in useful):
                continue
            useful.append(re.sub(r"\s+", " ", part).rstrip("."))
            if len(useful) >= 3:
                break
    if not useful:
        useful.append(title.rstrip("."))
    return useful[:3]


def _gemini_summaries(articles: list[dict[str, Any]]) -> dict[int, list[str]]:
    key = gemini_api_key()
    if not key or not articles:
        return {}
    try:
        from google import genai
    except ImportError:
        return {}
    payload = [
        {
            "i": i,
            "title": row.get("title") or "",
            "source": row.get("source") or "",
            "body": ((row.get("body") or row.get("snippet") or "")[:1400]),
        }
        for i, row in enumerate(articles)
    ]
    prompt = f"""헤드라인만 본 독자가 원문을 열지 않고도 기사 내용을 대략 이해하도록, 각 뉴스를 한국어 3문장으로 요약하세요.

규칙:
- 1문장: 누가/무엇이 무엇을 했는지, 결과를 구체적으로.
- 2문장: 수치, 당사자, 배경 등 본문에 나온 핵심 사실.
- 3문장: 쟁점이나 앞으로의 영향. 본문에 없으면 부가 사실을 나눠 쓰되 지어내지 말 것.
- 헤드라인을 그대로 반복하지 말 것.
- "~관심이 모이고 있습니다", "자세한 내용은 원문", "주요하게 다뤄졌습니다" 같은 빈 문장 금지.
- 투자 권유·추측 금지.
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
        if idx < 0 or idx >= len(articles):
            continue
        candidate = cleaned[:3]
        if _usable_summary(candidate, articles[idx]):
            out[idx] = candidate
    return out


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="키워드 뉴스 스냅샷")
    parser.add_argument("--collect", action="store_true", help="오전 뉴스 스냅샷을 수집합니다.")
    args = parser.parse_args()
    if args.collect:
        path = collect_morning_digest()
        print(f"뉴스 수집 완료: {path}")
        return
    raise SystemExit("사용법: python -m src.news_digest --collect")


if __name__ == "__main__":
    main()
