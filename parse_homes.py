import html
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

BASE_URL = "https://www.homes.co.jp"

# 京王井の頭線 富士見ヶ丘・久我山・三鷹台 and 京王線 千歳烏山・仙川・つつじヶ丘,
# with every マンションノート condition LIFULL HOME'S offers.
HOMES_PARAMS = [
    ("cond[roseneki][87104984]", "87104984"),  # 京王井の頭線 富士見ヶ丘
    ("cond[roseneki][87104985]", "87104985"),  # 京王井の頭線 久我山
    ("cond[roseneki][87104986]", "87104986"),  # 京王井の頭線 三鷹台
    ("cond[roseneki][86304935]", "86304935"),  # 京王線 千歳烏山
    ("cond[roseneki][86304936]", "86304936"),  # 京王線 仙川
    ("cond[roseneki][86304937]", "86304937"),  # 京王線 つつじヶ丘
    ("cond[monthmoneyroomh]", "19"), ("cond[kanrihi]", "1"),  # 賃料 19万円以下, 管理費込み
    # 2LDK / 3LDK / 4LDK以上
    ("cond[madori][25]", "25"), ("cond[madori][35]", "35"), ("cond[madori][45-]", "45-"),
    ("cond[housearea]", "45"),  # 専有面積 45m2以上
    ("cond[walkminutesh]", "10"),  # 駅徒歩 10分以内
    # 築年数: 最長が30年以内のため指定しない
    ("cond[housekouzougroup][rebar]", "rebar"),  # 鉄筋系
    ("cond[housekouzougroup][steelframe]", "steelframe"),  # 鉄骨系
    ("cond[mcf][113201]", "113201"),  # ペット相談可
    ("cond[mcf][220301]", "220301"),  # バス・トイレ別
    ("cond[mcf][290901]", "290901"),  # 室内洗濯機置場
    ("cond[mcf][230301]", "230301"),  # コンロ二口以上
    ("cond[sortby]", "newdate"),  # 新着順
]
HOMES_URL = f"{BASE_URL}/chintai/tokyo/list/?{urlencode(HOMES_PARAMS)}"

TARGET_STATIONS = ("富士見ヶ丘", "久我山", "三鷹台", "千歳烏山", "仙川", "つつじヶ丘")

LIST_START = 'id="prg-mod-bukkenList"'
# Results come in bundles of 20 buildings, each closed by an action bar
LIST_END = "bukkenListAction nocheck bottom last"


def parse_homes(html_str: str) -> list[dict]:
    """Parse LIFULL HOME'S 賃貸 search results, one dict per room.

    HOME'S merges the same room listed by several agencies into one row
    (the 「物件数」 count; 「総物件数」 counts every agency's ad), so one dict is
    produced per row. Only the result list is read: the PR boxes above it
    (``kksframelist``, which repeat a matching room) are skipped. The list
    shows no structure, so ``structure`` stays empty (the URL limits it to
    鉄筋系・鉄骨系).
    """
    start = html_str.find(LIST_START)
    if start == -1:
        return []
    end = html_str.find(LIST_END, start)
    listing = html_str[start:end if end != -1 else len(html_str)]

    pet_conditions = "ペット相談可" if re.search(
        r'name="cond\[mcf\]\[113201\]"[^>]*\bchecked\b', html_str) else ""

    results = []
    for block in re.split(r'<div class="mod-mergeBuilding', listing)[1:]:
        property_name = _clean_text(_match(r'<span class="bukkenName[^"]*">(.*?)</span>', block))
        spec = dict(
            (_clean_text(th), td)
            for th, td in re.findall(r'<tr><th>(.*?)</th><td>(.*?)</td></tr>', block, re.DOTALL)
        )
        address = _clean_text(spec.get("所在地", ""))
        railway_line, nearest_station, walk_minutes = _access(spec.get("交通", ""))
        built, floors = (_clean_text(x) for x in (_clean_text(spec.get("築年数/階数", "")) + " / ").split("/")[:2])
        if re.fullmatch(r"\d+年", built):
            built = "築" + built

        for row in re.split(r'<tr data-href="', block)[1:]:
            detail = html.unescape(row.split('"', 1)[0])
            floor = _clean_text(_match(r'<li class="roomKaisuu">(.*?)</li>', row)).strip("-")  # 一戸建ては "-"
            price = _match(r'<td class="price">(.*?)</td>', row)
            rent_num = _match(r'<span class="num">([\d.]+)</span>\s*万円', price)
            fee = _clean_text(_match(r'</span>\s*/\s*([^<]*)</span>', price)).replace(",", "")
            layout = _match(r'<td class="layout"[^>]*>(.*?)</td>', row)
            plan, area = (_clean_text(x) for x in (layout + "<br>").split("<br>")[:2])

            results.append({
                "property_name": property_name,
                "rent": f"{rent_num}万円" if rent_num else "",
                "management_fee": fee if fee and fee not in ("0円", "なし") else "-",
                "floor_plan": plan,
                "area_sqm": area,
                "railway_line": railway_line,
                "nearest_station": nearest_station,
                "walk_minutes": walk_minutes,
                "address": address,
                "building_year_month": built,
                "floor_info": " / ".join(filter(None, [floor, floors])),
                "structure": "",
                "pet_conditions": pet_conditions,
                "detail_url": detail if detail.startswith("http") else BASE_URL + detail,
            })

    return results


def get_next_page_url_homes(html_str: str, current_url: str | None = None) -> str | None:
    """Return the next result page, keeping the search conditions.

    The pager's 「次へ」 link is just ``?page=N`` (HOME'S keeps the conditions
    in a session cookie, which curl doesn't send), so the page number is set
    on the current search URL instead.
    """
    m = re.search(r'<li\s+class="nextPage"><a href="[^"]*" data-page="(\d+)"', html_str)
    if not m:
        return None
    parts = urlsplit(current_url or HOMES_URL)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "page"]
    query.append(("page", m.group(1)))
    return urlunsplit(parts._replace(query=urlencode(query)))


def _access(cell: str) -> tuple[str, str, str]:
    """Pick the shortest walk to one of the searched stations.

    Lines look like '京王線 仙川駅 徒歩9分', '京王線　仙川 徒歩9分' or
    '「京王電鉄京王線 柴崎」 徒歩9分'; bus accesses ('… バス9分 …下車 徒歩3分')
    are skipped. Without a searched station the first walking line is used.
    """
    parsed = []
    for text in re.findall(r'<span class="prg-stationText">(.*?)</span>', cell, re.DOTALL):
        text = re.sub(r"[「」]", "", _clean_text(text))
        m = re.match(r"(?:(.+)\s)?(\S+?)駅?\s*徒歩(\d+)分$", text)
        if m and "バス" not in text:
            parsed.append(((m.group(1) or "").strip(), m.group(2), m.group(3)))
    targets = [a for a in parsed if a[1] in TARGET_STATIONS]
    if targets:
        return min(targets, key=lambda a: int(a[2]))
    return parsed[0] if parsed else ("", "", "")


def _match(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1) if m else ""


def _clean_text(html_fragment: str) -> str:
    """Strip tags, decode entities, and normalise whitespace."""
    text = html.unescape(re.sub(r'<[^>]+>', '', html_fragment))
    text = text.replace('　', ' ')
    return re.sub(r'\s+', ' ', text).strip()


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/rental_html/homes_p1.html"
    with open(path, encoding="utf-8") as f:
        page = f.read()

    props = parse_homes(page)
    print(f"Found {len(props)} properties\n")
    for p in props:
        print(json.dumps(p, ensure_ascii=False, indent=2))
        print()

    print(f"Next page URL: {get_next_page_url_homes(page, HOMES_URL)}")
