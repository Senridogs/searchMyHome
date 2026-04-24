import re
from html.parser import HTMLParser


def _strip_tags(html_fragment: str) -> str:
    result: list[str] = []

    class _TagStripper(HTMLParser):
        def handle_data(self, data: str) -> None:
            result.append(data)

    _TagStripper().feed(html_fragment)
    return "".join(result)


def _clean(text: str) -> str:
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_sengawa(html_str: str) -> list[dict]:
    blocks = re.split(r'<div\s+class="box_result">', html_str)
    properties: list[dict] = []

    for block in blocks[1:]:
        end = block.find('<div class="box_result">')
        if end != -1:
            block = block[:end]

        layout_m = re.search(r'class="typo_layout"[^>]*>(.*?)</p>', block, re.DOTALL)
        area_m = re.search(r'class="area"[^>]*>(.*?)</p>', block, re.DOTALL)
        price_m = re.search(r'class="typo_price"[^>]*>(.*?)</p>', block, re.DOTALL)
        fee_m = re.search(r'class="typo_maintenance_fee"[^>]*>(.*?)</p>', block, re.DOTALL)
        access_m = re.search(r'class="typo_access"[^>]*>(.*?)</p>', block, re.DOTALL)
        address_m = re.search(r'<span>所在地[：:]</span>\s*(.*?)</p>', block, re.DOTALL)
        year_m = re.search(r'<span>築年月[：:]</span>\s*(.*?)</p>', block, re.DOTALL)
        detail_m = re.search(r'<a\s+href="(/es/rent/[^"]+)"', block)
        name_m = re.search(r'class="typo_name"[^>]*>(.*?)</(?:p|div)>', block, re.DOTALL)
        pet_m = re.search(r'class="typo_selling_point"[^>]*>(.*?)</p>', block, re.DOTALL)
        floor_m = re.search(r'<span>階数[：:]</span>\s*(.*?)</p>', block, re.DOTALL)

        floor_plan = _clean(_strip_tags(layout_m.group(1))) if layout_m else ""
        area_sqm = _clean(_strip_tags(area_m.group(1))) if area_m else ""
        rent = _clean(_strip_tags(price_m.group(1))) if price_m else ""
        management_fee = _clean(_strip_tags(fee_m.group(1))).strip("（）()") if fee_m else ""

        access_text = _clean(_strip_tags(access_m.group(1))) if access_m else ""
        access_text = re.sub(r'^交通[：:]\s*', '', access_text)
        railway_line = ""
        nearest_station = ""
        walk_minutes = ""
        am = re.match(r'(.+?線)\s+(.+?駅)\s+徒歩(\d+)分', access_text)
        if not am:
            am = re.match(r'(.+?)\s+(.+?駅)\s+徒歩(\d+)分', access_text)
        if am:
            railway_line = am.group(1)
            nearest_station = am.group(2)
            walk_minutes = am.group(3) + "分"

        address = _clean(_strip_tags(address_m.group(1))) if address_m else ""
        building_year = _clean(_strip_tags(year_m.group(1))) if year_m else ""
        detail_url = ("https://sengawa.es-ws.jp" + detail_m.group(1)) if detail_m else ""
        property_name = _clean(_strip_tags(name_m.group(1))) if name_m else ""
        pet_conditions = _clean(_strip_tags(pet_m.group(1))) if pet_m else ""
        floor_info = _clean(_strip_tags(floor_m.group(1))) if floor_m else ""

        if not property_name and address:
            property_name = address

        properties.append({
            "property_name": property_name,
            "rent": rent,
            "management_fee": management_fee,
            "floor_plan": floor_plan,
            "area_sqm": area_sqm,
            "railway_line": railway_line,
            "nearest_station": nearest_station,
            "walk_minutes": walk_minutes,
            "address": address,
            "building_year_month": building_year,
            "floor_info": floor_info,
            "pet_conditions": pet_conditions,
            "detail_url": detail_url,
        })

    return properties


def get_next_page_url_sengawa(html_str: str) -> str | None:
    pager_m = re.search(r'class="eswsPageLink">(.*?)</li>', html_str, re.DOTALL)
    if not pager_m:
        return None

    pager = pager_m.group(1)
    pages_linked = re.findall(r'/feature1/-/page_count/(\d+)', pager)
    if not pages_linked:
        return None

    all_spans = re.findall(r'<span>(\d+)</span>', pager)
    current_page = 1
    for s in all_spans:
        if s not in pages_linked:
            current_page = int(s)
            break

    next_page = current_page + 1
    if str(next_page) in pages_linked:
        return f"https://sengawa.es-ws.jp/feature1/-/page_count/{next_page}"

    return None
