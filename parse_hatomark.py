"""Parser for ハトマークサイト (hatomarksite.com), the 全宅連 members' listing site.

Most small local agencies around 千歳烏山・仙川・久我山 are 全宅連 members
(about 57 of them list an office near the six stations) and many have no
searchable site of their own, so one station search here covers them all.

List pages are server-rendered, one ``div.search-result-box`` per room. The
list has no 構造 field (only マンション/アパート/一戸建て), so ``structure``
stays empty. robots.txt does not restrict /search/.
"""

import html
import re
import unicodedata
from urllib.parse import urlencode

BASE_URL = "https://www.hatomarksite.com"

# 京王線 千歳烏山・仙川・つつじヶ丘 and 井の頭線 富士見ヶ丘・久我山・三鷹台
HATOMARK_STATIONS = {
    "千歳烏山": "Y8WBMM8BS", "仙川": "Y8WBMMWBY", "つつじヶ丘": "Y8WBMMPB3",
    "富士見ヶ丘": "Y8WBPMWBY", "久我山": "Y8WBPMPB3", "三鷹台": "Y8WBPMDBN",
}
HATOMARK_PARAMS = [
    *[("wst[]", code) for code in HATOMARK_STATIONS.values()],
    ("cpet[]", "CPET03"),  # ペット相談
    # 2LDK / 3LDK / 4LDK / 5LDK / 6LDK以上 (S付きも含む)
    *[("floor_plan[]", c) for c in ("2XXSLDK", "3XXSLDK", "4XXSLDK", "5XXSLDK", "6ZZZZZZ")],
    ("price_r_to", "220000"), ("mng_in_price", "true"),  # 管理費込み 22万円以下
    ("eki_walk", "15"),  # 駅徒歩15分以内
    ("building_area_all_from", "40"),  # 40m²以上
    ("sort1", "ASRT11"),  # 更新日 新しい順
    ("limit", "50"),
]
HATOMARK_URL = f"{BASE_URL}/search/zentaku/rent/home/train/13/list?{urlencode(HATOMARK_PARAMS)}"


def _text(fragment: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", text).strip()


def _searched_stations(page: str) -> set[str]:
    """Stations named in the title: '…【京王電鉄京王線】千歳烏山駅・仙川駅…の貸マンション…'."""
    m = re.search(r"<title>(.*?)</title>", page, re.DOTALL)
    head = _text(m.group(1)).split("の貸")[0] if m else ""
    return {re.sub(r"^.*】", "", s) for s in re.findall(r"([^・\s]+?)駅", head)}


def _access(traffic: str, searched: set[str]) -> tuple[str, str, str]:
    """Walking access to a searched station if any, else the closest walk.

    Lines run into station names ('京王電鉄京王線つつじヶ丘駅 徒歩10分'), and
    bus accesses ('…駅 バス乗車15分 天神前停 徒歩3分') are skipped.
    """
    options = []
    for item in re.findall(r"<div>(.*?)</div>", traffic, re.DOTALL):
        m = re.match(r"(.+?)駅 徒歩(\d+)分", _text(item))
        if not m:
            continue
        line_m = re.match(r"(.*(?:線|ライナー|モノレール|エクスプレス|ゆりかもめ))(.+)$", m.group(1))
        line, station = line_m.groups() if line_m else ("", m.group(1))
        options.append((station not in searched, int(m.group(2)), line, station))
    if not options:
        return "", "", ""
    _, walk, line, station = min(options)
    return line, station, str(walk)


def _value(block: str, label: str) -> str:
    m = re.search(
        r'room-detail-title[^>]*>' + label + r'</span>\s*<p class="room-detail-value">(.*?)</p>',
        block, re.DOTALL,
    )
    return _text(m.group(1)) if m else ""


def parse_hatomark(page: str) -> list[dict]:
    searched = _searched_stations(page)
    title_m = re.search(r"<title>.*?ペット\((.*?)\)", page, re.DOTALL)
    pet = title_m.group(1) if title_m else ""

    results = []
    for block in re.split(r'<div class="search-result-box detail-link"', page)[1:]:
        id_m = re.search(r'data-id="(\d+)"', block)
        if not id_m:
            continue
        kind_m = re.search(r'<p class="room-tag[^"]*">(.*?)</p>', block, re.DOTALL)
        name_m = re.search(r'<p class="text-18 fw-bold">(.*?)</p>', block, re.DOTALL)
        address_m = re.search(r'<div class="mb-1 address">(.*?)</div>', block, re.DOTALL)
        address = re.sub(r"MAP$", "", _text(address_m.group(1))).strip() if address_m else ""
        traffic_m = re.search(r'<div class="mb-1 traffic">(.*?)</div>\s*<div></div>', block, re.DOTALL)
        line, station, walk = _access(traffic_m.group(1) if traffic_m else "", searched)
        agency_m = re.search(r'<div class="text-end ms-auto text-14[^"]*">(.*?)</div>', block, re.DOTALL)
        copy_m = re.search(r'<p class="text-18 text-red fw-bold text-truncate">(.*?)</p>', block, re.DOTALL)
        copy = _text(copy_m.group(1)) if copy_m else ""

        area = unicodedata.normalize("NFKC", _value(block, "専有面積"))
        area_m = re.match(r"[\d.]+", area)
        # '1995[H7]年01月' -> '1995年1月'
        built = re.sub(r"\[.*?\]", "", _value(block, "築年月"))
        built = re.sub(r"年0?(\d+)月", r"年\1月", built)
        # '地上3階 1階部分' -> '1階 / 地上3階'
        floors = _value(block, "階建・階")
        floors_m = re.match(r"(\S+)\s+(\S+?)部分$", floors)
        kind = _text(kind_m.group(1)) if kind_m else ""
        name = _text(name_m.group(1)) if name_m else ""

        results.append({
            "property_name": name or f"{kind}（{address}）",
            "rent": _value(block, "賃料"),
            "management_fee": _value(block, "管理費等"),
            "floor_plan": _value(block, "間取り"),
            "area_sqm": f"{area_m.group()}m²" if area_m else "",
            "railway_line": line,
            "nearest_station": station,
            "walk_minutes": walk,
            "address": address,
            "building_year_month": built,
            "floor_info": f"{floors_m.group(2)} / {floors_m.group(1)}" if floors_m else floors,
            "structure": "",
            "pet_conditions": " ".join(filter(None, [pet, copy if "ペット" in copy else ""])),
            "agency": _text(agency_m.group(1)) if agency_m else "",
            "detail_url": f"{BASE_URL}/search/zentaku/bukken/{id_m.group(1)}",
        })
    return results


def get_next_page_url_hatomark(page: str, current_url: str | None = None) -> str | None:
    """The pager's 「»」 (aria-label="Next") link; the last page has none.

    The link has raw ``wst[]=`` brackets, which curl would read as a glob.
    """
    m = re.search(r'<a class="page-link" href="([^"]+)" aria-label="Next">', page)
    if not m:
        return None
    return html.unescape(m.group(1)).replace("[", "%5B").replace("]", "%5D")
