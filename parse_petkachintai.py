"""
Parser for petkachintai.net listing pages.
Extracts rental property data from blog-style listing HTML.
Uses only Python stdlib (html.parser, re, json).
"""

import re
from html.parser import HTMLParser


class _PetkachintaiListParser(HTMLParser):
    """Parses the blog listing page and extracts property card data."""

    def __init__(self):
        super().__init__()
        self.properties = []
        self._current = None
        # State tracking
        self._in_item = False
        self._in_title = False
        self._in_excerpt = False
        self._title_text = ""
        self._excerpt_text = ""
        self._link_href = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")

        # Detect <li class="p-postList__item">
        if tag == "li" and "p-postList__item" in cls:
            self._in_item = True
            self._current = {}
            self._title_text = ""
            self._excerpt_text = ""
            self._link_href = ""

        if not self._in_item:
            return

        # Detect <a href="..." class="p-postList__link">
        if tag == "a" and "p-postList__link" in cls:
            self._link_href = attrs_dict.get("href", "")

        # Detect <h2 class="p-postList__title">
        if tag == "h2" and "p-postList__title" in cls:
            self._in_title = True
            self._title_text = ""

        # Detect <div class="p-postList__excerpt">
        if tag == "div" and "p-postList__excerpt" in cls:
            self._in_excerpt = True
            self._excerpt_text = ""

    def handle_endtag(self, tag):
        if tag == "h2" and self._in_title:
            self._in_title = False

        if tag == "div" and self._in_excerpt:
            self._in_excerpt = False

        if tag == "li" and self._in_item:
            self._in_item = False
            if self._link_href:
                self._current["detail_url"] = self._link_href
                self._current["title"] = self._title_text.strip()
                self._current["excerpt"] = self._excerpt_text.strip()
                self.properties.append(self._current)
            self._current = None

    def handle_data(self, data):
        if self._in_title:
            self._title_text += data
        if self._in_excerpt:
            self._excerpt_text += data

    def handle_entityref(self, name):
        char = {"nbsp": " ", "amp": "&", "lt": "<", "gt": ">", "quot": '"'}.get(name, "")
        if self._in_title:
            self._title_text += char
        if self._in_excerpt:
            self._excerpt_text += char


class _PaginationParser(HTMLParser):
    """Extracts the next page URL from pagination div."""

    def __init__(self):
        super().__init__()
        self._in_pagination = False
        self._found_current = False
        self.next_url = None

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")

        if tag == "div" and "c-pagination" in cls:
            self._in_pagination = True

        if not self._in_pagination:
            return

        # <span class="page-numbers current"> marks current page
        if tag == "span" and "current" in cls and "page-numbers" in cls:
            self._found_current = True

        # First <a class="page-numbers"> after current is the next page
        if tag == "a" and "page-numbers" in cls and self._found_current and self.next_url is None:
            self.next_url = attrs_dict.get("href")

    def handle_endtag(self, tag):
        if tag == "div" and self._in_pagination:
            self._in_pagination = False


def _clean(text):
    """Normalize whitespace and special chars in extracted text."""
    if not text:
        return ""
    # Replace fullwidth chars, normalize whitespace
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_rent(excerpt):
    """Extract rent (賃料) from excerpt text. Returns string like '110,000円' or ''."""
    m = re.search(r"賃料／共益費\s*(\d[\d,]+)円", excerpt)
    if m:
        return m.group(1) + "円"
    m = re.search(r"賃料[：/／]?\s*(\d[\d,]+)円", excerpt)
    if m:
        return m.group(1) + "円"
    return ""


def _extract_management_fee(excerpt):
    """Extract management fee (管理費/共益費) from excerpt."""
    m = re.search(r"賃料／共益費\s*\d[\d,]+円[／/]\s*([^\s・]+?)(?:\s*・|$)", excerpt)
    if m:
        val = m.group(1).strip()
        return val
    return ""


def _extract_floor_plan(excerpt):
    """Extract floor plan (間取り) from excerpt."""
    # Pattern after 間取り／専有面積／階数
    m = re.search(r"間取り／専有面積／階数\s*[：:]?\s*(?:・間取り[：:]?)?\s*(\d?\w*LDK\+?S?(?:（納戸）)?|\d?\w*DK|\d?\w*K|\d?\w*R)\b", excerpt)
    if m:
        return m.group(1)
    # Try after just 間取り：
    m = re.search(r"間取り[：:]\s*(\d?\w*LDK\+?S?(?:（納戸）)?|\d?\w*DK|\d?\w*K|\d?\w*R)", excerpt)
    if m:
        return m.group(1)
    return ""


def _extract_area(excerpt):
    """Extract area in sqm (面積/専有面積) from excerpt."""
    # Match patterns like 25.46㎡ or 25㎡
    m = re.search(r"専有面積[：:]?\s*(\d+\.?\d*)㎡", excerpt)
    if m:
        return m.group(1) + "㎡"
    # After 間取り／専有面積／階数 ... look for ㎡
    m = re.search(r"間取り／専有面積／階数\s*.+?(\d+\.?\d*)㎡", excerpt)
    if m:
        return m.group(1) + "㎡"
    return ""


def _extract_floor(excerpt):
    """Extract floor info (階数) from excerpt."""
    # Look after area ㎡ for floor info like ／2階 or ／4階（4階建）
    m = re.search(r"㎡(?:（壁芯）)?[／/]\s*(.+?)(?:\s*・|\s*最寄)", excerpt)
    if m:
        return m.group(1).strip().rstrip("・ ")
    # Truncated: ends with 階数：N...  or just N階...
    m = re.search(r"㎡(?:（壁芯）)?[／/]\s*(.+?階[^・]*?)(?:\.{3}|…|\s*$)", excerpt)
    if m:
        return m.group(1).strip().rstrip("・ .")
    # Pattern: 階数：2...
    m = re.search(r"階数[：:]\s*(\d+)", excerpt)
    if m:
        return m.group(1) + "階"
    return ""


def _extract_station_info(excerpt):
    """Extract railway line, station name, and walk minutes."""
    line_name = ""
    station = ""
    walk_min = ""

    # Pattern: 最寄り<line>「<station>」駅 徒歩N分
    m = re.search(r"最寄り\s*(.+?)「(.+?)」\s*(?:駅)?\s*(?:徒歩\s*(\d+)\s*分)?", excerpt)
    if m:
        line_name = m.group(1).strip()
        station = m.group(2).strip()
        if m.group(3):
            walk_min = m.group(3)
        return line_name, station, walk_min

    # Pattern from title: <station>駅 徒歩N分 or <station>駅徒歩N分
    # Try excerpt first for 最寄り pattern without quotes
    m = re.search(r"最寄り\s*(.+?駅)\s*(?:徒歩\s*(\d+)\s*分)?", excerpt)
    if m:
        station_full = m.group(1).strip()
        if m.group(2):
            walk_min = m.group(2)
        return line_name, station_full, walk_min

    return line_name, station, walk_min


def _extract_station_from_title(title):
    """Fallback: extract station and walk minutes from the blog post title."""
    station = ""
    walk_min = ""
    line_name = ""

    # Pattern: <station>駅 徒歩N分 or <station>駅徒歩N分
    m = re.search(r"(.+?駅)\s*徒歩\s*(\d+)\s*分", title)
    if m:
        station_part = m.group(1).strip()
        walk_min = m.group(2)
        # Try to separate line name from station
        # e.g., "東急目黒線奥沢駅" -> line="東急目黒線", station="奥沢"
        lm = re.match(r"^(.+?線)(.+)", station_part)
        if lm:
            line_name = lm.group(1)
            station = lm.group(2).rstrip("駅") + "駅"
        else:
            station = station_part
        return line_name, station, walk_min

    return line_name, station, walk_min


def _extract_pet_conditions(title, excerpt):
    """Extract pet conditions from title and excerpt."""
    # Combine title and excerpt for best chance
    combined = title + " " + excerpt

    # Look for pet-related patterns (order matters: specific first)
    patterns = [
        # e.g., "ペット2匹可" (stop before unrelated info)
        r"(ペット\d匹可)",
        # e.g., "小型犬・猫2匹可、中型犬1匹相談"
        r"((?:小型|中型|大型)犬[^｜|\s]{0,40}?(?:可|OK|相談可?))",
        # e.g., "犬猫多頭OK" or "犬・猫・多頭飼い要相談"
        r"(犬[・]?猫[・]?多頭[^｜|\s]{0,20}?(?:可|OK|相談)?)",
        # e.g., "ペット可（犬猫・大型相談・複数匹相談）"
        r"(ペット可(?:（[^）]+）)?)",
        # e.g., "ペット（相談可）"
        r"(ペット（[^）]+）)",
        # e.g., "大型犬等相談可"
        r"(大型犬等相談可)",
        # e.g., "中型犬・猫OK｜2匹まで"
        r"((?:中型犬|小型犬)[^｜|\s]{0,30}?(?:まで|可|OK))",
        # e.g., "複数ペット可"
        r"(複数ペット可)",
        # e.g., "ペット相談可" or "ペット飼育可"
        r"(ペット(?:相談可|飼育可|相談))",
    ]

    for pat in patterns:
        m = re.search(pat, combined)
        if m:
            return m.group(1).strip()

    # Generic fallback
    if "ペット可" in combined:
        return "ペット可"

    return ""


def _extract_address_from_title(title):
    """Try to extract address hints from title (区/市/町)."""
    # Look for patterns like 【世田谷区弦巻】 or 【府中市天神町】
    # Only match brackets that contain an address-like pattern (区/市 + location)
    m = re.search(r"[【\[]((?:\S+?[区市])\S{1,10}(?:丁目)?)[】\]]", title)
    if m:
        addr = m.group(1).strip()
        # Filter out non-address matches (e.g. station names with 駅)
        if "駅" not in addr and "分" not in addr:
            return addr

    # Look for 区X or 市X patterns in the title (not inside brackets)
    m = re.search(r"((?:世田谷|目黒|渋谷|新宿|品川|大田|杉並|中野|板橋|練馬|豊島|北|荒川|台東|墨田|江東|足立|葛飾|江戸川|千代田|中央|港|文京)区\S{1,10})", title)
    if m:
        addr = m.group(1).strip()
        # Remove trailing non-address chars
        addr = re.sub(r"[】\]｜|].*$", "", addr)
        if addr:
            return addr

    # City-level: e.g., 府中市天神町, 調布市国領町, 多摩市連光寺
    m = re.search(r"(\S+?市\S{1,10}(?:丁目)?)", title)
    if m:
        addr = m.group(1).strip()
        addr = re.sub(r"[】\]｜|].*$", "", addr)
        if "駅" not in addr and "分" not in addr and len(addr) > 3:
            return addr

    return ""


def parse_petkachintai(html_str):
    """
    Parse petkachintai.net listing HTML and extract property data.

    Args:
        html_str: HTML string of a listing page.

    Returns:
        List of dicts, each with keys:
            property_name, rent, management_fee, floor_plan, area,
            railway_line, nearest_station, walk_minutes, address,
            building_year_month, floor_info, pet_conditions, detail_url
    """
    parser = _PetkachintaiListParser()
    parser.feed(html_str)

    results = []
    for prop in parser.properties:
        title = _clean(prop.get("title", ""))
        excerpt = _clean(prop.get("excerpt", ""))
        detail_url = prop.get("detail_url", "")

        rent = _extract_rent(excerpt)
        mgmt_fee = _extract_management_fee(excerpt)
        floor_plan = _extract_floor_plan(excerpt)
        area = _extract_area(excerpt)
        floor_info = _extract_floor(excerpt)

        # Station info: try excerpt first, fall back to title
        line_name, station, walk_min = _extract_station_info(excerpt)
        if not station:
            line_name, station, walk_min = _extract_station_from_title(title)

        pet_cond = _extract_pet_conditions(title, excerpt)
        address = _extract_address_from_title(title)

        results.append({
            "property_name": title,  # Blog title serves as property name
            "rent": rent,
            "management_fee": mgmt_fee,
            "floor_plan": floor_plan,
            "area": area,
            "railway_line": line_name,
            "nearest_station": station,
            "walk_minutes": walk_min,
            "address": address,
            "building_year_month": "",  # Not available on listing page (detail page only)
            "floor_info": floor_info,
            "pet_conditions": pet_cond,
            "detail_url": detail_url,
        })

    return results


def get_next_page_url_petkachintai(html_str):
    """
    Extract the next page URL from pagination on a petkachintai.net listing page.

    Args:
        html_str: HTML string of a listing page.

    Returns:
        Next page URL as a string, or None if there is no next page.
    """
    parser = _PaginationParser()
    parser.feed(html_str)
    return parser.next_url


if __name__ == "__main__":
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/rental_html/petkachintai_p1.html"
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    props = parse_petkachintai(html)
    print(f"Found {len(props)} properties\n")
    for i, p in enumerate(props, 1):
        print(f"--- Property {i} ---")
        for k, v in p.items():
            print(f"  {k}: {v}")
        print()

    nxt = get_next_page_url_petkachintai(html)
    print(f"Next page URL: {nxt}")
