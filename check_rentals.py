#!/usr/bin/env python3
"""
Rental listing checker - fetches properties from 7 sites, saves data,
and reports new listings compared to previous run.

Usage:
    python3 check_rentals.py

Data files:
    data/latest.json   - current run results
    data/previous.json - previous run results (for diff)
"""

import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parse_chintai_ex import parse_chintai_ex, get_next_page_url_chintai_ex
from parse_smocca import parse_smocca, get_next_page_url_smocca
from parse_petadpark import parse_petadpark, get_next_page_url_petadpark
from parse_airdoor import parse_airdoor, get_next_page_url_airdoor
from parse_rstore import parse_rstore, get_next_page_url_rstore
from parse_pethomeweb import parse_pethomeweb, get_next_page_url_pethomeweb
from parse_petkachintai import parse_petkachintai, get_next_page_url_petkachintai
from parse_esweb import rest_url, parse_esweb, get_next_page_url_esweb
from parse_ielove import parse_ielove, get_next_page_url_ielove
from parse_suumo import SUUMO_URL, SUUMO_AREA_URLS, parse_suumo, get_next_page_url_suumo
from parse_homes import HOMES_URL, parse_homes, get_next_page_url_homes
from parse_athome import ATHOME_URL, parse_athome, get_next_page_url_athome
from parse_eheya import EHEYA_URL, parse_eheya, get_next_page_url_eheya
from parse_pitat import PITAT_URL, parse_pitat, get_next_page_url_pitat
from parse_hatomark import HATOMARK_URL, parse_hatomark, get_next_page_url_hatomark
from parse_tohto import TOHTO_URL, parse_tohto, get_next_page_url_tohto
from parse_door_ac import parse_door_ac, get_next_page_url_door_ac
from conditions import area_preference, unmet_conditions, yen
from ranking import listing_key, rule_score

HEADERS = [
    "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "-H", "Accept-Language: ja,en-US;q=0.9,en;q=0.8",
]

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Search URLs for each site
URLS = {
    "賃貸EX": "https://chintai-ex.jp/search/detail?city_code%5B%5D=13101&city_code%5B%5D=13102&city_code%5B%5D=13103&city_code%5B%5D=13104&city_code%5B%5D=13105&city_code%5B%5D=13106&city_code%5B%5D=13107&city_code%5B%5D=13109&city_code%5B%5D=13110&city_code%5B%5D=13111&city_code%5B%5D=13112&city_code%5B%5D=13113&city_code%5B%5D=13114&city_code%5B%5D=13115&city_code%5B%5D=13116&city_code%5B%5D=13117&city_code%5B%5D=13118&city_code%5B%5D=13119&city_code%5B%5D=13120&city_code%5B%5D=13204&city_code%5B%5D=13208&city_code%5B%5D=13219&cond%5Barea%5D%5Bmin%5D=40&cond%5Bbaths%5D%5B%5D=1&cond%5Bchinryou%5D%5Binclude_kanrihi%5D=true&cond%5Bchinryou%5D%5Bmax%5D=200000&cond%5Bconditions%5D%5B%5D=64&cond%5Bkitchens%5D%5B%5D=16&cond%5Bother_conditions%5D%5B%5D=2&cond%5Bplans%5D%5Bmax%5D=44&cond%5Bplans%5D%5Bmin%5D=24&cond%5Bwalk_min%5D=15&prefecture_path=tokyo&cond%5Bsort%5D=arrived_at+desc",
    "賃貸EX(神奈川)": "https://chintai-ex.jp/search/detail?city_code%5B%5D=14109&city_code%5B%5D=14117&city_code%5B%5D=14133&city_code%5B%5D=14134&city_code%5B%5D=14136&city_code%5B%5D=14137&cond%5Barea%5D%5Bmin%5D=40&cond%5Bbaths%5D%5B%5D=1&cond%5Bchinryou%5D%5Binclude_kanrihi%5D=true&cond%5Bchinryou%5D%5Bmax%5D=200000&cond%5Bconditions%5D%5B%5D=64&cond%5Bkitchens%5D%5B%5D=16&cond%5Bother_conditions%5D%5B%5D=2&cond%5Bplans%5D%5Bmax%5D=44&cond%5Bplans%5D%5Bmin%5D=24&cond%5Bwalk_min%5D=15&prefecture_path=kanagawa&cond%5Bsort%5D=arrived_at+desc",
    "賃貸EX(埼玉)": "https://chintai-ex.jp/search/detail?city_code%5B%5D=11227&city_code%5B%5D=11228&city_code%5B%5D=11229&city_code%5B%5D=11230&cond%5Barea%5D%5Bmin%5D=40&cond%5Bbaths%5D%5B%5D=1&cond%5Bchinryou%5D%5Binclude_kanrihi%5D=true&cond%5Bchinryou%5D%5Bmax%5D=200000&cond%5Bconditions%5D%5B%5D=64&cond%5Bkitchens%5D%5B%5D=16&cond%5Bother_conditions%5D%5B%5D=2&cond%5Bplans%5D%5Bmax%5D=44&cond%5Bplans%5D%5Bmin%5D=24&cond%5Bwalk_min%5D=15&prefecture_path=saitama&cond%5Bsort%5D=arrived_at+desc",
    "スモッカ": "https://smocca.jp/search/results?city_code%5B%5D=13101&city_code%5B%5D=13102&city_code%5B%5D=13103&city_code%5B%5D=13104&city_code%5B%5D=13105&city_code%5B%5D=13106&city_code%5B%5D=13107&city_code%5B%5D=13109&city_code%5B%5D=13110&city_code%5B%5D=13111&city_code%5B%5D=13112&city_code%5B%5D=13113&city_code%5B%5D=13114&city_code%5B%5D=13115&city_code%5B%5D=13116&city_code%5B%5D=13117&city_code%5B%5D=13118&city_code%5B%5D=13119&city_code%5B%5D=13120&city_code%5B%5D=13204&city_code%5B%5D=13208&city_code%5B%5D=13219&cond%5Barea%5D%5Bmin%5D=40&cond%5Bbaths%5D%5B%5D=1&cond%5Bchinryou%5D%5Binclude_kanrihi%5D=true&cond%5Bchinryou%5D%5Bmax%5D=200000&cond%5Bconditions%5D%5B%5D=64&cond%5Bkitchens%5D%5B%5D=16&cond%5Bother_conditions%5D%5B%5D=2&cond%5Bplans%5D%5Bmax%5D=44&cond%5Bplans%5D%5Bmin%5D=24&cond%5Bstructs%5D%5B%5D=2&cond%5Bstructs%5D%5B%5D=3&cond%5Bwalk_min%5D=15&prefecture_path=tokyo&cond%5Bsort%5D=arrived_at+desc",
    "スモッカ(神奈川)": "https://smocca.jp/search/results?city_code%5B%5D=14109&city_code%5B%5D=14117&city_code%5B%5D=14133&city_code%5B%5D=14134&city_code%5B%5D=14136&city_code%5B%5D=14137&cond%5Barea%5D%5Bmin%5D=40&cond%5Bbaths%5D%5B%5D=1&cond%5Bchinryou%5D%5Binclude_kanrihi%5D=true&cond%5Bchinryou%5D%5Bmax%5D=200000&cond%5Bconditions%5D%5B%5D=64&cond%5Bkitchens%5D%5B%5D=16&cond%5Bother_conditions%5D%5B%5D=2&cond%5Bplans%5D%5Bmax%5D=44&cond%5Bplans%5D%5Bmin%5D=24&cond%5Bstructs%5D%5B%5D=2&cond%5Bstructs%5D%5B%5D=3&cond%5Bwalk_min%5D=15&prefecture_path=kanagawa&cond%5Bsort%5D=arrived_at+desc",
    "スモッカ(埼玉)": "https://smocca.jp/search/results?city_code%5B%5D=11227&city_code%5B%5D=11228&city_code%5B%5D=11229&city_code%5B%5D=11230&cond%5Barea%5D%5Bmin%5D=40&cond%5Bbaths%5D%5B%5D=1&cond%5Bchinryou%5D%5Binclude_kanrihi%5D=true&cond%5Bchinryou%5D%5Bmax%5D=200000&cond%5Bconditions%5D%5B%5D=64&cond%5Bkitchens%5D%5B%5D=16&cond%5Bother_conditions%5D%5B%5D=2&cond%5Bplans%5D%5Bmax%5D=44&cond%5Bplans%5D%5Bmin%5D=24&cond%5Bstructs%5D%5B%5D=2&cond%5Bstructs%5D%5B%5D=3&cond%5Bwalk_min%5D=15&prefecture_path=saitama&cond%5Bsort%5D=arrived_at+desc",
    "ペットアドパーク": "https://www.pet-adpark.jp/es/pref_city_search_list.php?pref=1310_1320&city=1310_1059-1310_1075-1310_1105-1310_1113-1310_1121-1310_1148-1310_1156-1310_1164-1310_1172-1310_1199-1310_1202&tmpl=pet&area=1000&category=chintai&count=30&sortHistory=sort2a&sort=sort8d&bldgType[]=01_03_04&bldgType[]=02&bldgType[]=06&moneyL=&moneyH=190000&kyoekiIncFlg=1&preset_disp=off&spaceL=50&spaceH=&walk=15&tikunensu=&newdate=&begin=0",
    "AirDoor": "https://airdoor.jp/list?jis=13101%2C13102%2C13103%2C13104%2C13105%2C13106%2C13107%2C13109%2C13110%2C13111%2C13112%2C13113%2C13114%2C13115%2C13116%2C13117%2C13118%2C13119%2C13120%2C13204%2C13208%2C13219%2C14109%2C14117%2C14133%2C14134%2C14136%2C14137%2C11227%2C11228%2C11229%2C11230&ur=220000&iaf=1&uf=15&le=40&ua=50&fp=d-2_ldk-3_ldk-4_more&cs=d-1-2&ca=d-10-15-24-43",
    "R-STORE": "https://www.r-store.jp/search?sb_purpose1%5B%5D=R&sb_r_max=220000&sb_price=1&sb_c%5B%5D=13101&sb_c%5B%5D=13102&sb_c%5B%5D=13103&sb_c%5B%5D=13104&sb_c%5B%5D=13105&sb_c%5B%5D=13106&sb_c%5B%5D=13107&sb_c%5B%5D=13109&sb_c%5B%5D=13110&sb_c%5B%5D=13111&sb_c%5B%5D=13112&sb_c%5B%5D=13113&sb_c%5B%5D=13114&sb_c%5B%5D=13115&sb_c%5B%5D=13116&sb_c%5B%5D=13117&sb_c%5B%5D=13118&sb_c%5B%5D=13119&sb_c%5B%5D=13120&sb_c%5B%5D=13204&sb_c%5B%5D=13208&sb_c%5B%5D=13219&sb_walk_from=15&sb_area_up=40&sb_floor_plan%5B%5D=2LDK&sb_floor_plan%5B%5D=2SLDK&sb_floor_plan%5B%5D=3LDK&sb_floor_plan%5B%5D=3SLDK&sb_floor_plan%5B%5D=4LDK&sb_floor_plan%5B%5D=4SLDK&sb_floor_plan%5B%5D=5K%E4%BB%A5%E4%B8%8A&sb_pet%5B%5D=%E5%B0%8F%E5%9E%8B%E7%8A%AC%E5%8F%AF&sb_pet%5B%5D=%E7%8C%AB%E5%8F%AF&sb_get_full1=true",
    "ペットホームウェブ": "https://www.pethomeweb.com/chintai/tokyo/list/?AR2=A2_55yo-A2_54yo-A2_55t2-A2_54li-A2_54r3-A2_55fl-A2_546l-A2_55la-A2_54hv-A2_5568-A2_54dy-A2_53z4-A2_53v1-A2_55q6-A2_55id-A2_5637-A2_54bi-A2_542j-A2_54vg-A2_575r-A2_55yz&SO=1&CH=1-33&CO=1&ME=8-18&EW=15&CN=9&KO=91-92-30-82-12-9-26",
    "ペット可賃貸.net": "https://petkachintai.net/archives/category/pet-friendly-rentals-in-tokyo",
    "SUUMO(重点6駅)": SUUMO_URL,
    **SUUMO_AREA_URLS,
    "HOME'S(重点6駅)": HOMES_URL,
    "アットホーム(重点6駅)": ATHOME_URL,
    "いい部屋ネット(重点6駅)": EHEYA_URL,
    "ピタットハウス(重点6駅)": PITAT_URL,
    "ハトマーク(重点6駅)": HATOMARK_URL,
    "東都": TOHTO_URL,
    "アイホープハウス": "https://www.i-hope-house.co.jp/area_c1/bknshiku_ih13115/?address%5B%5D=13112&address%5B%5D=13115&address%5B%5D=13204&address%5B%5D=13208&pF=0&pC=22&kykn=1&aF=40&wT=15&md%5B%5D=2LDK&md%5B%5D=3LDK&md%5B%5D=4LDK_up&op%5B%5D=option0101&orderby=",
    "TOB": "https://www.tob-home.com/area_c1/bknarea_to13112/?address%5B%5D=13112&address%5B%5D=13115&address%5B%5D=13204&address%5B%5D=13208&pF=0&pC=22&kykn=0&kykn=1&rkn=0&shkn=0&aF=40&aC=0&years=0&wT=15&md%5B%5D=2LDK&md%5B%5D=3LDK&md%5B%5D=4LDK_up&op%5B%5D=option0100&op%5B%5D=option0402&op%5B%5D=option0500&orderby=modified&lmt=50",
    "DOOR賃貸": "https://door.ac/list?utf8=%E2%9C%93&cond%5Bcities%5D%5B%5D=13109&cond%5Bcities%5D%5B%5D=13112&cond%5Bcities%5D%5B%5D=13115&cond%5Bcities%5D%5B%5D=13119&cond%5Bcities%5D%5B%5D=13208&cond%5Bsort%5D=-inquiry_price&cond%5Bfee_min%5D=&cond%5Bfee_max%5D=180000&cond%5Bincluded%5D=1&cond%5Bwalk_time%5D=15&cond%5Bsqmeter_min%5D=50&cond%5Bsqmeter_max%5D=&cond%5Bage_min%5D=&cond%5Bage_max%5D=30&cond%5Bfeatures%5D%5B%5D=7",
}

# Max pages per site
MAX_PAGES = {
    "ペット可賃貸.net": 1,
}

# Sources whose search isn't limited to our municipalities (Tokyo-wide blog)
UNSCOPED_SITES = {"ペット可賃貸.net"}

# Extra headers by URL: スモッカ's load-more API returns 400 without
# X-Requested-With, and sending that header to page 1 drops the load-more link.
EXTRA_HEADERS = {
    "smocca.jp/api/": ["-H", "X-Requested-With: XMLHttpRequest"],
}

# Sites that answer a search with no hits with HTTP 404 instead of an empty list
EMPTY_ON_404 = ("tob-home.com/", "i-hope-house.co.jp/")

# es-web agency sites: feature pages (rs=1 applies the query) whose results come
# from the REST API (see parse_esweb.py). Personal, once-a-day use, so the API
# is read despite robots.txt, keeping the requested 5s Crawl-delay.
# es-web search conditions (rs=1 makes a page apply its query string)
ESWEB_COMMON = (
    "rs=1&price_to=220000&price_include_amount_management_fee=1&occupied_area_from=40.0"
    "&walk_from_station_minutes_to=15&house_plan_summary_code%5B%5D=203&house_plan_summary_code%5B%5D=303"
    "&house_plan_summary_code%5B%5D=403&house_plan_summary_code%5B%5D=599"
    "&structure_summary_code%5B%5D=1&structure_summary_code%5B%5D=2&sub%5B%5D=is_pet_ok"
    "&sub%5B%5D=separate_bath_toilet&sub%5B%5D=has_multiple_gas_stove&sub%5B%5D=has_landry_room"
    "&sort=new_arrival&item_per_page=30"
)
# ワイエス・ホーム: マンション・アパート in 三鷹市 and 杉並区 (city codes without the prefecture part)
YS_AREA = (
    "&boshu_kind_summary_code%5B%5D=1&boshu_kind_summary_code%5B%5D=2&pref=%E6%9D%B1%E4%BA%AC%E9%83%BD"
    "&city%5B%5D=204&city%5B%5D=115&address%5B%5D=%E6%9D%B1%E4%BA%AC%E9%83%BD%E4%B8%89%E9%B7%B9%E5%B8%82"
    "&address%5B%5D=%E6%9D%B1%E4%BA%AC%E9%83%BD%E6%9D%89%E4%B8%A6%E5%8C%BA"
)
ESWEB_SITES = {
    "レントハウス(全店)": f"https://renthouse.re-ws.jp/rent/search/area/pref_13/?{ESWEB_COMMON}&pref=%E6%9D%B1%E4%BA%AC%E9%83%BD&city%5B%5D=112&city%5B%5D=115&city%5B%5D=204&city%5B%5D=208&city%5B%5D=219&address%5B%5D=%E6%9D%B1%E4%BA%AC%E9%83%BD%E4%B8%96%E7%94%B0%E8%B0%B7%E5%8C%BA&address%5B%5D=%E6%9D%B1%E4%BA%AC%E9%83%BD%E6%9D%89%E4%B8%A6%E5%8C%BA&address%5B%5D=%E6%9D%B1%E4%BA%AC%E9%83%BD%E4%B8%89%E9%B7%B9%E5%B8%82&address%5B%5D=%E6%9D%B1%E4%BA%AC%E9%83%BD%E8%AA%BF%E5%B8%83%E5%B8%82&address%5B%5D=%E6%9D%B1%E4%BA%AC%E9%83%BD%E7%8B%9B%E6%B1%9F%E5%B8%82",
    "南陽ハウジング": f"https://2116547.re-ws.jp/rent/search/area/pref_13/?{ESWEB_COMMON}&pref=%E6%9D%B1%E4%BA%AC%E9%83%BD&city%5B%5D=112&city%5B%5D=115&city%5B%5D=204&city%5B%5D=208&city%5B%5D=219&address%5B%5D=%E6%9D%B1%E4%BA%AC%E9%83%BD%E4%B8%96%E7%94%B0%E8%B0%B7%E5%8C%BA&address%5B%5D=%E6%9D%B1%E4%BA%AC%E9%83%BD%E6%9D%89%E4%B8%A6%E5%8C%BA&address%5B%5D=%E6%9D%B1%E4%BA%AC%E9%83%BD%E4%B8%89%E9%B7%B9%E5%B8%82&address%5B%5D=%E6%9D%B1%E4%BA%AC%E9%83%BD%E8%AA%BF%E5%B8%83%E5%B8%82&address%5B%5D=%E6%9D%B1%E4%BA%AC%E9%83%BD%E7%8B%9B%E6%B1%9F%E5%B8%82",
    "リベスト(吉祥寺)": f"https://www.kichijoji-chintai.com/rent/search/area/pref_13/?{ESWEB_COMMON}&pref=%E6%9D%B1%E4%BA%AC%E9%83%BD&city%5B%5D=115&city%5B%5D=203&city%5B%5D=204&address%5B%5D=%E6%9D%B1%E4%BA%AC%E9%83%BD%E6%9D%89%E4%B8%A6%E5%8C%BA&address%5B%5D=%E6%9D%B1%E4%BA%AC%E9%83%BD%E6%AD%A6%E8%94%B5%E9%87%8E%E5%B8%82&address%5B%5D=%E6%9D%B1%E4%BA%AC%E9%83%BD%E4%B8%89%E9%B7%B9%E5%B8%82",
    "ワイエス・ホーム": f"https://www.yshome.jp/feature/2739/?{ESWEB_COMMON}{YS_AREA}",
}

# Seconds between requests to a site (robots.txt Crawl-delay)
CRAWL_DELAY = {
    **{name: 5 for name in ESWEB_SITES},
    "HOME'S(重点6駅)": 1, "アットホーム(重点6駅)": 1, "いい部屋ネット(重点6駅)": 1,
    "ピタットハウス(重点6駅)": 1, "ハトマーク(重点6駅)": 1, "東都": 1,
}


def curl_fetch(url: str, attempts: int = 3) -> str | None:
    """Fetch URL with curl and browser headers. Returns HTML string or None.

    A transfer cut off midway still reports HTTP 200, so curl's exit code is
    checked too; otherwise a truncated page is parsed as if it were complete.
    """
    extra = [h for key, headers in EXTRA_HEADERS.items() if key in url for h in headers]
    if "/wp-json/" in url:  # the es-web REST API returns 500 without a same-site Referer
        extra += ["-H", "Referer: " + re.match(r"https?://[^/]+/", url).group(0)]
    for attempt in range(attempts):
        if attempt:
            time.sleep(5 * attempt)  # connection resets are usually brief
        result = subprocess.run(
            ["curl", "-s", "-g", "--compressed", "--max-time", "60", "-w", "\n%{http_code}",
             *HEADERS, *extra, url],
            capture_output=True, text=True, timeout=90,
        )
        body, _, status = result.stdout.rpartition("\n")
        if result.returncode == 0 and status == "200":
            return body
        if status == "404" and any(key in url for key in EMPTY_ON_404):
            return ""
        print(f"  HTTP {status or '-'} (curl exit {result.returncode}) for {url[:80]}...")
        if status.startswith("4"):
            return None
    return None


def _normalize(s):
    """Normalize text for stable comparison (NFKC, lowercase, strip address details)."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.lower()
    s = re.sub(r"\s+", "", s)
    # Truncate address after 丁目 to ignore room/building number variations
    s = re.sub(r"(丁目).*", r"\1", s)
    return s


def _prop_key(p):
    """Generate a stable identity key for a property.

    Uses name + address + rent + floor_plan to distinguish different
    units in the same building while merging cross-site duplicates.
    """
    name = _normalize(p.get("property_name", ""))
    addr = _normalize(p.get("address", ""))
    rent = re.sub(r"[^\d.]", "", str(p.get("rent", "")))
    plan = _normalize(p.get("floor_plan", ""))
    return f"{name}|{addr}|{rent}|{plan}"


def _room_key(p):
    """Cross-site identity: same town, layout, size and total rent.

    Sites name the same room differently (e.g. "高島平Ⅲ 3階" vs "高島平III"),
    so _prop_key alone would notify one room once per site.
    """
    nfkc = lambda v: unicodedata.normalize("NFKC", str(v or ""))
    addr = re.sub(r"\s+|^(東京都|神奈川県|埼玉県)", "", nfkc(p.get("address")))
    town = re.match(r"\D*", addr).group()
    plan_m = re.match(r"\d+S?(?:LDK|DK|K)|\d+R", nfkc(p.get("floor_plan")).upper())
    area_m = re.search(r"\d+(?:\.\d+)?", nfkc(p.get("area_sqm")))
    rent = yen(p.get("rent"))
    if not (town and plan_m and area_m and rent):
        return None
    total = rent + (yen(p.get("management_fee")) or 0)
    return f"room:{town}|{plan_m.group()}|{round(float(area_m.group()))}|{total}"


def _identity_keys(p):
    return {k for k in (_prop_key(p), _room_key(p)) if k}


def fetch_all_pages(site_name, first_url, parse_fn, next_page_fn, max_pages=30):
    """Fetch all pages for a site, returning combined property list."""
    all_props = []
    url = first_url
    page = 1

    while url and page <= max_pages:
        html = curl_fetch(url)
        if html is None:
            print(f"  {site_name} page {page}: fetch failed")
            break
        props = parse_fn(html)
        all_props.extend(props)
        print(f"  {site_name} page {page}: {len(props)} properties")
        url = next_page_fn(html, url)
        page += 1
        if url:
            time.sleep(CRAWL_DELAY.get(site_name, 0))

    return all_props


def fetch_esweb_site(site_name, page_url):
    """Fetch an es-web feature page, then its results through the REST API."""
    page = curl_fetch(page_url)
    first = rest_url(page) if page else None
    if not first:
        print(f"  {site_name}: 検索ページを読めませんでした")
        return []
    time.sleep(CRAWL_DELAY.get(site_name, 0))
    return fetch_all_pages(site_name, first, parse_esweb, get_next_page_url_esweb)


def _load_seen_history(path):
    """Load seen property history (permanent, no expiry)."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_seen_history(path, history):
    """Save seen property history to file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    # Load seen history (property keys seen in the last 7 days)
    history_path = os.path.join(DATA_DIR, "seen_history.json")
    seen_history = _load_seen_history(history_path)

    is_first_run = len(seen_history) == 0

    # Fetch and parse all sites
    all_properties = []
    site_counts = {}

    # Site configs: (name, parse_fn, next_page_fn)
    site_configs = [
        ("賃貸EX", parse_chintai_ex, get_next_page_url_chintai_ex),
        ("賃貸EX(神奈川)", parse_chintai_ex, get_next_page_url_chintai_ex),
        ("賃貸EX(埼玉)", parse_chintai_ex, get_next_page_url_chintai_ex),
        ("スモッカ", parse_smocca, get_next_page_url_smocca),
        ("スモッカ(神奈川)", parse_smocca, get_next_page_url_smocca),
        ("スモッカ(埼玉)", parse_smocca, get_next_page_url_smocca),
        ("ペットアドパーク", parse_petadpark, get_next_page_url_petadpark),
        ("AirDoor", parse_airdoor, get_next_page_url_airdoor),
        ("R-STORE", parse_rstore, get_next_page_url_rstore),
        ("ペットホームウェブ", parse_pethomeweb, get_next_page_url_pethomeweb),
        ("ペット可賃貸.net", parse_petkachintai, get_next_page_url_petkachintai),
        ("TOB", parse_ielove, get_next_page_url_ielove),
        ("SUUMO(重点6駅)", parse_suumo, get_next_page_url_suumo),
        *((name, parse_suumo, get_next_page_url_suumo) for name in SUUMO_AREA_URLS),
        ("HOME'S(重点6駅)", parse_homes, get_next_page_url_homes),
        ("アットホーム(重点6駅)", parse_athome, get_next_page_url_athome),
        ("いい部屋ネット(重点6駅)", parse_eheya, get_next_page_url_eheya),
        ("ピタットハウス(重点6駅)", parse_pitat, get_next_page_url_pitat),
        ("ハトマーク(重点6駅)", parse_hatomark, get_next_page_url_hatomark),
        ("東都", parse_tohto, get_next_page_url_tohto),
        ("アイホープハウス", parse_ielove, get_next_page_url_ielove),
        ("DOOR賃貸", parse_door_ac, get_next_page_url_door_ac),
    ]

    print(f"=== 賃貸物件チェック {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")

    for site_name, parse_fn, next_page_fn in site_configs:
        url = URLS.get(site_name)
        if not url:
            continue
        max_pages = MAX_PAGES.get(site_name, 30)
        print(f"[{site_name}]")
        props = fetch_all_pages(site_name, url, parse_fn, next_page_fn, max_pages)
        # Add source site name
        for p in props:
            p["source_site"] = site_name
        all_properties.extend(props)
        site_counts[site_name] = len(props)

    for site_name, page_url in ESWEB_SITES.items():
        print(f"[{site_name}]")
        props = fetch_esweb_site(site_name, page_url)
        for p in props:
            p["source_site"] = site_name
        all_properties.extend(props)
        site_counts[site_name] = len(props)

    # Deduplicate by detail_url
    seen_urls = set()
    unique_properties = []
    for p in all_properties:
        url = p.get("detail_url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_properties.append(p)
        elif not url:
            unique_properties.append(p)

    print(f"\n--- 集計 ---")
    for site, count in site_counts.items():
        print(f"  {site}: {count}件")
    print(f"  合計: {len(all_properties)}件 (重複除去後: {len(unique_properties)}件)")

    # Save current data
    current_data = {
        "fetched_at": datetime.now().isoformat(),
        "properties": unique_properties,
    }
    latest_path = os.path.join(DATA_DIR, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(current_data, f, ensure_ascii=False, indent=2)

    # Diff: find new listings (not previously seen)
    now_iso = datetime.now().isoformat()
    new_properties = [p for p in unique_properties if not _identity_keys(p) & seen_history.keys()]
    unseen_count = len(new_properties)

    # Notify only listings that satisfy the マンションノート conditions
    matching = []
    notified_keys = set()
    for p in new_properties:
        area_scoped = p.get("source_site") not in UNSCOPED_SITES
        keys = _identity_keys(p)
        if unmet_conditions(p, area_scoped) or keys & notified_keys:
            continue
        notified_keys |= keys
        p["area_preference"] = area_preference(p, area_scoped)
        matching.append(p)
    print(f"\n未確認 {unseen_count}件のうち条件に合う物件: {len(matching)}件")
    for p in matching:
        p["match_score"] = rule_score(p)
        p["key"] = listing_key(p)
    new_properties = sorted(matching, key=lambda p: p["match_score"], reverse=True)

    # Add only NEW properties to seen history (don't refresh existing timestamps)
    for p in unique_properties:
        for key in _identity_keys(p):
            seen_history.setdefault(key, now_iso)

    if is_first_run:
        print(f"\n初回実行のためレポートなし。{len(unique_properties)}件のデータを保存しました。")
    else:
        print(f"\n--- 差分 ---")
        print(f"  新着: {len(new_properties)}件")

        if new_properties:
            print(f"\n=== 新着物件 ===\n")
            for p in new_properties:
                print(f"【新着】{p.get('property_name', '不明')}")
                print(f"  家賃: {p.get('rent', '?')}（管理費{p.get('management_fee', '?')}）")
                print(f"  間取り: {p.get('floor_plan', '?')} / {p.get('area_sqm', p.get('area', '?'))}")
                station = p.get('nearest_station', '?')
                walk = p.get('walk_minutes', '?')
                line = p.get('railway_line', '')
                print(f"  最寄駅: {line} {station} 徒歩{walk}分")
                print(f"  住所: {p.get('address', '?')}")
                print(f"  ペット: {p.get('pet_conditions', '?')}")
                print(f"  サイト: {p.get('source_site', '?')}")
                print(f"  URL: {p.get('detail_url', '')}")
                print()

    # Queue new matches for notify.py (after the daily AI review); keep unsent ones
    added = 0 if is_first_run else _add_to_pending(new_properties)
    print(f"未通知リストに追加: {added}件")

    _save_seen_history(history_path, seen_history)

    print("完了。")
    return added


def _add_to_pending(properties):
    path = os.path.join(DATA_DIR, "pending.json")
    pending = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            pending = json.load(f)
    queued = {p["key"] for p in pending}
    added = [p for p in properties if p["key"] not in queued]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pending + added, f, ensure_ascii=False, indent=2)
    return len(added)


if __name__ == "__main__":
    new_count = main()
    # Exit 1 when nothing new was queued, so the workflow sends the "no new listings" message
    sys.exit(0 if new_count else 1)
