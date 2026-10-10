import json
import re
from urllib.parse import urlencode, urlsplit, urlunsplit

BASE_URL = "https://www.athome.co.jp"

# 京王井の頭線 富士見ヶ丘・久我山・三鷹台 and 京王線 千歳烏山・仙川・つつじヶ丘,
# with every マンションノート condition at home offers. These are the query
# parameters at home's own search form redirects to.
ATHOME_PARAMS = [
    ("pref", "13"),
    ("station", "fujimigaoka,kugayama,mitakadai,chitosekarasuyama,sengawa,tsutsujigaoka"),
    ("basic", ",".join([
        "kc133", "kc201",  # 賃料 19万円以下, 管理費等含む
        "km010", "km015", "km021",  # 2LDK / 3LDK / 4LDK以上
        "kt007",  # 専有面積 45m2以上
        "ke004",  # 駅徒歩 10分以内
        "kn001",  # 築年数: 最長が40年以内のため指定なし
        "kh001", "kh002",  # 鉄筋系 / 鉄骨系
    ])),
    # バス・トイレ別 / 2口以上コンロ / 室内洗濯機置き場 / ペット相談
    ("kod", "B01,K18,E23,C08"),
    ("sort", "33"),  # 新着順
    ("limit", "30"),  # 1ページ30棟
    ("q", "1"),
]
ATHOME_URL = f"{BASE_URL}/chintai/tokyo/list/?{urlencode(ATHOME_PARAMS, safe=',')}"

TARGET_STATIONS = ("富士見ヶ丘", "久我山", "三鷹台", "千歳烏山", "仙川", "つつじヶ丘")

_STATE_RE = re.compile(r'<script id="(?:serverApp-state|ng-state)"[^>]*>(.*?)</script>', re.DOTALL)


def parse_athome(html_str: str) -> list[dict]:
    """Parse at home 賃貸 search results, one dict per room.

    The list is server-rendered from the JSON embedded in
    ``<script id="serverApp-state">``; only its search result
    (``propertyListData``) is read, so the 「不動産会社のおすすめ」 and other
    recommendation blocks stored next to it are skipped. at home merges the
    same room listed by several agencies into one row (the 「N件」 count adds
    them all up), so one dict is produced per row. The list shows no
    structure, so ``structure`` stays empty (the URL limits it to 鉄筋系・鉄骨系).
    """
    data = _first_view(html_str)
    if not data:
        return []
    property_list = (data.get("propertyListData") or {}).get("propertyList") or []

    selected = _selected_conditions(data)
    pet_conditions = "ペット相談可" if "C08" in selected else ""

    results = []
    for building in property_list:
        name = re.sub(r"\s+\S*階建$", "", building.get("bukkenNm") or "").strip()
        address = building.get("address") or ""
        if address and not re.match(r"^(東京都|北海道|.{2,3}[府県])", address):
            address = "東京都" + address  # the search is limited to 東京都
        railway_line, nearest_station, walk_minutes = _access(building.get("traffic") or [])
        built = building.get("chikunengetsu") or ""  # '1991年9月(築35年2ヶ月)'
        built = re.match(r"[^(（]*", built).group().strip() or built
        floors = building.get("kaidate") or ""

        for room in building.get("roomList") or []:
            rent = (room.get("chinryo") or "").replace(",", "")
            if re.fullmatch(r"\d+(?:\.\d+)?", rent):
                rent += "万円"
            fee = (room.get("managementFee") or "").replace(",", "")
            floor = (room.get("kai") or "").strip("－-")
            bukken_no = room.get("bukkenNo") or ""

            results.append({
                "property_name": name,
                "rent": rent,
                "management_fee": fee if re.search(r"[1-9]", fee) else "-",
                "floor_plan": room.get("madori") or "",
                "area_sqm": room.get("area") or "",
                "railway_line": railway_line,
                "nearest_station": nearest_station,
                "walk_minutes": walk_minutes,
                "address": address,
                "building_year_month": built,
                "floor_info": " / ".join(filter(None, [floor, floors])),
                "structure": "",
                "pet_conditions": pet_conditions,
                "detail_url": f"{BASE_URL}/chintai/{bukken_no}/" if bukken_no else "",
            })

    return results


def get_next_page_url_athome(html_str: str, current_url: str | None = None) -> str | None:
    """Return the next result page (``/list/pageN/``), keeping the conditions.

    The server-rendered pager links drop the query string (the browser app
    adds it back), so the page path is set on the current search URL using
    the page number and building count from the embedded JSON.
    """
    data = _first_view(html_str)
    if not data:
        return None
    config = data.get("config") or {}
    try:
        page = int(config.get("pageNo") or 1)
        per_page = int(config.get("number") or 30)
        buildings = int((data.get("propertyListData") or {}).get("tatemonoCount") or 0)
    except (TypeError, ValueError):
        return None
    if page * per_page >= buildings:
        return None

    parts = urlsplit(current_url or ATHOME_URL)
    path = re.sub(r"/list/(?:page\d+/)?$", f"/list/page{page + 1}/", parts.path)
    if path == parts.path:
        return None
    return urlunsplit(parts._replace(path=path))


def _first_view(html_str: str) -> dict | None:
    """The search result JSON the page was rendered from."""
    m = _STATE_RE.search(html_str)
    if not m:
        return None
    try:
        state = json.loads(m.group(1))
    except ValueError:
        return None
    item = state.get("first-view-ITEMS")
    if isinstance(item, dict) and isinstance(item.get("data"), dict):
        return item["data"]
    for key, value in state.items():  # the raw BFF response it was copied from
        if "/property-list/first-view" in key and isinstance(value, dict):
            try:
                return json.loads(value.get("body") or "")["data"]
            except (ValueError, KeyError, TypeError):
                return None
    return None


def _selected_conditions(data: dict) -> set[str]:
    selected = set()
    for section in ("basicConditions", "insistenceConditions"):
        for group in ((data.get("conditions") or {}).get(section) or {}).get("group") or []:
            for cond in group.get("conditions") or []:
                for option in cond.get("condition") or []:
                    if option.get("selected"):
                        selected.add(option.get("value"))
    return selected


def _access(traffic: list[dict]) -> tuple[str, str, str]:
    """Pick the shortest walk to one of the searched stations.

    at home lists the access that matched the search; bus accesses have no
    ``tohoJikan``. Without a searched station the first walking line is used.
    """
    parsed = [
        (t.get("lineName") or "", t.get("stationName") or "", str(t.get("tohoJikan")))
        for t in traffic if str(t.get("tohoJikan") or "").isdigit()
    ]
    targets = [a for a in parsed if a[1] in TARGET_STATIONS]
    if targets:
        return min(targets, key=lambda a: int(a[2]))
    return parsed[0] if parsed else ("", "", "")


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/rental_html/athome_p1.html"
    with open(path, encoding="utf-8") as f:
        page = f.read()

    props = parse_athome(page)
    print(f"Found {len(props)} properties\n")
    for p in props:
        print(json.dumps(p, ensure_ascii=False, indent=2))
        print()

    print(f"Next page URL: {get_next_page_url_athome(page, ATHOME_URL)}")
