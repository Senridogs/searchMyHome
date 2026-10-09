"""Parser for agency sites on the いえらぶ (ielove) platform, e.g. tob-home.com.

List pages are server-rendered: one ``div.list_section`` per building with a
room table (``tr[name=<room id>]``). Links are site-relative, so the site's own
domain is read from the page's canonical/og:url.
"""

import html
import re
from urllib.parse import quote, urljoin


def _text(fragment: str, sep: str = " ") -> str:
    text = html.unescape(re.sub(r"<[^>]+>", sep, fragment))
    return re.sub(r"\s+", sep, text).strip()


def _compact(fragment: str) -> str:
    """Text with all whitespace removed (addresses, prices, station names)."""
    return _text(fragment, "")


def _site_root(page: str) -> str:
    m = re.search(r'<(?:link rel="canonical"|meta property="og:url")[^>]*(?:href|content)="(https?://[^/"]+)', page)
    return m.group(1) if m else ""


def _absolute(root: str, href: str) -> str:
    return urljoin(root, quote(html.unescape(href), safe="/%?=&:"))


def parse_ielove(page: str) -> list[dict]:
    root = _site_root(page)
    summary = _text(page.split('class="list_area"', 1)[0][-6000:])
    pet = "ペット相談" if re.search(r"設備条件.{0,200}ペット相談", summary) else ""

    results = []
    for block in re.split(r'<div class="list_section"', page)[1:]:
        name_m = re.search(r'<h2 class="bknttl">\s*<a[^>]*>(.*?)</a>', block, re.DOTALL)
        address_m = re.search(r'<li class="adress">(.*?)</li>', block, re.DOTALL)
        address = re.sub(r"^住所", "", _compact(address_m.group(1))) if address_m else ""

        # Several stations are listed and the first is not always the closest
        stations = []
        access_m = re.search(r"<dt>交通</dt>\s*<dd>(.*?)</dd>", block, re.DOTALL)
        for item in re.findall(r"<li>(.*?)</li>", access_m.group(1) if access_m else "", re.DOTALL):
            m = re.match(r"(.*?)「(.*?)」駅徒歩(\d+)分", _compact(item))
            if m:
                stations.append((int(m.group(3)), m.group(1), m.group(2)))
        walk, line, station = min(stations) if stations else ("", "", "")

        def spec(label):
            m = re.search(r"<span[^>]*>" + label + r"</span>(.*?)</li>", block, re.DOTALL)
            return _text(m.group(1)) if m else ""

        floors = spec("階数")
        for _, row in re.findall(r'<tr name="(\d+)"\s*>(.*?)</tr>', block, re.DOTALL):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
            if len(cells) < 8:
                continue
            detail_m = re.search(r'href="([^"]+)"', cells[7])
            results.append({
                "property_name": _text(name_m.group(1)) if name_m else "",
                "rent": _compact(cells[1]),
                "management_fee": _compact(cells[2]),
                "floor_plan": _compact(cells[5]),
                "area_sqm": _compact(cells[6]),
                "railway_line": line,
                "nearest_station": station,
                "walk_minutes": str(walk),
                "address": address,
                "building_year_month": spec("築年"),
                "floor_info": " / ".join(filter(None, [_text(cells[0]), floors])),
                "structure": spec("構造"),
                "pet_conditions": pet,
                "detail_url": _absolute(root, detail_m.group(1)) if detail_m else "",
            })
    return results


def get_next_page_url_ielove(page: str, current_url: str | None = None) -> str | None:
    m = re.search(r'<li class="go"><a href="([^"]+)">次へ', page)
    if not m:
        return None
    return _absolute(_site_root(page) or (current_url or ""), m.group(1))
