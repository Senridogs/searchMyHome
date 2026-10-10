import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

BASE_URL = "https://www.eheya.net"

# 久我山 / 富士見ヶ丘 / 三鷹台 (京王井の頭線) and 仙川 / 千歳烏山 / つつじヶ丘 (京王線),
# with every マンションノート condition いい部屋ネット offers.
EHEYA_PARAMS = [
    ("val_code", "22644"), ("val_code", "22956"), ("val_code", "22987"),
    ("val_code", "22776"), ("val_code", "22817"), ("val_code", "22823"),
    ("price_to", "220000"), ("price_and_cost", "1"),  # 賃料 22万円以下, 管理費等込み
    # 2LDK / 3LDK / 4K以上 (the site has no separate 4LDK)
    ("house_plan", "2LDK"), ("house_plan", "3LDK"), ("house_plan", "4K_more"),
    ("use_part_area_from", "40"),  # 専有面積 40m2以上
    ("walk_from_station_x", "15"),  # 駅徒歩 15分以内 (バス便は含めない)
    # 築年数: 最長が30年以内のため指定しない
    ("structure_code", "1"), ("structure_code", "2"),  # 鉄筋系 / 鉄骨系
    ("pet_code", "1"),  # ペット相談可
    ("cooking_stove_code", "2"),  # 2口以上コンロ
    ("toilet_code", "1"),  # バス・トイレ別
    ("washing_machine_place_code", "1"),  # 室内洗濯機置場
    # 並び順: 既定の「更新日順」(UPDATE_DESC) が新着順にあたる
]
EHEYA_URL = f"{BASE_URL}/tokyo/station/search/?{urlencode(EHEYA_PARAMS)}"


def parse_eheya(html_str: str) -> list[dict]:
    """Parse いい部屋ネット search results (建物ごとに表示), one dict per room.

    The page is rendered by Next.js, so the rooms are read from __NEXT_DATA__
    (buildingSearchResult). The separate ``highlightProperty`` slot and other
    suggestions are skipped. The list carries no structure, so ``structure``
    stays empty (the search URL already limits it to 鉄筋系・鉄骨系).
    """
    page_props = _page_props(html_str)
    if not page_props:
        return []
    buildings = (page_props.get("buildingSearchResult") or {}).get("buildings") or []

    # The search conditions are echoed back; ペット相談可 means every room allows it
    detail = (page_props.get("serializedCondition") or {}).get("detail") or {}
    searched_pet = bool(detail.get("isPetNegotiable"))

    results = []
    for b in buildings:
        railway_line, nearest_station, walk_minutes = _access(b.get("mainTransportationText"))
        stories = f"{b['story']}階建" if b.get("story") else ""
        if stories and b.get("underStory"):
            stories += f" 地下{b['underStory']}階"

        for p in b.get("properties") or []:
            floor = re.sub(r"^0+(?=\d)", "", p.get("floor") or "")
            area = p.get("roomArea")
            full_id = p.get("propertyFullId") or ""
            results.append({
                "property_name": p.get("buildingName") or b.get("name") or "",
                "rent": _man_yen(p.get("price")),
                "management_fee": _fee(p.get("manageCost")),
                "floor_plan": p.get("housePlan") or "",
                "area_sqm": f"{area:g}m²" if area else "",
                "railway_line": railway_line,
                "nearest_station": nearest_station,
                "walk_minutes": walk_minutes,
                "address": b.get("address") or "",
                "building_year_month": b.get("age") or "",  # "築35年" / "新築"
                "floor_info": " / ".join(filter(None, [floor, stories])),
                "structure": "",
                "pet_conditions": "ペット相談可" if searched_pet or p.get("isPet") else "",
                "detail_url": f"{BASE_URL}/detail/{full_id}/" if full_id else "",
            })

    return results


def get_next_page_url_eheya(html_str: str, current_url: str | None = None) -> str | None:
    """Return the next ``page=N`` URL while buildings remain (20 per page)."""
    page_props = _page_props(html_str)
    info = ((page_props or {}).get("buildingSearchResult") or {}).get("pageInfo") or {}
    offset, limit, total = info.get("offset"), info.get("limit"), info.get("totalCount")
    if not limit or offset is None or total is None or offset + limit >= total:
        return None
    next_page = offset // limit + 2

    parts = urlsplit(current_url or EHEYA_URL)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "page"]
    query.append(("page", str(next_page)))
    return urlunsplit(parts._replace(query=urlencode(query)))


def _page_props(html_str: str) -> dict | None:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html_str, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))["props"]["pageProps"]
    except (ValueError, KeyError, TypeError):
        return None


def _access(text) -> tuple[str, str, str]:
    """'京王線 仙川駅 徒歩8分' -> ('京王線', '仙川', '8').

    For bus access ('京王線 仙川駅 バス7分 中原小学校 徒歩2分') the walk is to
    the bus stop, not the station, so walk_minutes is left empty.
    """
    m = re.match(r"(.+?)\s+(\S+?)駅\s*(.*)$", (text or "").replace("　", " ").strip())
    if not m:
        return "", "", ""
    rest = m.group(3)
    walk = re.match(r"徒歩(\d+)分", rest)
    return m.group(1), m.group(2), walk.group(1) if walk else ""


def _man_yen(price) -> str:
    """{'number': 172300, 'unit': 'YEN'} -> '17.23万円'."""
    n = (price or {}).get("number")
    if not n or (price or {}).get("unit") != "YEN":
        return ""
    return f"{n / 10000:g}万円"


def _fee(cost) -> str:
    n = (cost or {}).get("number")
    if not n or (cost or {}).get("unit") != "YEN":
        return "-"
    return f"{n}円"


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/rental_html/eheya_p1.html"
    with open(path, encoding="utf-8") as f:
        page = f.read()

    props = parse_eheya(page)
    print(f"Found {len(props)} properties\n")
    for p in props:
        print(json.dumps(p, ensure_ascii=False, indent=2))
        print()

    print(f"Next page URL: {get_next_page_url_eheya(page, EHEYA_URL)}")
