import html
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

BASE_URL = "https://www.pitat.com"

# 富士見ヶ丘・久我山・三鷹台 (京王井の頭線 304) and 千歳烏山・仙川・つつじヶ丘 (京王線 301)
PITAT_STATIONS = {
    "13_304_2956": "富士見ヶ丘", "13_304_2001": "久我山", "13_304_3073": "三鷹台",
    "13_301_2528": "千歳烏山", "13_301_2418": "仙川", "13_301_2563": "つつじヶ丘",
}

# Every マンションノート condition ピタットハウス offers. The site has no 構造
# filter, and its 築年数 options stop at 40年以内, so neither is set.
PITAT_PARAMS = [
    ("articleClass", "0"),  # 居住用
    *[(f"railRoadList[{code}]", code) for code in PITAT_STATIONS],
    ("cnryTo", "190000"), ("kkFlg", "true"),  # 賃料 19万円以下, 共益費・管理費含む
    # 2LDK / 3LDK / 4LDK以上 (S付き・LK も含む)
    ("floorPlan[6]", "2LDK#2SLDK#2LK#2SLK"),
    ("floorPlan[9]", "3LDK#3SLDK#3LK#3SLK"),
    ("floorPlan[12]", "4LDK#4SLDK#4LK#4SLK#5"),
    ("symnDc.from", "45"),  # 専有面積 45㎡以上
    ("timeRequired", "10"),  # 駅徒歩 10分以内
    ("kodawari[39]", "室内洗濯機置場"),
    ("kodawari[48]", "コンロ2口以上"),
    ("kodawari[50]", "バス・トイレ別"),
    ("kodawari[56]", "ペット相談可"),
    ("sortList[0]", "KOUKAI_DESC"),  # 公開が新しい順
    ("rowCount", "50"),  # 1ページ50棟
]
PITAT_URL = f"{BASE_URL}/rent/railroad/pref/ensen/eki/search?{urlencode(PITAT_PARAMS)}"

_SEARCHED_STATIONS = set(PITAT_STATIONS.values())


def parse_pitat(html_str: str) -> list[dict]:
    """Parse ピタットハウス search results (建物ごとに表示), one dict per room.

    Only the result list (<form id="result-main">) is read, so the photo modal
    and other blocks are skipped. The list shows no structure, so
    ``structure`` stays empty.

    Note the page's 「該当物件 N 件」 counts a room once per nearby searched
    station, so it is larger than the number of rooms listed.
    """
    start = html_str.find('<form id="result-main"')
    end = html_str.find("</form>", start)
    if start == -1 or end == -1:
        return []
    listing = html_str[start:end]

    # The search conditions are echoed back; ペット相談可 means every room allows it
    pet_conditions = (
        "ペット相談可"
        if re.search(r'name="kodawari\[56\]" value="ペット相談可"[^>]*checked', html_str)
        else ""
    )

    results = []
    for block in re.split(r'<section class="result-list__item"', listing)[1:]:
        property_name = _clean_text(_match(r'class="result-list__ttl">(.*?)</h2>', block))
        info = {
            alt: _clean_text(text)
            for alt, text in re.findall(
                r'<li class="result-list__info-item">.*?alt="([^"]*)".*?</span>(.*?)</li>',
                block, re.DOTALL,
            )
        }
        railway_line, nearest_station, walk_minutes = _access(info.get("交通", ""))
        built = re.search(r"\d{4}年\d{1,2}月|新築", info.get("インフォメーション", ""))

        for row in re.findall(r'<a class="prpty-items__link-area"(.*?)</a>', block, re.DOTALL):
            detail = _match(r'href="(/rentDetail/[^"]+)"', row)
            layout = _clean_text(_match(r'class="prpty-items__layout-info">(.*?)</div>', row))
            plan, _, area = layout.partition("/")
            fee = _clean_text(_match(r'<div class="sub">(.*?)</div>', row))
            fee = re.sub(r"[^\d]", "", fee)

            results.append({
                "property_name": property_name,
                "rent": _clean_text(_match(r'<div class="main">(.*?)</div>', row)).replace(" ", ""),
                "management_fee": f"{fee}円" if fee and int(fee) else "-",
                "floor_plan": plan.strip(),
                "area_sqm": area.strip().replace("㎡", "m²"),
                "railway_line": railway_line,
                "nearest_station": nearest_station,
                "walk_minutes": walk_minutes,
                "address": info.get("住所", ""),
                "building_year_month": built.group() if built else "",
                # 'NEW' badge sits in its own div; the floor is in div.txt
                "floor_info": _clean_text(_match(r'<div class="txt">(.*?)</div>', row)),
                "structure": "",
                "pet_conditions": pet_conditions,
                "detail_url": BASE_URL + html.unescape(detail) if detail else "",
            })

    return results


def get_next_page_url_pitat(html_str: str, current_url: str | None = None) -> str | None:
    """Return the current URL with ``page`` advanced while the pager has a next page.

    The pager's own hrefs drop the search conditions (JS re-submits the form),
    so the next URL is built from the current one instead.
    """
    m = re.search(r'<ul class="pagination">.*?<span class="active">(\d+)</span>', html_str, re.DOTALL)
    if not m:
        return None
    next_page = int(m.group(1)) + 1
    if f"changePage('{next_page}')" not in html_str:
        return None

    parts = urlsplit(current_url or PITAT_URL)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "page"]
    query.append(("page", str(next_page)))
    return urlunsplit(parts._replace(query=urlencode(query)))


def _access(text: str) -> tuple[str, str, str]:
    """Pick the walking access to a searched station.

    '京王線 「柴崎駅」 徒歩5分 / 京王線 「つつじヶ丘駅」 徒歩10分' lists the nearest
    station first, which may not be one we searched, so the closest searched
    station is preferred. Bus accesses ('「荻窪駅」 バス21分 「立教女学院」 徒歩3分')
    walk to the bus stop, so they get no walk_minutes.
    """
    parsed = []
    for part in text.split(" / "):
        m = re.match(r"(.*?)\s*「(.+?)駅」\s*(.*)$", part.strip())
        if m:
            walk = re.match(r"徒歩(\d+)分", m.group(3))
            parsed.append((m.group(1).strip(), m.group(2), walk.group(1) if walk else ""))
    if not parsed:
        return "", "", ""
    walking = [a for a in parsed if a[2]]
    searched = [a for a in walking if a[1] in _SEARCHED_STATIONS]
    if searched:
        return min(searched, key=lambda a: int(a[2]))
    return walking[0] if walking else parsed[0]


def _match(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1) if m else ""


def _clean_text(html_fragment: str) -> str:
    """Strip tags, decode entities, and normalise whitespace."""
    text = html.unescape(re.sub(r'<[^>]+>', ' ', html_fragment))
    text = text.replace('　', ' ')
    return re.sub(r'\s+', ' ', text).strip()


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/rental_html/pitat_p1.html"
    with open(path, encoding="utf-8") as f:
        page = f.read()

    props = parse_pitat(page)
    print(f"Found {len(props)} properties\n")
    for p in props:
        print(json.dumps(p, ensure_ascii=False, indent=2))
        print()

    print(f"Next page URL: {get_next_page_url_pitat(page, PITAT_URL)}")
