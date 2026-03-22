import re
import json
from html.parser import HTMLParser


def parse_chintai_ex(html_str: str) -> list[dict]:
    """Parse chintai-ex.jp search results HTML and extract rental property data.

    Args:
        html_str: Raw HTML string of the search results page.

    Returns:
        List of dicts, one per property, with keys:
            property_name, rent, management_fee, floor_plan, area_sqm,
            railway_line, nearest_station, walk_minutes, address,
            building_year_month, floor_info, pet_conditions, detail_url
    """
    results = []

    # Each property block starts with an <h3> title containing the detail link,
    # followed by a <table class="...js-bukken bukken"...> with the data rows.

    # 1) Extract property blocks: from each <h3 class="titleStyle01 ..."> to the
    #    next one (or end of bukkenList div).
    #    We split on the h3 title pattern.

    # Pattern for the h3 property title block
    h3_pattern = re.compile(
        r'<h3\s+class="titleStyle01[^"]*"[^>]*>\s*<span[^>]*>\s*'
        r'(?:<span[^>]*>\[NEW\]</span>\s*)?'
        r'<a\s+href="(https://chintai-ex\.jp/dwelling/show/[^"]+)"[^>]*>\s*'
        r'(.+?)\s*</a>',
        re.DOTALL,
    )

    # Split html into property sections using the table with class js-bukken
    table_pattern = re.compile(
        r'<table\s+class="[^"]*js-bukken\s+bukken"[^>]*>(.+?)</table>',
        re.DOTALL,
    )

    # Find all h3 titles (gives us name + detail_url)
    h3_matches = list(h3_pattern.finditer(html_str))
    # Find all property tables
    table_matches = list(table_pattern.finditer(html_str))

    for i, h3_match in enumerate(h3_matches):
        detail_url = h3_match.group(1).strip()
        property_name = _strip_tags(h3_match.group(2)).strip()

        if i >= len(table_matches):
            break

        table_html = table_matches[i].group(1)

        prop = {
            "property_name": property_name,
            "rent": "",
            "management_fee": "",
            "floor_plan": "",
            "area_sqm": "",
            "railway_line": "",
            "nearest_station": "",
            "walk_minutes": "",
            "address": "",
            "building_year_month": "",
            "floor_info": "",
            "pet_conditions": "",
            "detail_url": detail_url,
        }

        # --- Address ---
        addr_m = re.search(
            r'icon_address06[^>]*></span>\s*</div>\s*'
            r'<div\s+class="displayTableCell[^"]*">\s*(.+?)\s*<br\s*/?>',
            table_html,
            re.DOTALL,
        )
        if addr_m:
            prop["address"] = _strip_tags(addr_m.group(1)).strip()

        # --- Railway line / station / walk minutes ---
        train_m = re.search(
            r'icon_train06[^>]*></span>\s*</div>\s*'
            r'<div\s+class="displayTableCell[^"]*">\s*(.+?)\s*</div>',
            table_html,
            re.DOTALL,
        )
        if train_m:
            train_text = _clean_text(train_m.group(1))
            # Format: "路線名/駅名 徒歩N分"
            line_station_m = re.match(
                r'(.+?)[/／](.+?)\s+徒歩(\d+)分', train_text
            )
            if line_station_m:
                prop["railway_line"] = line_station_m.group(1).strip()
                prop["nearest_station"] = line_station_m.group(2).strip()
                prop["walk_minutes"] = line_station_m.group(3).strip()

        # --- Extract <tr> rows for structured data ---
        rows = re.findall(r'<tr>(.*?)</tr>', table_html, re.DOTALL)
        for row in rows:
            cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', row, re.DOTALL)
            # Process pairs of (header, value)
            j = 0
            while j < len(cells) - 1:
                header = _clean_text(cells[j])
                value = _clean_text(cells[j + 1])

                if '賃料' in header:
                    prop["rent"] = value
                    j += 2
                elif '共益費' in header or '管理費' in header:
                    prop["management_fee"] = value
                    j += 2
                elif '間取' in header and '面積' in header:
                    # "間取 / 面積" -> value like "1LDK / 50.57m²"
                    parts = re.split(r'\s*/\s*', value)
                    if len(parts) >= 2:
                        prop["floor_plan"] = parts[0].strip()
                        prop["area_sqm"] = parts[1].strip()
                    else:
                        prop["floor_plan"] = value
                    j += 2
                elif '階層' in header and '方位' in header:
                    prop["floor_info"] = value
                    j += 2
                elif '築年月' in header:
                    prop["building_year_month"] = value
                    j += 2
                elif '特徴' in header:
                    # Extract pet conditions from feature tags
                    pet_tags = re.findall(
                        r'(ペット[^<]*)', cells[j + 1]
                    )
                    prop["pet_conditions"] = (
                        ", ".join(t.strip() for t in pet_tags) if pet_tags else ""
                    )
                    j += 2
                else:
                    j += 1

        results.append(prop)

    return results


def get_next_page_url_chintai_ex(html_str: str) -> str | None:
    """Extract the next page URL from chintai-ex.jp search results HTML.

    Looks for the pagination section (pagerKaminari) and finds the link
    for the page following the currently active page.

    Args:
        html_str: Raw HTML string of the search results page.

    Returns:
        Absolute URL string for the next page, or None if on the last page.
    """
    # The current page is shown as a <span> (not a link) inside pagerKaminari.
    # The next page link follows it.
    # Pattern: active page is <span class="backgroundColor11 ...">N</span>
    # Next page link is in the next <li>: <a href="...">N+1</a>

    pager_m = re.search(
        r'<ul\s+class="pagerKaminari">(.*?)</ul>', html_str, re.DOTALL
    )
    if not pager_m:
        return None

    pager_html = pager_m.group(1)

    # Find the active (current) page span, then the very next <a href="...">
    # that is a numbered page (not the ">>最後" link).
    active_m = re.search(
        r'<span\s+class="backgroundColor11[^"]*">[^<]*</span>\s*</li>'
        r'\s*<li[^>]*>\s*<a\s+href="([^"]*)"[^>]*>(\d+)</a>',
        pager_html,
        re.DOTALL,
    )
    if active_m:
        raw_url = active_m.group(1)
        # Unescape HTML entities
        from html import unescape
        url = unescape(raw_url)
        # Make absolute if relative
        if url.startswith("/"):
            url = "https://chintai-ex.jp" + url
        return url

    return None


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
