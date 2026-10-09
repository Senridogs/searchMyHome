import html
import json
import re

# The site loads its ペット可 feature list (feature 2679) from this REST endpoint
SENGAWA_URL_TEMPLATE = (
    "https://sengawa.re-ws.jp/wp-json/wp/v2/get_search_result_for_feature"
    "?search_url=https%3A%2F%2Fsengawa.re-ws.jp%2Ffeature%2F2679%2F"
    "&rent_or_sale=rent&area_or_line=area&item_per_page=30&sort=new_arrival"
    "&sub%5B%5D=is_pet_ok&page_num={page}"
)


def sengawa_url(page: int) -> str:
    return SENGAWA_URL_TEMPLATE.format(page=page)


def _text(fragment: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", text).strip()


def _results_html(raw: str) -> str:
    """The endpoint returns JSON {"html": ...}; accept plain HTML too."""
    if raw.lstrip().startswith("{"):
        try:
            return json.loads(raw).get("html", "")
        except ValueError:
            return ""
    return raw


def _td(block: str, cls: str) -> str:
    m = re.search(rf'<td class="{cls}[^"]*">(.*?)</td>', block, re.DOTALL)
    return _text(m.group(1)) if m else ""


def parse_sengawa(raw: str) -> list[dict]:
    page = _results_html(raw)
    properties: list[dict] = []

    for block in re.split(r'<article class="data', page)[1:]:
        address = re.sub(r"\s+", "", _td(block, "feature-detail-data__address"))
        built = _td(block, "feature-detail-data__age")
        built = re.sub(r"[（(].*$", "", built).strip()

        railway_line = nearest_station = walk_minutes = ""
        access_m = re.search(
            r'<td class="feature-detail-data__access">(.*?)(?:<br>|</td>)', block, re.DOTALL
        )
        if access_m:
            am = re.match(r"(\S+)\s+(\S+?)駅\s+徒歩(\d+)分", _text(access_m.group(1)))
            if am:
                railway_line = am.group(1)
                nearest_station = re.sub(r"[（(].*?[）)]", "", am.group(2))
                walk_minutes = am.group(3)

        for row in re.split(r'<td class="feature-detail-condition__others1 checkbox">', block)[1:]:
            fav_m = re.search(r'<span class="fav es-fav[^"]*"(.*?)>', row, re.DOTALL)
            if not fav_m:
                continue
            attrs = {
                k: html.unescape(v)
                for k, v in re.findall(r'data-([\w-]+)="([^"]*)"', fav_m.group(1))
            }
            room_id = attrs.get("identifier", "")
            floor_m = re.search(r'feature-detail-condition__floor pc">\s*(.*?)\s*<', row)

            properties.append({
                "property_name": attrs.get("building-name") or address,
                "rent": attrs.get("price", ""),
                "management_fee": attrs.get("management-fee", ""),
                "floor_plan": attrs.get("house-plan", ""),
                "area_sqm": attrs.get("major-area", ""),
                "railway_line": railway_line,
                "nearest_station": nearest_station,
                "walk_minutes": walk_minutes,
                "address": address,
                "building_year_month": built,
                "floor_info": floor_m.group(1) if floor_m else "",
                "pet_conditions": "ペット可",
                "detail_url": f"https://sengawa.re-ws.jp/rent/{room_id}/" if room_id else "",
            })

    return properties


def get_next_page_url_sengawa(raw: str) -> str | None:
    page = _results_html(raw)
    current_m = re.search(r'class="pager current" data-page="(\d+)"', page)
    if not current_m:
        return None
    next_page = int(current_m.group(1)) + 1
    if f'data-page="{next_page}"' in page:
        return sengawa_url(next_page)
    return None
