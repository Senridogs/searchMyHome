"""
Parser for R-STORE (r-store.jp) rental property search result pages.

Uses only Python stdlib: re, html.parser, json.
"""

import re
from html.parser import HTMLParser


BASE_URL = "https://www.r-store.jp"


class _RStoreListingParser(HTMLParser):
    """
    Parses an R-STORE search results page and extracts property data.

    Available fields on the listing page:
      - property name (物件名): from room_title span (includes station prefix)
      - rent (家賃) and management fee (管理費): from post-price h3
      - floor plan (間取り): from spec-madori span
      - area (面積): from spec-area span
      - walk minutes (徒歩分数): from spec-time span
      - building year/month (築年月): from year span
      - detail URL (物件詳細URL): from the <a> wrapping each listing
      - room number: from room_number span (used to infer floor)

    Fields NOT present on the listing page (set to None):
      - railway line name (路線名)
      - nearest station (最寄駅) — partially extractable from title prefix
      - address (住所)
      - pet conditions (ペット条件)
    """

    def __init__(self):
        super().__init__()
        self.properties = []
        self._current = None

        # State tracking
        self._in_post = False
        self._in_link = False
        self._current_href = None
        self._capture = None  # which field we're capturing text for
        self._depth = 0  # nesting depth inside post div

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")

        # Detect start of a property listing block
        if tag == "div" and "post" in cls.split() and "post-list" in cls.split():
            self._in_post = True
            self._depth = 1
            self._current = {
                "property_name": None,
                "rent": None,
                "management_fee": None,
                "floor_plan": None,
                "area_sqm": None,
                "railway_line": None,
                "nearest_station": None,
                "walk_minutes": None,
                "address": None,
                "building_year_month": None,
                "floor_info": None,
                "pet_conditions": None,
                "detail_url": None,
            }
            self._current_href = None
            return

        if not self._in_post:
            return

        # Track div nesting
        if tag == "div":
            self._depth += 1

        # Capture the detail link (first <a> with href containing /chintai/room/ or /room/)
        if tag == "a":
            href = attrs_dict.get("href", "")
            if "/room/" in href and self._current.get("detail_url") is None:
                if href.startswith("/"):
                    self._current["detail_url"] = BASE_URL + href
                else:
                    self._current["detail_url"] = href
                self._current_href = href

        # Identify spans/elements to capture
        if tag == "span":
            if "room_title" in cls:
                self._capture = "room_title"
            elif "room_number" in cls:
                self._capture = "room_number"
            elif "spec-time" in cls:
                self._capture = "spec_time"
            elif "spec-area" in cls:
                self._capture = "spec_area"
            elif "spec-madori" in cls:
                self._capture = "spec_madori"
            elif "year" in cls.split():
                self._capture = "year"

        if tag == "h3" and "post-price" in cls:
            self._capture = "price"

    def handle_endtag(self, tag):
        if not self._in_post:
            return

        if tag == "div":
            self._depth -= 1
            if self._depth <= 0:
                # End of the post block — finalize and save
                if self._current is not None:
                    self.properties.append(self._current)
                self._in_post = False
                self._current = None
                return

        # Stop capturing after the closing tag
        if tag in ("span", "h3") and self._capture is not None:
            self._capture = None

    def handle_data(self, data):
        if not self._in_post or self._current is None or self._capture is None:
            return

        text = data.strip()
        if not text:
            return

        if self._capture == "room_title":
            self._current["property_name"] = text
            # The title often starts with the station name, e.g. "雑色 ファーマーズ・メゾネット"
            # Try to extract station as the first token before a space
            parts = text.split(None, 1)
            if parts:
                self._current["nearest_station"] = parts[0]

        elif self._capture == "room_number":
            # Room number can hint at the floor (e.g. "302" -> 3F)
            room_num = text.strip()
            m = re.match(r"^(\d+)", room_num)
            if m:
                num_str = m.group(1)
                if len(num_str) >= 3:
                    # First digit(s) minus last two = floor
                    floor = num_str[:-2]
                    if floor and int(floor) > 0:
                        self._current["floor_info"] = f"{int(floor)}階"
                elif len(num_str) <= 2:
                    # Could be the floor directly or just a unit number
                    pass

        elif self._capture == "price":
            # Format: "147,000円 / 5,000円" or "-円 / -円"
            self._parse_price(text)

        elif self._capture == "spec_time":
            # "徒歩7分"
            m = re.search(r"(\d+)", text)
            if m:
                self._current["walk_minutes"] = int(m.group(1))
            else:
                self._current["walk_minutes"] = text

        elif self._capture == "spec_area":
            # "52.17㎡"
            m = re.search(r"([\d.]+)", text)
            if m:
                self._current["area_sqm"] = float(m.group(1))
            else:
                self._current["area_sqm"] = text

        elif self._capture == "spec_madori":
            self._current["floor_plan"] = text

        elif self._capture == "year":
            self._current["building_year_month"] = text

    def _parse_price(self, text):
        """Parse '147,000円 / 5,000円' into rent and management_fee."""
        parts = text.split("/")
        if len(parts) >= 1:
            rent_str = parts[0].strip()
            m = re.search(r"([\d,]+)", rent_str)
            if m:
                self._current["rent"] = int(m.group(1).replace(",", ""))
            else:
                self._current["rent"] = None  # e.g. "-円"
        if len(parts) >= 2:
            mgmt_str = parts[1].strip()
            m = re.search(r"([\d,]+)", mgmt_str)
            if m:
                self._current["management_fee"] = int(m.group(1).replace(",", ""))
            else:
                self._current["management_fee"] = None


class _RStoreNextPageParser(HTMLParser):
    """Extracts the 'next page' URL from pagination."""

    def __init__(self):
        super().__init__()
        self.next_url = None

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")

        # Method 1: <a class="link link-next" href="...">次へ</a>
        if tag == "a" and "link-next" in cls:
            href = attrs_dict.get("href", "").strip()
            if href:
                if href.startswith("/"):
                    self.next_url = BASE_URL + href
                else:
                    self.next_url = href

        # Method 2 (fallback): <link rel="next" href="...">
        if tag == "link" and attrs_dict.get("rel") == "next" and self.next_url is None:
            href = attrs_dict.get("href", "").strip()
            if href:
                if href.startswith("/"):
                    self.next_url = BASE_URL + href
                else:
                    self.next_url = href


def parse_rstore(html_str):
    """
    Parse an R-STORE search results HTML page and extract property listings.

    Args:
        html_str: Raw HTML string of the search results page.

    Returns:
        List of dicts, each containing:
            - property_name (str|None): 物件名 (title, often prefixed with station)
            - rent (int|None): 家賃 in yen
            - management_fee (int|None): 管理費 in yen
            - floor_plan (str|None): 間取り (e.g. "2LDK")
            - area_sqm (float|None): 面積 in square meters
            - railway_line (str|None): 路線名 (not available on listing page)
            - nearest_station (str|None): 最寄駅 (extracted from title prefix)
            - walk_minutes (int|None): 徒歩分数
            - address (str|None): 住所 (not available on listing page)
            - building_year_month (str|None): 築年月 (e.g. "2017年02月")
            - floor_info (str|None): 階数 (inferred from room number)
            - pet_conditions (str|None): ペット条件 (not available on listing page)
            - detail_url (str|None): 物件詳細URL
    """
    parser = _RStoreListingParser()
    parser.feed(html_str)
    return parser.properties


def get_next_page_url_rstore(html_str):
    """
    Extract the next-page URL from an R-STORE search results page.

    Args:
        html_str: Raw HTML string of the search results page.

    Returns:
        Absolute URL string for the next page, or None if there is no next page.
    """
    parser = _RStoreNextPageParser()
    parser.feed(html_str)
    return parser.next_url


if __name__ == "__main__":
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/rental_html/rstore_p1.html"
    with open(path, encoding="utf-8") as f:
        html = f.read()

    props = parse_rstore(html)
    print(f"Found {len(props)} properties")
    for p in props[:3]:
        print(json.dumps(p, ensure_ascii=False, indent=2))
    print("...")

    nxt = get_next_page_url_rstore(html)
    print(f"Next page URL: {nxt}")
