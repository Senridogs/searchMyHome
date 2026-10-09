import html
import re
import json
from html.parser import HTMLParser


def _strip_tags(html_fragment: str) -> str:
    """Remove HTML tags and return plain text."""
    result: list[str] = []

    class _TagStripper(HTMLParser):
        def handle_data(self, data: str) -> None:
            result.append(data)

    _TagStripper().feed(html_fragment)
    return "".join(result)


def _clean(text: str) -> str:
    """Normalize whitespace, strip &nbsp; and leading/trailing space."""
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_smocca(html_str: str) -> list[dict]:
    """Parse smocca.jp search results HTML and extract rental property data.

    Only extracts properties from the main search results (data-scene-name="search_result"),
    excluding PR/recommendation sliders and "similar" recommended blocks.

    Args:
        html_str: Raw HTML string of the search results page.

    Returns:
        List of dicts, one per room/unit row, with keys:
            property_name, rent, management_fee, floor_plan, area_sqm,
            railway_line, nearest_station, walk_minutes, address,
            building_year_month, floor_info, pet_conditions, detail_url
    """
    results: list[dict] = []

    # -------------------------------------------------------------------------
    # 1) Locate each property card block (div.item_list01) that is a main
    #    search result (data-scene-name="search_result").
    # -------------------------------------------------------------------------
    block_pattern = re.compile(
        r'<div\s[^>]*?class="item_list01\s[^"]*?bukken[^"]*?"'
        r'[^>]*?data-scene-name="search_result"'
        r'[^>]*?>'
        r'(.*?)'
        r'(?=<div\s[^>]*?class="item_list01\s[^"]*?bukken[^"]*?"[^>]*?>|'
        r'<div\s+id="zero-result-recommend-box"|'
        r'</form>|\Z)',
        re.DOTALL,
    )

    for block_m in block_pattern.finditer(html_str):
        block = block_m.group(0)

        # -----------------------------------------------------------------
        # Property name & detail URL from the <h3> title link
        # The link text is like "コリーナ　ヴェルデ 1階の賃貸【東京都 / 三鷹市】"
        # We also get the detail URL from each room row's "詳細を見る" button.
        # -----------------------------------------------------------------
        title_link_m = re.search(
            r'<a\s+href="(https://smocca\.jp/bukken/detail/[^"]+)"'
            r'[^>]*?class="[^"]*js_hook_link_title[^"]*"[^>]*?>'
            r'(.*?)</a>',
            block, re.DOTALL,
        )

        # Multi-room building cards; the title is "<name>の空室を探す" or plain text
        is_group = 'building-group-container' in block_m.group(0)[:300]
        if is_group:
            group_title_m = re.search(
                r'class="item_list01_title">.*?<h3[^>]*>(.*?)</h3>', block, re.DOTALL
            )
            raw_title = _clean(_strip_tags(group_title_m.group(1))) if group_title_m else ""
            property_name = re.sub(r'の空室を探す$', '', raw_title)
        elif title_link_m:
            raw_title = _clean(_strip_tags(title_link_m.group(2)))
            # Title often has "  X階の賃貸【東京都 / 区名】", strip that suffix
            property_name = re.sub(
                r'\s*\d+階の賃貸【[^】]*】\s*$', '', raw_title
            ).strip() or raw_title
        else:
            continue

        # -----------------------------------------------------------------
        # Address: icon_20_address01 followed by text
        # -----------------------------------------------------------------
        address = ""
        addr_m = re.search(
            r'icon_20_address01.*?</(?:div|span)>\s*'
            r'<div\s+class="d_table_cell[^"]*">(.*?)</div>',
            block, re.DOTALL,
        )
        if addr_m:
            address = _clean(_strip_tags(addr_m.group(1)))

        # -----------------------------------------------------------------
        # Railway line / station / walk minutes: icon_20_train01 section
        # Extract the FIRST station entry for the primary line.
        # Format: "路線名/<a>駅名</a> 徒歩Xmin" or with バスY分 ...
        # -----------------------------------------------------------------
        railway_line = ""
        nearest_station = ""
        walk_minutes = ""
        train_m = re.search(
            r'icon_20_train01.*?</(?:div|span)>\s*'
            r'<div\s+class="d_table_cell[^"]*">\s*'
            r'<span[^>]*>(.*?)</span>',
            block, re.DOTALL,
        )
        if train_m:
            train_html = train_m.group(1)
            # First line of the train info (before first <br)
            first_line_html = re.split(r'<br\s*/?>', train_html)[0]
            first_line = _clean(_strip_tags(first_line_html))
            # Pattern: "路線名/駅名 徒歩X分" or "路線名/駅名 バスY分 停留所から徒歩Z分"
            line_station_m = re.match(
                r'(.+?)/(.+?)\s+(徒?歩|バス)', first_line
            )
            if line_station_m:
                railway_line = line_station_m.group(1).strip()
                nearest_station = line_station_m.group(2).strip()
            else:
                # Fallback: no line prefix, just "駅名 徒歩X分"
                parts = first_line.split()
                if parts:
                    nearest_station = parts[0]

            # Some listings write "歩X分" instead of "徒歩X分"
            walk_m = re.search(r'徒?歩\s*(\d+)\s*分', first_line)
            if walk_m:
                walk_minutes = walk_m.group(1)

        # -----------------------------------------------------------------
        # Building info: icon_20_house01 section
        # Format: "地上X階建 / 2020年06月 / 賃貸アパート"
        # or "地上X階建 / 新築(2026年03月) / 賃貸マンション"
        # -----------------------------------------------------------------
        building_year_month = ""
        floor_count = ""
        building_m = re.search(
            r'icon_20_house01.*?</(?:div|span)>\s*'
            r'<div\s+class="d_table_cell[^"]*">(.*?)</div>',
            block, re.DOTALL,
        )
        if building_m:
            bldg_text = _clean(_strip_tags(building_m.group(1)))
            # building year/month
            ym_m = re.search(r'(\d{4}年\d{2}月)', bldg_text)
            if ym_m:
                building_year_month = ym_m.group(1)
            # floor count info like "地上2階建"
            fc_m = re.search(r'((?:地上|地下)?\d+階建)', bldg_text)
            if fc_m:
                floor_count = fc_m.group(1)

        # -----------------------------------------------------------------
        # Pet conditions: look for ペット mentions in the description
        # -----------------------------------------------------------------
        pet_conditions = ""
        desc_m = re.search(
            r'icon_20_exclamation01.*?</(?:div|span)>\s*'
            r'<div\s+class="d_table_cell[^"]*">(.*?)</div>',
            block, re.DOTALL,
        )
        if desc_m:
            desc_text = _clean(_strip_tags(desc_m.group(1)))
            pet_m = re.search(r'ペット(?:可|相談|不可|応相談|小型犬|大型犬|猫|要相談|飼育可|条件付き|OK)[^\s。、☆]*', desc_text)
            if pet_m:
                pet_conditions = pet_m.group(0)
        # If no pet info in description, the page search condition says ペット相談
        if not pet_conditions:
            if re.search(r'ペット相談|ペット可', html_str[:2000]):
                pet_conditions = "ペット相談"

        # -----------------------------------------------------------------
        # Room rows: each <tr> inside <tbody> of the item_list01_rooms table
        # has: floor, rent, management_fee, floor_plan, area_sqm, detail_url
        # -----------------------------------------------------------------
        building = {
            "property_name": property_name,
            "railway_line": railway_line,
            "nearest_station": nearest_station,
            "walk_minutes": walk_minutes,
            "address": address,
            "building_year_month": building_year_month,
            "pet_conditions": pet_conditions,
        }
        if is_group:
            results.extend(_group_rooms(block, building, floor_count))
            continue

        table_m = re.search(
            r'<table\s+class="[^"]*item_list01_rooms[^"]*"[^>]*>'
            r'(.*?)</table>',
            block, re.DOTALL,
        )
        if not table_m:
            continue

        table_html = table_m.group(1)
        # Each room is a <tr> inside <tbody>
        row_pattern = re.compile(
            r'<tbody>\s*(.*?)\s*</tbody>',
            re.DOTALL,
        )
        tbody_m = row_pattern.search(table_html)
        if not tbody_m:
            continue

        tr_pattern = re.compile(r'<tr>(.*?)</tr>', re.DOTALL)
        for tr_m in tr_pattern.finditer(tbody_m.group(1)):
            tr_html = tr_m.group(1)

            # Extract <td> cells (skip <th> which is the checkbox)
            td_pattern = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL)
            tds = td_pattern.findall(tr_html)
            # Expected order: [image, floor/room, rent/mgmt, deposit/reikin,
            #                  plan/area, direction, detail_button]
            if len(tds) < 6:
                continue

            # Floor info from tds[1]: "1階<br/> 101"
            floor_td_text = _clean(_strip_tags(tds[1]))
            floor_info = floor_td_text if floor_td_text else ""
            # Combine with building floor count
            if floor_count and floor_info:
                floor_info = f"{floor_info} / {floor_count}"
            elif floor_count:
                floor_info = floor_count

            # Rent and management fee from tds[2]
            # "<span ...><span>16.0</span>万円</span><br/> 6,000円"
            rent_parts = re.split(r'<br\s*/?>', tds[2])
            rent = ""
            management_fee = ""
            if rent_parts:
                rent = _clean(_strip_tags(rent_parts[0]))
            if len(rent_parts) > 1:
                management_fee = _clean(_strip_tags(rent_parts[1]))

            # Floor plan and area from tds[4]
            # "<span>2LDK</span><br/><span>56.89m²</span>"
            plan_parts = re.split(r'<br\s*/?>', tds[4])
            floor_plan = ""
            area_sqm = ""
            if plan_parts:
                floor_plan = _clean(_strip_tags(plan_parts[0]))
            if len(plan_parts) > 1:
                area_sqm = _clean(_strip_tags(plan_parts[1]))

            # Detail URL from tds[5] (the last td with the button)
            detail_url = ""
            detail_btn_td = tds[-1]
            url_m = re.search(
                r'href="(https://smocca\.jp/bukken/detail/[^"]+)"',
                detail_btn_td,
            )
            if url_m:
                detail_url = url_m.group(1)

            results.append({
                "property_name": property_name,
                "rent": rent,
                "management_fee": management_fee,
                "floor_plan": floor_plan,
                "area_sqm": area_sqm,
                "railway_line": railway_line,
                "nearest_station": nearest_station,
                "walk_minutes": walk_minutes,
                "address": address,
                "building_year_month": building_year_month,
                "floor_info": floor_info,
                "pet_conditions": pet_conditions,
                "detail_url": detail_url,
            })

    return results


def _group_rooms(block: str, building: dict, floor_count: str) -> list[dict]:
    """Rooms of a multi-room building card (one ``tr#z_...`` per room)."""
    rooms = []
    for row in re.split(r'<tr\s+id="z_', block)[1:]:
        def info(cls):
            m = re.search(r'<div class="' + cls + r'">(.*?)</div>\s*(?:<div class="|</div>)', row, re.DOTALL)
            return m.group(1) if m else ""

        floor = _clean(_strip_tags(info("group-bukken-room-info")))
        price = _clean(_strip_tags(re.split(r'<div class="mt_5">', info("group-bukken-price-info"))[0]))
        rent, _, fee = price.partition(" / ")
        plan_parts = re.split(r'<br\s*/?>', info("group-bukken-plan-info"))
        url_m = re.search(r'href="(https://smocca\.jp/bukken/detail/[^"]+)"', row)
        rooms.append({
            **building,
            "rent": rent.strip(),
            "management_fee": fee.strip(),
            "floor_plan": _clean(_strip_tags(plan_parts[0])),
            "area_sqm": _clean(_strip_tags(plan_parts[1])) if len(plan_parts) > 1 else "",
            "floor_info": " / ".join(filter(None, [floor, floor_count])),
            "detail_url": url_m.group(1) if url_m else "",
        })
    return rooms


def get_next_page_url_smocca(html_str: str, current_url: str | None = None) -> str | None:
    """Return the next results URL, or None when there are no more rooms.

    Page 1 links to the load-more API (``a.js-load-more-bukkens-api-pc``),
    which needs ``X-Requested-With``. API pages have no link, so the page
    number in ``current_url`` is incremented while pages still have rooms.
    """
    more_m = re.search(r'js-load-more-bukkens-api-pc[^>]*data-url="([^"]+)"', html_str)
    if more_m:
        return html.unescape(more_m.group(1))
    if current_url and "/api/bukken/list" in current_url and parse_smocca(html_str):
        page_m = re.search(r'([?&]page=)(\d+)', current_url)
        if page_m:
            return current_url.replace(page_m.group(0), page_m.group(1) + str(int(page_m.group(2)) + 1))
    return None


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python parse_smocca.py <html_file>")
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        page = f.read()

    props = parse_smocca(page)
    print(json.dumps(props, ensure_ascii=False, indent=2))
    print(f"\nTotal properties: {len(props)}")

    next_url = get_next_page_url_smocca(page)
    print(f"Next page URL: {next_url}")
