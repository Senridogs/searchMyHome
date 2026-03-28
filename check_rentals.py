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
import subprocess
import sys
from datetime import datetime, timedelta

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parse_chintai_ex import parse_chintai_ex, get_next_page_url_chintai_ex
from parse_smocca import parse_smocca, get_next_page_url_smocca
from parse_petadpark import parse_petadpark, get_next_page_url_petadpark
from parse_airdoor import parse_airdoor, get_next_page_url_airdoor
from parse_rstore import parse_rstore, get_next_page_url_rstore
from parse_pethomeweb import parse_pethomeweb, get_next_page_url_pethomeweb
from parse_petkachintai import parse_petkachintai, get_next_page_url_petkachintai

HEADERS = [
    "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "-H", "Accept-Language: ja,en-US;q=0.9,en;q=0.8",
]

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Search URLs for each site
URLS = {
    "賃貸EX": "https://chintai-ex.jp/search/detail?city_code%5B%5D=13101&city_code%5B%5D=13102&city_code%5B%5D=13103&city_code%5B%5D=13104&city_code%5B%5D=13105&city_code%5B%5D=13106&city_code%5B%5D=13107&city_code%5B%5D=13109&city_code%5B%5D=13110&city_code%5B%5D=13111&city_code%5B%5D=13112&city_code%5B%5D=13113&city_code%5B%5D=13114&city_code%5B%5D=13115&city_code%5B%5D=13116&city_code%5B%5D=13117&city_code%5B%5D=13118&city_code%5B%5D=13119&city_code%5B%5D=13120&cond%5Barea%5D%5Bmin%5D=50&cond%5Bbaths%5D%5B%5D=1&cond%5Bbuilt_year%5D=25&cond%5Bchinryou%5D%5Binclude_kanrihi%5D=true&cond%5Bchinryou%5D%5Bmax%5D=190000&cond%5Bconditions%5D%5B%5D=64&cond%5Bkitchens%5D%5B%5D=1&cond%5Bkitchens%5D%5B%5D=2&cond%5Blocations%5D%5B%5D=2&cond%5Bother_conditions%5D%5B%5D=4096&cond%5Bplans%5D%5Bmax%5D=44&cond%5Bplans%5D%5Bmin%5D=10&cond%5Bwalk_min%5D=15&prefecture_path=tokyo",
    "スモッカ": "https://smocca.jp/search/results?city_code%5B%5D=13101&city_code%5B%5D=13102&city_code%5B%5D=13103&city_code%5B%5D=13104&city_code%5B%5D=13105&city_code%5B%5D=13106&city_code%5B%5D=13107&city_code%5B%5D=13108&city_code%5B%5D=13109&city_code%5B%5D=13110&city_code%5B%5D=13111&city_code%5B%5D=13112&city_code%5B%5D=13113&city_code%5B%5D=13114&city_code%5B%5D=13115&city_code%5B%5D=13116&city_code%5B%5D=13117&city_code%5B%5D=13119&city_code%5B%5D=13120&city_code%5B%5D=13204&cond%5Barea%5D%5Bmin%5D=50&cond%5Bbaths%5D%5B%5D=1&cond%5Bbuilt_year%5D=25&cond%5Bchinryou%5D%5Binclude_kanrihi%5D=true&cond%5Bchinryou%5D%5Bmax%5D=190000&cond%5Bconditions%5D%5B%5D=64&cond%5Bkitchens%5D%5B%5D=2&cond%5Blocations%5D%5B%5D=16&cond%5Bplans%5D%5Bmax%5D=44&cond%5Bplans%5D%5Bmin%5D=10&cond%5Bsecurities%5D%5B%5D=2&cond%5Bsort%5D=arrived_at+desc&cond%5Bstructs%5D%5B%5D=2&cond%5Bstructs%5D%5B%5D=3&cond%5Bwalk_min%5D=15&prefecture_path=tokyo&sort_base=smocca_pcvr_a",
    "ペットアドパーク": "https://www.pet-adpark.jp/es/pref_city_search_list.php?pref=1310_1320&city=1310_1059-1310_1075-1310_1105-1310_1113-1310_1121-1310_1148-1310_1156-1310_1164-1310_1172-1310_1202&tmpl=pet&area=1000&category=chintai&count=30&sortHistory=sort2a&sort=sort8d&bldgType[]=01_03_04&bldgType[]=02&bldgType[]=06&moneyL=&moneyH=190000&kyoekiIncFlg=1&preset_disp=off&spaceL=50&spaceH=&walk=15&tikunensu=&newdate=&begin=0",
    "AirDoor": "https://airdoor.jp/list?jis=13101%2C13102%2C13103%2C13104%2C13105%2C13106%2C13107%2C13108%2C13109%2C13110%2C13111%2C13112%2C13113%2C13114%2C13115%2C13116%2C13117%2C13119%2C13120%2C13204&ur=190000&iaf=1&uf=15&le=50&ua=30&cs=d-1-2&dir=d-3&ca=d-8-10-24-41",
    "R-STORE": "https://www.r-store.jp/search?&sb_purpose1%5B%5D=R&sb_r_max=190000&sb_price=1&sb_c%5B%5D=13101&sb_c%5B%5D=13102&sb_c%5B%5D=13103&sb_c%5B%5D=13104&sb_c%5B%5D=13105&sb_c%5B%5D=13113&sb_c%5B%5D=13106&sb_c%5B%5D=13107&sb_c%5B%5D=13109&sb_c%5B%5D=13110&sb_c%5B%5D=13111&sb_c%5B%5D=13112&sb_c%5B%5D=13114&sb_c%5B%5D=13115&sb_c%5B%5D=13120&sb_c%5B%5D=13116&sb_c%5B%5D=13117&sb_c%5B%5D=13119&sb_c%5B%5D=13204&sb_walk_from=15&sb_area_up=50&sb_floor_plan%5B%5D=1R&sb_floor_plan%5B%5D=1K&sb_floor_plan%5B%5D=1DK&sb_floor_plan%5B%5D=1LDK&sb_floor_plan%5B%5D=1SLDK&sb_floor_plan%5B%5D=2K&sb_floor_plan%5B%5D=2DK&sb_floor_plan%5B%5D=2LDK&sb_floor_plan%5B%5D=2SLDK&sb_floor_plan%5B%5D=3K&sb_floor_plan%5B%5D=3DK&sb_floor_plan%5B%5D=3LDK&sb_floor_plan%5B%5D=3SLDK&sb_floor_plan%5B%5D=4K&sb_floor_plan%5B%5D=4DK&sb_floor_plan%5B%5D=4LDK&sb_floor_plan%5B%5D=4SLDK&sb_floor_plan%5B%5D=5K%E4%BB%A5%E4%B8%8A&sb_age_of_building=25&sb_pet%5B%5D=%E5%B0%8F%E5%9E%8B%E7%8A%AC%E5%8F%AF&sb_pet%5B%5D=%E7%8C%AB%E5%8F%AF&sb_r_category%5B%5D=%E3%81%B5%E3%81%9F%E3%82%8A%E6%9A%AE%E3%82%89%E3%81%97%E5%90%91%E3%81%8D&sb_kodawari_category%5B%5D=2%E9%9A%8E%E4%BB%A5%E4%B8%8A",
    "ペットホームウェブ": "https://www.pethomeweb.com/chintai/tokyo/list/?AR2=A2_55yo-A2_54yo-A2_55t2-A2_54li-A2_54r3-A2_55fl-A2_546l-A2_55la-A2_54hv-A2_5568-A2_54dy-A2_53z4-A2_53v1-A2_55q6-A2_55id-A2_5637-A2_54bi-A2_542j-A2_54vg-A2_575r&SO=1&CH=1-33&CO=1&ME=8-18&EW=15&CN=9&KO=91-92-30-82-12-9-26",
    "ペット可賃貸.net": "https://petkachintai.net/archives/category/pet-friendly-rentals-in-tokyo",
}

# Max pages per site
MAX_PAGES = {
    "ペット可賃貸.net": 1,
}


def curl_fetch(url: str) -> str | None:
    """Fetch URL with curl and browser headers. Returns HTML string or None."""
    result = subprocess.run(
        ["curl", "-s", "-w", "\n%{http_code}", *HEADERS, url],
        capture_output=True, text=True, timeout=30,
    )
    lines = result.stdout.rsplit("\n", 1)
    if len(lines) < 2:
        return None
    body, status = lines[0], lines[1].strip()
    if status == "200":
        return body
    print(f"  HTTP {status} for {url[:80]}...")
    return None


def _prop_key(p):
    """Generate a stable identity key for a property (name + address).

    Some sites change URLs between fetches for the same property,
    so we use property name + address instead of URL for deduplication.
    """
    name = p.get("property_name", "")
    addr = p.get("address", "")
    return f"{name}|{addr}"


def fetch_all_pages(site_name, first_url, parse_fn, next_page_fn, max_pages=30):
    """Fetch all pages for a site, returning combined property list."""
    all_props = []
    url = first_url
    page = 1

    while url and page <= max_pages:
        html = curl_fetch(url)
        if not html:
            print(f"  {site_name} page {page}: fetch failed")
            break
        props = parse_fn(html)
        all_props.extend(props)
        print(f"  {site_name} page {page}: {len(props)} properties")
        url = next_page_fn(html)
        page += 1

    return all_props


def _write_markdown_report(new_properties, all_properties, is_first_run, path):
    """Write a markdown report of new listings to a file."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# 新着物件レポート ({now})\n"]

    if is_first_run:
        lines.append(f"初回実行: {len(all_properties)}件のデータを保存しました。\n")
    elif not new_properties:
        lines.append("新着物件はありませんでした。\n")
    else:
        lines.append(f"**新着 {len(new_properties)}件**\n")
        lines.append("---\n")
        for p in new_properties:
            name = p.get('property_name', '不明')
            url = p.get('detail_url', '')
            rent = p.get('rent', '?')
            mgmt = p.get('management_fee', '?')
            plan = p.get('floor_plan', '?')
            area = p.get('area_sqm', p.get('area', '?'))
            line = p.get('railway_line', '')
            station = p.get('nearest_station', '?')
            walk = p.get('walk_minutes', '?')
            addr = p.get('address', '?')
            pet = p.get('pet_conditions', '?')
            site = p.get('source_site', '?')

            lines.append(f"### [{name}]({url})\n")
            lines.append(f"| 項目 | 内容 |")
            lines.append(f"|------|------|")
            lines.append(f"| 家賃 | {rent}（管理費 {mgmt}） |")
            lines.append(f"| 間取り | {plan} / {area} |")
            lines.append(f"| 最寄駅 | {line} {station} 徒歩{walk}分 |")
            lines.append(f"| 住所 | {addr} |")
            lines.append(f"| ペット | {pet} |")
            lines.append(f"| サイト | {site} |")
            lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_line_message(new_properties, is_first_run, path):
    """Write a plain-text message for LINE notification with property details."""
    if is_first_run or not new_properties:
        # No detailed message needed for these cases
        with open(path, "w", encoding="utf-8") as f:
            f.write("")
        return

    lines = [f"🏠 新着物件 {len(new_properties)}件\n"]

    for p in new_properties:
        name = p.get('property_name', '不明')
        rent = p.get('rent', '?')
        mgmt = p.get('management_fee', '')
        plan = p.get('floor_plan', '?')
        area = p.get('area_sqm', p.get('area', '?'))
        station = p.get('nearest_station', '?')
        walk = p.get('walk_minutes', '?')
        url = p.get('detail_url', '')
        site = p.get('source_site', '')

        mgmt_str = f"(管理費{mgmt})" if mgmt and mgmt != '?' else ""
        lines.append(f"━━━━━━━━━━")
        lines.append(f"📍 {name}")
        lines.append(f"💰 {rent}{mgmt_str}")
        lines.append(f"🏠 {plan} / {area}")
        lines.append(f"🚶 {station} 徒歩{walk}分")
        if site:
            lines.append(f"📋 {site}")
        if url:
            lines.append(f"🔗 {url}")
        lines.append("")

    # LINE Push Message limit: 5 messages, each up to 5000 chars
    text = "\n".join(lines)
    if len(text) > 4900:
        text = text[:4800] + "\n\n…他にもあります。GitHub Issueで全件確認できます。"

    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _load_seen_history(path, retention_days=7):
    """Load seen property history, pruning entries older than retention_days."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        history = json.load(f)
    cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()
    return {k: v for k, v in history.items() if v >= cutoff}


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
        ("スモッカ", parse_smocca, get_next_page_url_smocca),
        ("ペットアドパーク", parse_petadpark, get_next_page_url_petadpark),
        ("AirDoor", parse_airdoor, get_next_page_url_airdoor),
        ("R-STORE", parse_rstore, get_next_page_url_rstore),
        ("ペットホームウェブ", parse_pethomeweb, get_next_page_url_pethomeweb),
        ("ペット可賃貸.net", parse_petkachintai, get_next_page_url_petkachintai),
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

    # Diff: find new listings (not seen in the last 7 days)
    now_iso = datetime.now().isoformat()
    new_properties = [p for p in unique_properties if _prop_key(p) not in seen_history]

    # Add only NEW properties to seen history (don't refresh existing timestamps)
    for p in unique_properties:
        key = _prop_key(p)
        if key not in seen_history:
            seen_history[key] = now_iso

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

    # Write markdown report for CI/GitHub Issue usage
    md_path = os.path.join(DATA_DIR, "report.md")
    _write_markdown_report(new_properties, unique_properties, is_first_run, md_path)

    # Write LINE notification text
    line_path = os.path.join(DATA_DIR, "line_message.txt")
    _write_line_message(new_properties, is_first_run, line_path)

    # Save seen history (keeps last 7 days)
    _save_seen_history(history_path, seen_history)

    print("完了。")
    return len(new_properties)


if __name__ == "__main__":
    new_count = main()
    # Exit with code 0 if new listings found (for CI), 1 if none
    # This lets GitHub Actions conditionally create issues
    sys.exit(0 if new_count else 1)
