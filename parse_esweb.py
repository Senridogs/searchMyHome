"""Agency sites on the es-web platform (*.re-ws.jp, yshome.jp, ...).

A feature/search page embeds ``var localize = {"restRoute": ..., "searchParams":
{...}}`` built from its query string (``rs=1`` makes it honour the query), and
the browser then GETs restRoute with those params, receiving {"html": ...}.
"""

import html
import json
import re
from urllib.parse import urlencode


def rest_url(page: str) -> str | None:
    """The REST URL for page 1 of the search embedded in a feature/search page."""
    m = re.search(r"var localize = (\{.*?\});\s*/\* \]\]>", page, re.DOTALL)
    if not m:
        return None
    localize = json.loads(m.group(1))
    params = []
    for key, value in localize["searchParams"].items():
        if isinstance(value, list):  # jQuery serialisation: key[]=a&key[]=b
            params += [(f"{key}[]", v) for v in value]
        else:
            params.append((key, "" if value is None else value))
    return localize["restRoute"] + "?" + urlencode(params)


def _text(fragment: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", text).strip()


def _results_html(raw: str) -> str:
    if raw.lstrip().startswith("{"):
        try:
            return json.loads(raw).get("html", "")
        except ValueError:
            return ""
    return raw


def _td(block: str, cls: str) -> str:
    m = re.search(rf'<td class="{cls}[^"]*">(.*?)</td>', block, re.DOTALL)
    return _text(m.group(1)) if m else ""


def parse_esweb(raw: str) -> list[dict]:
    page = _results_html(raw)
    properties = []

    for block in re.split(r'<article class="data', page)[1:]:
        address = re.sub(r"\s+", "", _td(block, "feature-detail-data__address"))
        built = re.sub(r"[（(].*$", "", _td(block, "feature-detail-data__age")).strip()

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
            link_m = re.search(r'<a href="(https?://[^"]+/rent/\d+/)"', row)
            if not fav_m or not link_m:
                continue
            attrs = {
                k: html.unescape(v)
                for k, v in re.findall(r'data-([\w-]+)="([^"]*)"', fav_m.group(1))
            }
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
                "pet_conditions": "ペット相談可",
                "detail_url": link_m.group(1),
            })

    return properties


def get_next_page_url_esweb(raw: str, current_url: str | None = None) -> str | None:
    page = _results_html(raw)
    current_m = re.search(r'class="pager current" data-page="(\d+)"', page)
    if not current_m or not current_url:
        return None
    next_page = int(current_m.group(1)) + 1
    if f'data-page="{next_page}"' not in page:
        return None
    return re.sub(r"([?&]page_num=)\d+", rf"\g<1>{next_page}", current_url)
