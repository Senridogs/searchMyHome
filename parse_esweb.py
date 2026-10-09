"""Agency sites on the es-web platform (*.re-ws.jp etc.), e.g. レントハウス仙川店.

robots.txt on these sites disallows /wp-json/, which is the only source of
their list pages, so listings are read from sitemap-advertisement.xml plus
the individual /rent/<id>/ detail pages (allowed, Crawl-delay: 5).
"""

import html
import re
import unicodedata


def _clean(fragment: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", text).strip()


def sitemap_rent_urls(xml: str) -> list[str]:
    """Rent detail URLs, most recently modified first."""
    entries = re.findall(
        r"<loc>([^<]+/rent/\d+/)</loc>\s*(?:<lastmod>([^<]+)</lastmod>)?", xml
    )
    return [url for url, _ in sorted(entries, key=lambda e: e[1], reverse=True)]


def parse_esweb_detail(page: str, url: str) -> dict | None:
    """One rental from a detail page, or None unless pets are allowed."""
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.DOTALL)
    # The page repeats several fields in a second, cleaner table; keep the last value
    fields = {
        _clean(k): _clean(v)
        for k, v in re.findall(r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", body, re.DOTALL)
    }
    conditions = " ".join(fields.get(k, "") for k in ("入居条件", "主要設備"))
    if not re.search(r"ペット(相談|可)", conditions):
        return None

    stations = []
    for line, station, walk in re.findall(r"(\S+)\s+(\S+?)駅\s*徒歩(\d+)分", fields.get("交通", "")):
        stations.append((int(walk), line, re.sub(r"（.*?）|\(.*?\)", "", station)))
    walk, line, station = min(stations) if stations else ("", "", "")

    fees = re.findall(r"[\d,]+(?=円)", fields.get("管理費/共益費/雑費", ""))
    fee_total = sum(int(f.replace(",", "")) for f in fees)

    return {
        "property_name": fields.get("物件名", ""),
        "rent": re.sub(r"\s+", "", fields.get("賃料", "")),
        "management_fee": f"{fee_total}円" if fees else "",
        "floor_plan": re.split(r"[（(]", fields.get("間取り", ""))[0].strip(),
        "area_sqm": fields.get("面積（専有/延床/土地）", "").split("/")[0].strip(),
        "railway_line": line,
        "nearest_station": station,
        "walk_minutes": str(walk),
        "address": re.sub(r"\s+|（周辺地図）", "", fields.get("所在地", "")),
        "building_year_month": re.split(r"[（(]", fields.get("築年月", ""))[0].strip(),
        "floor_info": fields.get("所在階/階数", ""),
        "structure": fields.get("構造", ""),
        "pet_conditions": "ペット相談可",
        "equipment": unicodedata.normalize(
            "NFKC", " ".join(fields.get(k, "") for k in ("主要設備", "設備"))
        ),
        "detail_url": url,
    }
