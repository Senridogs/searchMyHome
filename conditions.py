"""Search conditions from マンションノート, applied to every scraped listing.

The numbers and the extra stations come from data/settings.json, which the
user changes from LINE (see settings.py). Missing rent/area/walk/age values
pass: listing pages often omit them, and the site search already filters.
"""

import re
import unicodedata
from datetime import date

from settings import load as load_settings

SETTINGS = load_settings()
MAX_TOTAL_RENT = SETTINGS["max_rent"]  # 賃料+管理費
MIN_AREA_SQM = SETTINGS["min_area"]
MAX_WALK_MIN = SETTINGS["max_walk"]
MAX_AGE_YEARS = SETTINGS["max_age"]
MIN_LDK_ROOMS = SETTINGS["min_rooms"]  # 2 = 2LDK / 3LDK / 4LDK以上

# 住めたら理想的なエリア
IDEAL_STATIONS = {
    "大岡山", "三鷹台", "学芸大学", "鷺沼", "元住吉", "祖師ヶ谷大蔵", "青葉台", "市が尾",
    "宮崎台", "あざみ野", "梶が谷", "新百合ヶ丘", "平和台", "狛江", "荻窪", "菊名",
    "南阿佐ケ谷", "地下鉄成増", "成増", "藤が丘", "仙川", "下赤塚", "地下鉄赤塚",
    "つつじヶ丘", "光が丘", "宮前平", "大倉山", "石神井公園", "千歳烏山", "永福町",
    "浜田山", "西小山", "成城学園前", "経堂", "千歳船橋", "富士見ヶ丘", "都立大学",
    "新中野", "東高円寺", "二子新地", "新高円寺", "多摩川", "小竹向原", "富士見台",
    "高井戸", "下丸子", "氷川台", "西太子堂", "久我山", "江田", "西永福", "武蔵新田",
}
IDEAL_AREAS = {"大田区", "練馬区", "中野区", "杉並区"}

# 住みたいエリア
WANT_STATIONS = {
    "等々力", "西荻窪", "井の頭公園", "たまプラーザ", "尾山台", "日吉", "和光市", "用賀",
    "調布", "日吉本町", "大泉学園", "志木", "朝霞", "朝霞台", "桜新町", "練馬高野台",
    "津田山", "東長崎", "駒沢大学", "千川", "要町", "南千住",
}
WANT_AREAS = {"北区"}

# できれば避けたい + 絶対避けたい (板橋区 was listed by mistake and is allowed)
AVOID_STATIONS = {
    "鴨居", "志村三丁目", "鶴川", "宿河原", "新板橋", "希望ヶ丘", "東山田", "鈴木町",
    "和泉多摩川", "田奈", "緑園都市", "五月台", "中山", "立場", "金沢文庫",
}
AVOID_AREAS = {"江戸川区", "足立区", "荒川区", "葛飾区", "江東区", "川崎市川崎区", "市川市"}

# Outside the 23 wards only the listed stations are within commuting range
TOKYO_23_WARDS = {
    "千代田区", "中央区", "港区", "新宿区", "文京区", "台東区", "墨田区", "江東区",
    "品川区", "目黒区", "大田区", "世田谷区", "渋谷区", "中野区", "杉並区", "豊島区",
    "北区", "荒川区", "板橋区", "練馬区", "足立区", "葛飾区", "江戸川区",
}

_KANA_VARIANTS = str.maketrans({"ヶ": "ケ", "ヵ": "ケ", "が": "ケ", "ガ": "ケ"})


def station_key(name) -> str:
    """'小田急線/千歳船橋駅', 'つつじヶ丘（東京）駅', '【猫OK】経堂駅' -> comparable name."""
    s = unicodedata.normalize("NFKC", str(name or ""))
    s = re.sub(r"\(.*?\)", "", s)
    parts = [x for x in re.split(r"[/|【】!・\s]", s) if x]
    s = parts[-1] if parts else ""
    s = re.sub(r"駅$", "", s)
    s = re.sub(r"^.+?[線区](?=.)", "", s)  # '京王線八幡山', '世田谷区経堂'
    return s.translate(_KANA_VARIANTS)


def municipality(address) -> str:
    a = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(address or "")))
    a = re.sub(r"^(東京都|神奈川県|埼玉県|千葉県)", "", a)
    m = re.match(r"(.+?市.+?区|.+?区|.+?市|.+?[町村])", a)
    return m.group(1) if m else ""


def _keys(stations):
    return {station_key(s) for s in stations}


# Stations or municipalities the user added / excluded from LINE override the lists above
_MUNI = re.compile(r"[区市町村]$")
_ADDED = set(SETTINGS["add_stations"])
_EXCLUDED = set(SETTINGS["avoid_stations"])
_IDEAL = _keys(IDEAL_STATIONS | _ADDED) - _keys(_EXCLUDED)
_WANT = _keys(WANT_STATIONS) - _keys(_EXCLUDED)
_AVOID = _keys(AVOID_STATIONS | _EXCLUDED) - _keys(_ADDED)
IDEAL_AREAS = (IDEAL_AREAS | {a for a in _ADDED if _MUNI.search(a)}) - _EXCLUDED
WANT_AREAS = WANT_AREAS - _EXCLUDED
AVOID_AREAS = (AVOID_AREAS | {a for a in _EXCLUDED if _MUNI.search(a)}) - _ADDED


def yen(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = unicodedata.normalize("NFKC", str(value)).replace(",", "")
    m = re.search(r"([\d.]+)万(\d+)?", s)
    if m:
        return int(float(m.group(1)) * 10_000) + int(m.group(2) or 0)
    m = re.search(r"\d+", s)
    return int(m.group()) if m else None


def number(value):
    m = re.search(r"\d+(?:\.\d+)?", unicodedata.normalize("NFKC", str(value or "")))
    return float(m.group()) if m else None


def building_age(value):
    s = unicodedata.normalize("NFKC", str(value or ""))
    m = re.search(r"築(\d+)年", s)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{4})年", s)
    if m:
        return date.today().year - int(m.group(1))
    return 0 if "新築" in s else None


def _plan_ok(p):
    """Layout is the core condition, so an unknown layout does not match.

    Falls back to the title for blog-style sources with no layout field.
    """
    text = p.get("floor_plan") or p.get("property_name") or ""
    m = re.search(r"(\d+)\s*S?LDK", unicodedata.normalize("NFKC", str(text)).upper())
    return bool(m) and int(m.group(1)) >= MIN_LDK_ROOMS


def area_preference(p, area_scoped=True):
    """Return '理想' / '住みたい' / '' for an in-scope listing, or None if excluded.

    area_scoped=False is for sources whose search isn't limited to our
    municipalities; they need a recognised 23-ward address to count as in scope.
    """
    station = station_key(p.get("nearest_station"))
    muni = municipality(p.get("address"))
    if station in _AVOID or muni in _EXCLUDED:  # an area excluded from LINE beats a liked station
        return None
    if station in _IDEAL or muni in IDEAL_AREAS:
        return "理想"
    if station in _WANT or muni in WANT_AREAS:
        return "住みたい"
    if muni in AVOID_AREAS:
        return None
    if muni and muni not in TOKYO_23_WARDS:
        return None
    if not muni and not area_scoped:
        return None
    return ""


def unmet_conditions(p, area_scoped=True) -> list[str]:
    """Names of the conditions this listing fails (empty list = matches)."""
    failed = []
    rent = yen(p.get("rent"))
    if rent is not None and rent + (yen(p.get("management_fee")) or 0) > MAX_TOTAL_RENT:
        failed.append("賃料")
    if not _plan_ok(p):
        failed.append("間取り")
    walk = number(p.get("walk_minutes"))
    if walk is not None and walk > MAX_WALK_MIN:
        failed.append("駅徒歩")
    area = number(p.get("area_sqm") or p.get("area"))
    if area is not None and area < MIN_AREA_SQM:
        failed.append("専有面積")
    age = building_age(p.get("building_year_month"))
    if age is not None and age > MAX_AGE_YEARS:
        failed.append("築年数")
    structure = unicodedata.normalize("NFKC", str(p.get("structure") or "")).upper()
    if structure and not re.search(r"鉄|RC", structure):  # 鉄筋系 (RC/SRC) か 鉄骨系
        failed.append("構造")
    if area_preference(p, area_scoped) is None:
        failed.append("エリア")
    return failed
