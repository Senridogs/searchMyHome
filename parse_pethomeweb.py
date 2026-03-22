import re
import json
from html.parser import HTMLParser


def parse_pethomeweb(html_str: str) -> list[dict]:
    """Parse pethomeweb.com search results HTML and extract rental property data.

    Args:
        html_str: Raw HTML string of the search results page.

    Returns:
        List of dicts, one per property, with keys:
            property_name, rent, management_fee, floor_plan, area_sqm,
            railway_line, nearest_station, walk_minutes, address,
            building_year_month, floor_info, pet_conditions, detail_url
    """
    results = []

    # Each property is inside <li class="result-item sys-list" ...> ... </li>
    # We extract each block and parse fields from it.

    item_pattern = re.compile(
        r'<li\s+class="result-item\s+sys-list"[^>]*>(.*?)</li>\s*(?=<li\s+'
        r'class="result-item\s+sys-list"|</ul>)',
        re.DOTALL,
    )

    for item_m in item_pattern.finditer(html_str):
        block = item_m.group(1)

        prop = {
            "property_name": "",
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
            "detail_url": "",
        }

        # --- Property name and detail URL ---
        title_m = re.search(
            r'<a\s+href="([^"]+)"\s+class="result-item__title__link[^"]*"'
            r'[^>]*>(.+?)</a>',
            block,
            re.DOTALL,
        )
        if title_m:
            raw_url = title_m.group(1).strip()
            if raw_url.startswith("/"):
                raw_url = "https://www.pethomeweb.com" + raw_url
            prop["detail_url"] = raw_url
            prop["property_name"] = _clean_text(title_m.group(2))

        # --- Address ---
        addr_m = re.search(
            r'<p\s+class="result-item__address">(.+?)</p>',
            block,
            re.DOTALL,
        )
        if addr_m:
            prop["address"] = _clean_text(addr_m.group(1))

        # --- Extract full cell text for rent, fee, floor plan, area ---
        # The result-item__table__cell contains all pricing and layout info.
        # After cleaning: "5.20万円※税込（管理費等 4,000円※税込） ワンルーム 10.62㎡ ..."
        cell_m = re.search(
            r'<div\s+class="result-item__table__cell">(.*?)'
            r'<div\s+class="result-item__kotsu',
            block,
            re.DOTALL,
        )
        if cell_m:
            cell_text = _clean_text(cell_m.group(1))

            # Rent: N.NN万円
            rent_m = re.search(r'([\d.]+)万円', cell_text)
            if rent_m:
                prop["rent"] = rent_m.group(1) + "万円"

            # Management fee: （管理費等 VALUE）
            fee_m = re.search(
                r'（管理費等\s*(.+?)(?:※[^）]*)?）', cell_text
            )
            if fee_m:
                prop["management_fee"] = fee_m.group(1).strip()

            # Floor plan and area: after ）, e.g. "） ワンルーム 10.62㎡"
            plan_area_m = re.search(
                r'）\s*(.+?)\s+([\d.]+)㎡', cell_text
            )
            if plan_area_m:
                prop["floor_plan"] = plan_area_m.group(1).strip()
                prop["area_sqm"] = plan_area_m.group(2) + "㎡"

        # --- Railway line / station / walk minutes ---
        # Primary transport: <div class="result-item__kotsu1">LINE STATION 徒歩N分</div>
        kotsu_m = re.search(
            r'<div\s+class="result-item__kotsu1">(.+?)</div>',
            block,
            re.DOTALL,
        )
        if kotsu_m:
            kotsu_text = _clean_text(kotsu_m.group(1))
            # Format: "東急大井町線 九品仏駅 徒歩1分"
            train_m = re.match(
                r'(.+?)\s+(.+?駅)\s+徒歩(\d+)分', kotsu_text
            )
            if train_m:
                prop["railway_line"] = train_m.group(1).strip()
                prop["nearest_station"] = train_m.group(2).strip()
                prop["walk_minutes"] = train_m.group(3).strip()

        # --- Pet conditions ---
        # Pattern: <i class="fa fa-paw"></i> followed by pet text,
        # potentially separated by HTML comments and whitespace.
        pet_m = re.search(
            r'<i\s+class="fa\s+fa-paw"></i>(.*?)</span>',
            block,
            re.DOTALL,
        )
        if pet_m:
            pet_text = _clean_text(pet_m.group(1))
            if pet_text:
                prop["pet_conditions"] = pet_text

        # --- Building year and floor info ---
        # These are not available on the listing page, only on detail pages.
        # Leave as empty strings.

        results.append(prop)

    return results


def get_next_page_url_pethomeweb(html_str: str) -> str | None:
    """Extract the next page URL from pethomeweb.com search results HTML.

    Pethomeweb uses JavaScript-driven pagination with pvalue attributes
    rather than real href URLs. This function constructs the next page URL
    from the canonical URL and the next page number.

    Args:
        html_str: Raw HTML string of the search results page.

    Returns:
        Absolute URL string for the next page, or None if on the last page.
    """
    # Find the "次" (next) pagination link with its pvalue
    next_m = re.search(
        r'<a\s+href="[^"]*"\s+class="pagination__item--next\s+sys-paging"'
        r'\s+pvalue="(\d+)"',
        html_str,
    )
    if not next_m:
        return None

    next_page = next_m.group(1)

    # Get the canonical URL as base
    canonical_m = re.search(
        r'<link\s+rel="canonical"\s+href="([^"]+)"', html_str
    )
    if canonical_m:
        base_url = canonical_m.group(1).rstrip("/")
    else:
        return None

    # Construct the next page URL: base_url?page=N
    return f"{base_url}/?page={next_page}"


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
    text = text.replace('&emsp;', ' ')
    text = text.replace('&ensp;', ' ')
    text = text.replace('\u3000', ' ')
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/rental_html/pethomeweb_p1.html"
    with open(path, encoding="utf-8") as f:
        html = f.read()

    props = parse_pethomeweb(html)
    print(f"Found {len(props)} properties\n")
    for p in props[:3]:
        print(json.dumps(p, ensure_ascii=False, indent=2))
        print()

    next_url = get_next_page_url_pethomeweb(html)
    print(f"Next page URL: {next_url}")
