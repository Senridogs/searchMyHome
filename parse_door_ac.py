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


def parse_door_ac(html_str: str) -> list[dict]:
    blocks = re.split(r'<div\s+class="building-box">', html_str)
    properties: list[dict] = []

    for block in blocks[1:]:
        name_m = re.search(
            r'<h2\s+class="heading"[^>]*>\s*<a[^>]+href="([^"]*)"[^>]*>(.*?)</a>',
            block, re.DOTALL,
        )
        property_name = ""
        if name_m:
            property_name = _clean(_strip_tags(name_m.group(2)))
            property_name = re.sub(r'の賃貸物件情報$', '', property_name)

        summary_m = re.search(
            r'class="building-box__summary-primary">(.*?)</div>',
            block, re.DOTALL,
        )
        address = ""
        building_year = ""
        station_text = ""
        if summary_m:
            summary = summary_m.group(1)
            dds = re.findall(r'<dd>(.*?)</dd>', summary, re.DOTALL)
            for dd_html in dds:
                dd_text = _clean(_strip_tags(dd_html))
                if re.search(r'所在地', _get_preceding_dt(summary, dd_html)):
                    address = dd_text
                elif re.match(r'築\d+年', dd_text) or '新築' in dd_text:
                    building_year = dd_text
                elif re.search(r'駅|線|バス', dd_text):
                    station_text = dd_text
                elif not address and re.match(r'東京都', dd_text):
                    address = dd_text

        dl_blocks = re.findall(r'<dl\s+class="description-item[^"]*">(.*?)</dl>', block, re.DOTALL)
        for dl in dl_blocks:
            label_m = re.search(r'<span\s+class="label-property-item">(.*?)</span>', dl, re.DOTALL)
            value_m = re.search(r'<dd>(.*?)</dd>', dl, re.DOTALL)
            if label_m and value_m:
                label = _clean(_strip_tags(label_m.group(1)))
                value = _clean(_strip_tags(value_m.group(1)))
                if '所在地' in label and not address:
                    address = value
                elif '築年' in label and not building_year:
                    building_year = value
                elif '最寄' in label and not station_text:
                    station_text = value

        railway_line = ""
        nearest_station = ""
        walk_minutes = ""
        sm = re.match(r'(.+?)\s+(.+?駅)\s+徒歩(\d+)分', station_text)
        if sm:
            railway_line = sm.group(1)
            nearest_station = sm.group(2)
            walk_minutes = sm.group(3) + "分"

        rows = re.findall(r'<tbody>(.*?)</tbody>', block, re.DOTALL)
        if not rows:
            rows = [block]

        for row_block in rows:
            trs = re.findall(r'<tr>(.*?)</tr>', row_block, re.DOTALL)
            for tr in trs:
                if '<th>' in tr:
                    continue

                tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.DOTALL)
                if len(tds) < 6:
                    continue

                floor_info = _clean(_strip_tags(tds[0]))
                rent_html = tds[1]
                rent_m = re.search(r'emphasis-primary[^>]*[^<]*?(\d+(?:\.\d+)?)', rent_html)
                rent = (rent_m.group(1) + "万円") if rent_m else _clean(_strip_tags(rent_html))
                mgmt_fee = _clean(_strip_tags(tds[2]))
                floor_plan = _clean(_strip_tags(tds[4]))
                area_sqm = _clean(_strip_tags(tds[5]))

                detail_m = re.search(r'href="(/buildings/[^"]+)"', tr)
                detail_url = ("https://door.ac" + detail_m.group(1)) if detail_m else ""

                properties.append({
                    "property_name": property_name,
                    "rent": rent,
                    "management_fee": mgmt_fee,
                    "floor_plan": floor_plan,
                    "area_sqm": area_sqm,
                    "railway_line": railway_line,
                    "nearest_station": nearest_station,
                    "walk_minutes": walk_minutes,
                    "address": address,
                    "building_year_month": building_year,
                    "floor_info": floor_info,
                    "pet_conditions": "",
                    "detail_url": detail_url,
                })

    return properties


def _get_preceding_dt(summary: str, dd_html: str) -> str:
    pos = summary.find(dd_html)
    if pos == -1:
        return ""
    preceding = summary[:pos]
    dt_m = re.search(r'<dt>(.*?)</dt>\s*$', preceding, re.DOTALL)
    return _clean(_strip_tags(dt_m.group(1))) if dt_m else ""


def get_next_page_url_door_ac(html_str: str) -> str | None:
    next_m = re.search(
        r'<(?:span|li)\s+class="[^"]*next[^"]*"[^>]*>\s*<a\s+href="([^"]+)"',
        html_str,
        re.DOTALL,
    )
    if next_m:
        href = next_m.group(1)
        if href.startswith("/"):
            return "https://door.ac" + href
        return href
    return None
