import html
import json
import re
from urllib.parse import urlencode

BASE_URL = "https://suumo.jp"

# 京王井の頭線 (rn=0265) 富士見ヶ丘・久我山・三鷹台 and 京王線 (rn=0280)
# 千歳烏山・仙川・つつじヶ丘, with every マンションノート condition SUUMO offers.
# Kept alongside the by-municipality searches below because it also catches
# rooms near these stations in neighbouring municipalities (e.g. 武蔵野市).
SUUMO_PARAMS = [
    ("ar", "030"), ("bs", "040"), ("ra", "013"),  # 関東 / 賃貸 / 東京都
    ("rn", "0265"), ("rn", "0280"),
    ("ek", "026534030"), ("ek", "026512460"), ("ek", "026536890"),
    ("ek", "028024130"), ("ek", "028021360"), ("ek", "028024850"),
    ("cb", "0.0"), ("ct", "22.0"), ("co", "1"),  # 賃料 22万円以下, 管理費・共益費込み
    ("et", "15"),  # 駅徒歩 15分以内
    # 2LDK / 3LDK / 4LDK / 5K以上 (S付きの 2SLDK 等も含まれる)
    ("md", "07"), ("md", "10"), ("md", "13"), ("md", "14"),
    ("cn", "9999999"),  # 築年数: 最長が30年以内のため指定しない
    ("mb", "40"), ("mt", "9999999"),  # 専有面積 40m2以上
    ("kz", "1"), ("kz", "2"),  # 鉄筋系 / 鉄骨系
    # ペット相談可 / バス・トイレ別 / 室内洗濯機置場 / コンロ2口以上
    ("tc", "0401102"), ("tc", "0400301"), ("tc", "0400501"), ("tc", "0400203"),
    ("po1", "09"),  # 新着順
    ("pc", "50"),  # 1ページ50建物
]
SUUMO_URL = f"{BASE_URL}/jj/chintai/ichiran/FR301FC001/?{urlencode(SUUMO_PARAMS)}"

# Broad search over the マンションノート areas (by municipality), same conditions
_CONDITION_PARAMS = [(k, v) for k, v in SUUMO_PARAMS if k not in ("ar", "bs", "ra", "rn", "ek")]
_AREA_CODES = {
    "SUUMO(東京)": ("13", [13101, 13102, 13103, 13104, 13105, 13106, 13107, 13109, 13110, 13111,
                         13112, 13113, 13114, 13115, 13116, 13117, 13118, 13119, 13120,
                         13204, 13208, 13219]),
    "SUUMO(神奈川)": ("14", [14109, 14117, 14133, 14134, 14136, 14137]),
    "SUUMO(埼玉)": ("11", [11227, 11228, 11229, 11230]),
}
SUUMO_AREA_URLS = {
    name: f"{BASE_URL}/jj/chintai/ichiran/FR301FC001/?"
    + urlencode([("ar", "030"), ("bs", "040"), ("ta", ta)] + [("sc", c) for c in codes] + _CONDITION_PARAMS)
    for name, (ta, codes) in _AREA_CODES.items()
}

LIST_START = "<!-- FrBukkenCassette03 START -->"
LIST_END = "<!-- FrBukkenCassette03 END -->"


def parse_suumo(html_str: str) -> list[dict]:
    """Parse SUUMO 賃貸 search results (建物ごとに表示), one dict per room.

    Only the result list between the FrBukkenCassette03 markers is read, so
    the 「希望の条件に近い物件」 carousel and other suggestions are skipped.
    The list shows no per-building structure, so ``structure`` stays empty
    (the search URL already limits it to 鉄筋系・鉄骨系).
    """
    start = html_str.find(LIST_START)
    end = html_str.find(LIST_END, start)
    if start == -1 or end == -1:
        return []
    listing = html_str[start:end]

    # The search conditions are echoed back; ペット相談可 means every room allows it
    cond_m = re.search(r'name="searchdisp" value="([^"]*)"', html_str)
    pet_conditions = "ペット相談可" if cond_m and "ペット相談可" in cond_m.group(1) else ""

    results = []
    for block in re.split(r'<div class="cassetteitem">', listing)[1:]:
        property_name = _clean_text(_match(r'class="cassetteitem_content-title">(.*?)</div>', block))
        address = _clean_text(_match(r'class="cassetteitem_detail-col1">(.*?)</li>', block))
        railway_line, nearest_station, walk_minutes = _access(
            _match(r'class="cassetteitem_detail-col2">(.*?)</li>', block)
        )

        col3 = re.findall(r'<div>(.*?)</div>', _match(r'class="cassetteitem_detail-col3">(.*?)</li>', block))
        col3 = [_clean_text(c) for c in col3]
        built = next((c for c in col3 if re.search(r"築\d+年|新築", c)), "")
        floors = next((c for c in col3 if c.endswith("階建")), "")

        for row in re.split(r'<tr class="js-cassette_link"', block)[1:]:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            floor = _clean_text(cells[2]).strip("-") if len(cells) > 2 else ""  # 一戸建ては "-"
            detail = html.unescape(_match(r'<a href="(/chintai/[^"]+)"[^>]*js-cassette_link_href', row))
            area = _clean_text(_match(r'class="cassetteitem_menseki">(.*?)</span>', row))

            results.append({
                "property_name": property_name,
                "rent": _clean_text(_match(r'cassetteitem_price--rent">(.*?)</span>\s*</span>', row)),
                "management_fee": _clean_text(_match(r'cassetteitem_price--administration">(.*?)</span>', row)),
                "floor_plan": _clean_text(_match(r'class="cassetteitem_madori">(.*?)</span>', row)),
                "area_sqm": re.sub(r"m2$", "m²", area),
                "railway_line": railway_line,
                "nearest_station": nearest_station,
                "walk_minutes": walk_minutes,
                "address": address,
                "building_year_month": built,
                "floor_info": " / ".join(filter(None, [floor, floors])),
                "structure": "",
                "pet_conditions": pet_conditions,
                "detail_url": BASE_URL + detail if detail else "",
            })

    return results


def get_next_page_url_suumo(html_str: str, current_url: str | None = None) -> str | None:
    """Follow the pager's 「次へ」 link (``&page=N``); the last page has none."""
    m = re.search(r'<p class="pagination-parts"><a href="([^"]+)">次へ</a>', html_str)
    if not m:
        return None
    href = html.unescape(m.group(1))
    return BASE_URL + href if href.startswith("/") else href


def _access(col2: str) -> tuple[str, str, str]:
    """Pick the walking access to a searched station.

    SUUMO bolds the accesses that matched the searched stations, so the first
    bold walking line is preferred over e.g. a closer station on another line.
    Bus accesses ("バス15分 (バス停)… 歩4分") are skipped.
    """
    lines = re.findall(r'<div class="cassetteitem_detail-text"([^>]*)>(.*?)</div>', col2, re.DOTALL)
    parsed = []
    for attrs, text in lines:
        m = re.match(r'(?:(.+)/)?(.+?)駅\s*歩(\d+)分$', _clean_text(text))
        if m:
            parsed.append(("bold" in attrs, ((m.group(1) or "").strip(), m.group(2), m.group(3))))
    for bold, access in parsed:
        if bold:
            return access
    return parsed[0][1] if parsed else ("", "", "")


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

    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/rental_html/suumo_p1.html"
    with open(path, encoding="utf-8") as f:
        page = f.read()

    props = parse_suumo(page)
    print(f"Found {len(props)} properties\n")
    for p in props:
        print(json.dumps(p, ensure_ascii=False, indent=2))
        print()

    print(f"Next page URL: {get_next_page_url_suumo(page)}")
