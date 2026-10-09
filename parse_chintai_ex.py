import re
import json
from html.parser import HTMLParser


NEAR_MISS_HEADING = "お探しになっている条件に近い物件"


def parse_chintai_ex(html_str: str) -> list[dict]:
    """Parse chintai-ex.jp search results (building-grouped layout).

    Each building is a ``div.building-group-container`` whose header holds
    name/address/station/building info, followed by one ``tr#z_...`` per room.
    Near-miss suggestions after NEAR_MISS_HEADING are ignored.
    """
    cut = html_str.find(NEAR_MISS_HEADING)
    if cut != -1:
        html_str = html_str[:cut]

    results = []
    for block in re.split(r'<div\s+class="building-group-container', html_str)[1:]:
        if 'data-scene-name="search_result"' not in block[:1000]:
            continue

        # The title is a link for single-room buildings and plain text otherwise
        name_m = re.search(
            r'class="group-building-title-(?:link|text)[^"]*"[^>]*>(.*?)</(?:a|span)>', block, re.DOTALL
        )
        property_name = _clean_text(name_m.group(1)) if name_m else ""
        address = _clean_text(_icon_cell(block, "icon_address06"))

        railway_line = nearest_station = walk_minutes = ""
        train_html = re.split(r'<br\s*/?>', _icon_cell(block, "icon_train06"))[0]
        train_m = re.match(r'(?:(.+?)[/／])?(\S+?)駅?\s*徒?歩\s*(\d+)分', _clean_text(train_html))
        if train_m:
            railway_line = (train_m.group(1) or "").strip()
            nearest_station = train_m.group(2)
            walk_minutes = train_m.group(3)

        building_info = _clean_text(_icon_cell(block, "icon_home06"))
        built_m = re.search(r'新築|\d{4}年\d{1,2}月', building_info)
        floors_m = re.search(r'(?:地上|地下)?\d+階建', building_info)
        structure = building_info.rsplit("/", 1)[-1].strip() if "/" in building_info else ""

        rows = re.split(r'<tr\s+id="z_', block)[1:]
        for row in rows:
            floor = _clean_text(_cell(row, "group-bukken-room-cell"))
            rent_m = re.search(r'class="group-bukken-chinryou">(.*?</span>)\s*</span>', row, re.DOTALL)
            fee_m = re.search(r'class="group-bukken-kanri">(.*?)</span>', row, re.DOTALL)
            rent = _clean_text(rent_m.group(1)) if rent_m else ""
            management_fee = _clean_text(fee_m.group(1)).lstrip("/ ").strip() if fee_m else ""
            plan_parts = re.split(r'<br\s*/?>', _cell(row, "group-bukken-plan-cell"))
            detail_m = re.search(r'href="([^"]*/dwelling/show/[^"]+)"', row)
            labels = re.findall(r'class="group-bukken-label-blue">([^<]*)<', row)

            detail_url = detail_m.group(1) if detail_m else ""
            if detail_url.startswith("/"):
                detail_url = "https://chintai-ex.jp" + detail_url

            results.append({
                "property_name": property_name,
                "rent": rent,
                "management_fee": management_fee,
                "floor_plan": _clean_text(plan_parts[0]),
                "area_sqm": _clean_text(plan_parts[1]) if len(plan_parts) > 1 else "",
                "railway_line": railway_line,
                "nearest_station": nearest_station,
                "walk_minutes": walk_minutes,
                "address": address,
                "building_year_month": built_m.group(0) if built_m else "",
                "floor_info": " / ".join(filter(None, [floor, floors_m.group(0) if floors_m else ""])),
                "structure": structure,
                "pet_conditions": ", ".join(l.strip() for l in labels if "ペット" in l),
                "detail_url": detail_url,
            })

    return results


def get_next_page_url_chintai_ex(html_str: str, current_url: str | None = None) -> str | None:
    """Only the first page is fetched.

    The page has no pager, ``&page=N`` redirects to page 1, and the load-more
    API repeats recommended rooms on every page without ending. With the
    search sorted by 新着順, page 1 (60 rooms) covers each day's new arrivals.
    """
    return None


def _icon_cell(block: str, icon: str) -> str:
    m = re.search(
        icon + r'"></span></div>\s*<div class="displayTableCell[^"]*">(.*?)</div>',
        block, re.DOTALL,
    )
    return m.group(1) if m else ""


def _cell(row: str, cls: str) -> str:
    m = re.search(r'<td class="' + cls + r'[^"]*">(.*?)</td>', row, re.DOTALL)
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _strip_tags(html_fragment: str) -> str:
    """Remove all HTML tags from a fragment, returning plain text."""
    return re.sub(r'<[^>]+>', '', html_fragment)


def _clean_text(html_fragment: str) -> str:
    """Strip tags, decode common entities, and normalise whitespace."""
    text = _strip_tags(html_fragment)
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")
    text = text.replace('\u3000', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/rental_html/chintai_ex_p1.html"
    with open(path, encoding="utf-8") as f:
        html = f.read()

    props = parse_chintai_ex(html)
    print(f"Found {len(props)} properties\n")
    for p in props:
        print(json.dumps(p, ensure_ascii=False, indent=2))
        print()

    next_url = get_next_page_url_chintai_ex(html)
    print(f"Next page URL: {next_url}")
