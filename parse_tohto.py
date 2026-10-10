"""Parser for 株式会社東都 (リロの不動産, 千歳烏山店 ほか), new.tohto.ne.jp.

The site runs on the Reblo platform. Search results are server-rendered and,
without ``def=1``, list one ``article.room-card`` per room. 東都 manages many
pet-friendly buildings (シャーメゾン等) across Tokyo and Kanagawa, so the search
is not limited by area; conditions.py drops what is out of range.
robots.txt only disallows the ajax_*.php endpoints (Crawl-delay for bing only).
"""

import html
import re
from urllib.parse import urlencode

BASE_URL = "https://new.tohto.ne.jp"

TOHTO_PARAMS = [
    ("search_equip[0]", "32"),  # ペット相談
    ("search_madori[0]", "7"), ("search_madori[1]", "10"), ("search_madori[2]", "11"),  # 2LDK(+S) / 3LDK(+S) / 4K〜
    ("search_price_limit", "250000"),  # 25万円未満 (管理費別; 管理費込みの上限は conditions.py で判定)
    ("search_area", "40"),  # 40m²以上 (選択肢に45がない)
    ("search_station", "15"),  # 駅徒歩15分以内
    ("page_disp", "30"),
]
TOHTO_URL = f"{BASE_URL}/search-result/page-1.html?{urlencode(TOHTO_PARAMS)}"


def _text(fragment: str, sep: str = " ") -> str:
    text = html.unescape(re.sub(r"<[^>]+>", sep, fragment))
    return re.sub(r"\s+", sep, text).strip()


def _man_yen(value: str) -> str:
    """'160,000円' -> '16万円'; '-' or empty -> ''."""
    m = re.search(r"[\d,]+", value)
    if not m:
        return ""
    return f"{int(m.group().replace(',', '')) / 10000:g}万円"


def _access(fragment: str) -> tuple[str, str, str]:
    """Closest walking access; bus accesses ('バス18分 徒歩 3 分') are skipped."""
    options = []
    for item in re.split(r"<br\s*/?>", fragment):
        links = [_text(a) for a in re.findall(r"<a[^>]*>(.*?)</a>", item, re.DOTALL)]
        rest = _text(re.sub(r"<a[^>]*>.*?</a>", "", item, flags=re.DOTALL))
        m = re.fullmatch(r"徒歩 ?(\d+) ?分", rest)
        if len(links) == 2 and m:
            options.append((int(m.group(1)), links[0], re.sub(r"駅$", "", links[1])))
    if not options:
        return "", "", ""
    walk, line, station = min(options)
    return line, station, str(walk)


def parse_tohto(page: str) -> list[dict]:
    pet = "ペット相談" if "search_equip%5B0%5D=32" in page or "search_equip[0]=32" in page else ""

    results = []
    for block in re.split(r'<article class="article-card-item room-card">', page)[1:]:
        title_m = re.search(r'<h3 class="article-card-title"><a href="([^"]+)">(.*?)</a>', block, re.DOTALL)
        if not title_m:
            continue
        sub_m = re.search(r'<h4 class="article-card-title-sub[^"]*">(.*?)</h4>', block, re.DOTALL)
        catch = _text(sub_m.group(1)) if sub_m else ""
        price_m = re.search(r'<p class="price">(.*?)<span class="maint_fee">（管理費 (.*?)）</span>', block, re.DOTALL)
        layout_m = re.search(r'<p class="layout">(.*?)<span class="exc_area">（専有面積 (.*?)）</span>', block, re.DOTALL)
        area_m = re.search(r'<li class="i-area[^"]*">(.*?)</li>', block, re.DOTALL)
        station_m = re.search(r'<li class="i-station[^"]*">(.*?)</li>', block, re.DOTALL)
        build_m = re.search(r'<li class="i-build">(.*?)</li>', block, re.DOTALL)
        floor_m = re.search(r"<span>階数</span>(.*?)</p>", block, re.DOTALL)

        # '2020年1月 / 鉄骨 / 1階' (築年月 / 構造 / 所在階)
        built, structure = ([_text(x) for x in build_m.group(1).split("/")] + ["", ""])[:2] if build_m else ("", "")
        line, station, walk = _access(station_m.group(1)) if station_m else ("", "", "")
        area = re.search(r"[\d.]+", _text(layout_m.group(2))) if layout_m else None
        fee = _text(price_m.group(2)) if price_m else ""

        results.append({
            "property_name": _text(title_m.group(2)).replace("｜", " "),
            "rent": _man_yen(_text(price_m.group(1))) if price_m else "",
            "management_fee": fee if re.search(r"\d", fee) else "",
            "floor_plan": _text(layout_m.group(1)) if layout_m else "",
            "area_sqm": f"{area.group()}m²" if area else "",
            "railway_line": line,
            "nearest_station": station,
            "walk_minutes": walk,
            "address": _text(area_m.group(1), "") if area_m else "",
            "building_year_month": built,
            "floor_info": _text(floor_m.group(1)) if floor_m else "",
            "structure": structure,
            "pet_conditions": " ".join(filter(None, [pet, catch.split("|")[-1].strip() if "ペット" in catch else ""])),
            "detail_url": html.unescape(title_m.group(1)),
        })
    return results


def get_next_page_url_tohto(page: str, current_url: str | None = None) -> str | None:
    """The pager's 「>」 link (page-N.html?...); the last page has none.

    The link has raw ``search_equip[0]=`` brackets, which curl would read as a glob.
    """
    m = re.search(r'<a href="([^"]+)"[^>]*/?><span>&gt;</span></a>', page)
    if not m:
        return None
    return html.unescape(m.group(1)).replace("[", "%5B").replace("]", "%5D")
