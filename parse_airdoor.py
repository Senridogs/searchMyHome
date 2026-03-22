import re
import json
from html.parser import HTMLParser


def parse_airdoor(html_str: str) -> list[dict]:
    """Parse airdoor.jp search results HTML and extract rental property data.

    Airdoor is a Next.js SSR site that embeds property data as React Server
    Components flight payload inside <script> tags.  This function decodes
    that payload, extracts SearchBuilding objects (which contain nested
    SearchRoom objects), and returns one dict per room.

    Args:
        html_str: Raw HTML string of the search results page.

    Returns:
        List of dicts, one per property, with keys:
            property_name, rent, management_fee, floor_plan, area_sqm,
            railway_line, nearest_station, walk_minutes, address,
            building_year_month, floor_info, pet_conditions, detail_url
    """
    results = []

    # --- Step 1: Decode the RSC flight payload --------------------------
    flight_data = _decode_flight_payload(html_str)

    # --- Step 2: Parse line-keyed JSON values ---------------------------
    # Each flight line looks like "hex_id:{...}" or "hex_id:[...]".
    # We parse individual JSON values keyed by their hex id so that "$xx"
    # references can be resolved later if needed.
    value_map = _build_value_map(flight_data)

    # --- Step 3: Extract SearchBuilding objects -------------------------
    # These contain full building metadata (address, stations, year, etc.)
    # and a nested "rooms" array of SearchRoom objects with rent info.
    buildings = _extract_buildings(flight_data, value_map)

    for building in buildings:
        # Building-level fields
        building_name = building.get("name", "")
        address = building.get("address", "")
        constructed = building.get("constructed_yr_mo", "")
        total_floors = building.get("total_floors", "")

        # Station info from the first station entry
        railway_line = ""
        nearest_station = ""
        walk_minutes = ""
        stations = building.get("stations", [])
        if stations and isinstance(stations, list) and len(stations) > 0:
            first_station = stations[0]
            if isinstance(first_station, dict):
                full_text = first_station.get("full_text", "")
                railway_line, nearest_station, walk_minutes = (
                    _parse_station_text(full_text)
                )

        # Pet conditions from building-level tags
        building_tags = building.get("tags", [])
        pet_conditions = _extract_pet_conditions(building_tags)

        # Each room in the building
        rooms = building.get("rooms", [])
        if not isinstance(rooms, list):
            continue

        for room in rooms:
            if not isinstance(room, dict):
                continue

            # Resolve $-references for nested objects
            rent_obj = _resolve_ref(room.get("rent"), value_map)
            admin_obj = _resolve_ref(
                room.get("administration_fee"), value_map
            )

            rent = ""
            if isinstance(rent_obj, dict):
                rent = rent_obj.get("display_text", "")
            elif isinstance(rent_obj, str):
                rent = rent_obj

            management_fee = ""
            if isinstance(admin_obj, dict):
                management_fee = admin_obj.get("display_text", "")
            elif isinstance(admin_obj, str):
                management_fee = admin_obj

            floor_plan = room.get("floor_plan", "")
            area_sqm = room.get("room_area", "")
            unit_name = room.get("unit_name", "")

            # Derive floor info from unit_name (e.g. "0601号室" -> "6階")
            floor_info = _derive_floor_info(unit_name)

            # Room-level pet tags
            room_tags = room.get("tags", [])
            room_pet = _extract_pet_conditions(room_tags)
            combined_pet = (
                ", ".join(filter(None, [pet_conditions, room_pet]))
                if pet_conditions or room_pet
                else ""
            )

            # Detail URL: constructed from building and room ids
            building_id = room.get("building_id", building.get("id", ""))
            room_id = room.get("id", "")
            detail_url = ""
            if building_id and room_id:
                detail_url = (
                    f"https://airdoor.jp/buildings/{building_id}"
                    f"/rooms/{room_id}"
                )

            prop = {
                "property_name": building_name,
                "rent": rent,
                "management_fee": management_fee,
                "floor_plan": floor_plan,
                "area_sqm": area_sqm,
                "railway_line": railway_line,
                "nearest_station": nearest_station,
                "walk_minutes": walk_minutes,
                "address": address,
                "building_year_month": constructed,
                "floor_info": floor_info,
                "pet_conditions": combined_pet,
                "detail_url": detail_url,
            }
            results.append(prop)

    return results


def get_next_page_url_airdoor(html_str: str) -> str | None:
    """Extract the next page URL from airdoor.jp search results HTML.

    Airdoor uses query-parameter-based pagination.  The current search URL
    is stored in the flight payload under ``pathName``.  If the page has
    buildings listed and the current URL does not already contain a ``p=``
    parameter at the maximum page, we construct the next-page URL by
    incrementing (or adding) the ``p=`` query parameter.

    Args:
        html_str: Raw HTML string of the search results page.

    Returns:
        Absolute URL string for the next page, or None if on the last page
        or unable to determine pagination.
    """
    flight_data = _decode_flight_payload(html_str)

    # Find pathName value
    path_m = re.search(r'"pathName":"([^"]+)"', flight_data)
    if not path_m:
        return None

    raw_path = path_m.group(1)
    # Decode unicode escapes (\u0026 -> &)
    path = raw_path.encode().decode("unicode_escape")

    # Check if there are buildings on this page (if not, we are past the end)
    if '"__typename":"SearchBuilding"' not in flight_data:
        return None

    # Determine current page number
    page_m = re.search(r'[?&]p=(\d+)', path)
    if page_m:
        current_page = int(page_m.group(1))
        next_page = current_page + 1
        next_path = re.sub(
            r'([?&])p=\d+', rf'\g<1>p={next_page}', path
        )
    else:
        # No p= param means page 1; add p=2
        separator = "&" if "?" in path else "?"
        next_path = path + separator + "p=2"

    # Make absolute
    if next_path.startswith("/"):
        return "https://airdoor.jp" + next_path
    if not next_path.startswith("http"):
        return "https://airdoor.jp/" + next_path
    return next_path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _decode_flight_payload(html_str: str) -> str:
    """Extract and decode the React Server Components flight payload."""
    chunks = []
    for m in re.finditer(
        r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html_str, re.DOTALL
    ):
        raw = m.group(1)
        decoded = raw.replace('\\n', '\n').replace('\\"', '"')
        decoded = decoded.replace('\\\\', '\\')
        chunks.append(decoded)
    return "".join(chunks)


def _build_value_map(flight_data: str) -> dict:
    """Build a map of hex-id -> parsed JSON value from flight data lines.

    Each line in the flight data has the format ``hex_id:JSON_VALUE``.
    We parse each one and store it keyed by ``$hex_id`` for reference
    resolution.
    """
    value_map = {}
    for line in flight_data.split("\n"):
        colon_m = re.match(r'^([0-9a-fA-F]+):', line)
        if not colon_m:
            continue
        hex_id = colon_m.group(1)
        json_str = line[colon_m.end():]
        try:
            value_map["$" + hex_id] = json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            pass
    return value_map


def _resolve_ref(value, value_map: dict):
    """If *value* is a ``$hex_id`` reference string, resolve it."""
    if isinstance(value, str) and re.match(r'^\$[0-9a-fA-F]+$', value):
        return value_map.get(value, value)
    return value


def _extract_buildings(flight_data: str, value_map: dict) -> list[dict]:
    """Extract SearchBuilding JSON objects from flight data.

    Buildings contain ``"__typename":"SearchBuilding"`` and hold both
    building metadata and a nested ``rooms`` array.  We find them by
    locating balanced-brace JSON objects that contain this typename.
    """
    buildings = []
    search_start = 0

    while True:
        idx = flight_data.find('"constructed_yr_mo"', search_start)
        if idx == -1:
            break

        # Walk backwards to the opening brace of this object
        start = idx
        depth = 0
        for i in range(idx, -1, -1):
            if flight_data[i] == '}':
                depth += 1
            elif flight_data[i] == '{':
                if depth == 0:
                    start = i
                    break
                depth -= 1

        # Walk forwards to find the matching closing brace
        depth = 0
        end = start
        for i in range(start, len(flight_data)):
            if flight_data[i] == '{':
                depth += 1
            elif flight_data[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

        search_start = end

        try:
            obj = json.loads(flight_data[start:end])
        except (json.JSONDecodeError, ValueError):
            continue

        if obj.get("__typename") == "SearchBuilding":
            buildings.append(obj)

    return buildings


def _parse_station_text(full_text: str) -> tuple[str, str, str]:
    """Parse a station full_text like '日暮里舎人ライナー 西新井大師西駅 徒歩10分'.

    Returns:
        (railway_line, station_name, walk_minutes) as strings.
    """
    m = re.match(r'(.+?)\s+(.+?)駅\s+徒歩(\d+)分', full_text)
    if m:
        return m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
    return "", "", ""


def _extract_pet_conditions(tags) -> str:
    """Extract pet-related conditions from a list of tag dicts."""
    if not isinstance(tags, list):
        return ""
    pet_tags = []
    for tag in tags:
        if isinstance(tag, dict):
            name = tag.get("name", "")
            if "ペット" in name:
                pet_tags.append(name)
    return ", ".join(pet_tags)


def _derive_floor_info(unit_name: str) -> str:
    """Derive floor number from a unit name like '0601号室' -> '6階'.

    Airdoor unit names typically encode the floor in the leading digits.
    For 3-digit units (e.g. '305号室'), the first digit is the floor.
    For 4-digit units (e.g. '0601号室'), digits 1-2 (or the leading
    non-zero portion) are the floor.
    """
    m = re.match(r'0*(\d+)\d{2}号室', unit_name)
    if m:
        floor_num = m.group(1)
        if floor_num:
            return floor_num + "階"
    return ""


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

    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/rental_html/airdoor_p1.html"
    with open(path, encoding="utf-8") as f:
        html = f.read()

    props = parse_airdoor(html)
    print(f"Found {len(props)} properties\n")
    for p in props[:3]:
        print(json.dumps(p, ensure_ascii=False, indent=2))
        print()

    next_url = get_next_page_url_airdoor(html)
    print(f"Next page URL: {next_url}")
