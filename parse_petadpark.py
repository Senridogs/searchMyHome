import re
import html.parser
import json


def parse_petadpark(html_str: str) -> list[dict]:
    """Parse pet-adpark.jp search result HTML and extract property data.

    Args:
        html_str: Raw HTML string of the search results page.

    Returns:
        List of dicts, one per property, with keys:
            property_name, rent, management_fee, floor_plan, area_sqm,
            railway_line, nearest_station, walk_minutes, address,
            building_age, floor_info, pet_conditions, detail_url
    """
    h = html.parser.HTMLParser()
    _unescape = getattr(html, 'unescape', getattr(h, 'unescape', None))

    # --- Step 1: Extract JS objects (thisObj0 .. thisObjN) ---
    # Each block looks like:  var thisObj0 = { ... };
    js_pattern = re.compile(
        r"var\s+thisObj(\d+)\s*=\s*\{(.*?)\};",
        re.DOTALL,
    )

    def _js_val(block: str, key: str) -> str:
        """Extract a value from a JS object literal by key name."""
        # Handles both single- and double-quoted string values
        m = re.search(
            r"'" + re.escape(key) + r"'\s*:\s*['\"](.+?)['\"]",
            block,
        )
        if m:
            val = m.group(1)
            # Strip HTML tags like <sup>2</sup>
            val = re.sub(r"<[^>]+>", "", val)
            return val.strip()
        # Try unquoted (numeric etc.)
        m = re.search(
            r"'" + re.escape(key) + r"'\s*:\s*([^,\n]+)",
            block,
        )
        if m:
            val = m.group(1).strip().strip("'\"")
            val = re.sub(r"<[^>]+>", "", val)
            return val.strip()
        return ""

    # --- Step 2: Extract POINT texts (pet conditions) from HTML ---
    # They are in <h4 class="search_list_item_point_txt_v3-2">...</h4>
    # One per property that has a POINT block; some properties lack one.
    # We correlate them by matching each thisObj to its surrounding HTML.

    # Strategy: for each property, find the POINT text that appears between
    # its <li> start and its </li> end in the HTML.

    # First, find all <li class="search_list_item_v3-2" ...> blocks
    # and extract the POINT text from each.
    li_pattern = re.compile(
        r'<li\s+class="search_list_item_v3-2"[^>]*>(.*?)</li>\s*(?=(?:<script>|</ul>))',
        re.DOTALL,
    )
    point_pattern = re.compile(
        r'class="search_list_item_point_txt_v3-2">(.*?)</h4>',
        re.DOTALL,
    )
    li_blocks = li_pattern.findall(html_str)
    point_texts: list[str] = []
    for li_block in li_blocks:
        pm = point_pattern.search(li_block)
        if pm:
            txt = pm.group(1).strip()
            txt = re.sub(r"<[^>]+>", "", txt)
            txt = _unescape(txt) if _unescape else txt
            point_texts.append(txt)
        else:
            point_texts.append("")

    # --- Step 3: Build result list ---
    results: list[dict] = []
    js_blocks = js_pattern.findall(html_str)

    for idx, (obj_idx, block) in enumerate(js_blocks):
        title = _js_val(block, "title")
        url = _js_val(block, "url")
        price = _js_val(block, "price")
        address = _js_val(block, "address")
        traffic1 = _js_val(block, "traffic1")
        madori = _js_val(block, "madori")
        space = _js_val(block, "space")
        kanrihi = _js_val(block, "kanrihi")
        age = _js_val(block, "age")
        floorstr = _js_val(block, "floorstr")

        # Unescape HTML entities
        if _unescape:
            title = _unescape(title)
            url = _unescape(url)
            address = _unescape(address)

        # Parse traffic1 -> railway_line, station, walk_minutes
        railway_line = ""
        nearest_station = ""
        walk_minutes = ""
        if traffic1:
            # Format: "路線名 駅名 徒歩N分" or "路線名 駅名 バスN分 停歩N分"
            t_match = re.match(
                r"(.+?)\s+(.+?)\s+徒歩(\d+)分",
                traffic1,
            )
            if t_match:
                railway_line = t_match.group(1)
                nearest_station = t_match.group(2)
                walk_minutes = t_match.group(3)
            else:
                # Try bus pattern or other
                t_match2 = re.match(r"(.+?)\s+(.+?)\s+(.*)", traffic1)
                if t_match2:
                    railway_line = t_match2.group(1)
                    nearest_station = t_match2.group(2)
                    walk_minutes = t_match2.group(3)

        # Parse area: "61.55m2" -> "61.55"
        area_sqm = re.sub(r"m2?$", "", space).strip() if space else ""

        # Pet conditions from POINT text
        pet_conditions = point_texts[idx] if idx < len(point_texts) else ""

        results.append({
            "property_name": title,
            "rent": price,
            "management_fee": kanrihi,
            "floor_plan": madori,
            "area_sqm": area_sqm,
            "railway_line": railway_line,
            "nearest_station": nearest_station,
            "walk_minutes": walk_minutes,
            "address": address,
            "building_age": age,
            "floor_info": floorstr,
            "pet_conditions": pet_conditions,
            "detail_url": url,
        })

    return results


def get_next_page_url_petadpark(html_str: str) -> str | None:
    """Extract the 'next page' URL from pet-adpark search results.

    Args:
        html_str: Raw HTML string of the search results page.

    Returns:
        Absolute URL string for the next page, or None if there is no next page.
    """
    _unescape = getattr(html, 'unescape', None)
    if _unescape is None:
        _unescape = html.parser.HTMLParser().unescape

    # The pagination is in:
    #   <li class="search_list_pager_next"><a href="...">次へ</a></li>
    m = re.search(
        r'class="search_list_pager_next">\s*<a\s+href="([^"]+)"',
        html_str,
    )
    if m:
        url = m.group(1)
        url = _unescape(url)
        return url
    return None


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/rental_html/petadpark_p1.html"
    with open(path, encoding="utf-8") as f:
        raw = f.read()

    props = parse_petadpark(raw)
    print(f"Found {len(props)} properties\n")
    for i, p in enumerate(props):
        print(f"--- Property {i+1} ---")
        for k, v in p.items():
            print(f"  {k}: {v}")
        print()

    nxt = get_next_page_url_petadpark(raw)
    print(f"Next page URL: {nxt}")
