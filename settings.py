"""Conditions the user can change from LINE (see gas/line_webhook.gs).

The collect workflow runs `python3 settings.py` first: it reads the settings
saved by the LINE bot (GAS_URL) and writes data/settings.json, which
conditions.py and ranking.py load. Values are kept inside the range the site
searches cover (LIMITS), since anything looser is never fetched.
"""

import json
import os
import urllib.request

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "settings.json")

DEFAULTS = {
    "max_rent": 190_000,   # 賃料+管理費の上限（円）
    "max_walk": 10,        # 駅徒歩（分）
    "min_area": 45,        # 専有面積（㎡）
    "max_age": 50,         # 築年数（年）
    "min_rooms": 2,        # 2 = 2LDK以上
    "add_stations": [],    # 理想エリアに加える駅・市区
    "avoid_stations": [],  # 除外する駅・市区
}

# The site search URLs cover up to 22万円 / 徒歩15分 / 40㎡ / 2LDK以上
LIMITS = {
    "max_rent": (50_000, 220_000),
    "max_walk": (1, 15),
    "min_area": (40, 200),
    "max_age": (1, 100),
    "min_rooms": (2, 4),
}


def clean(raw) -> dict:
    """Defaults overlaid with valid values from raw, clamped to LIMITS."""
    settings = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    if not isinstance(raw, dict):
        return settings
    for key, (low, high) in LIMITS.items():
        try:
            settings[key] = max(low, min(high, int(float(raw[key]))))
        except (KeyError, TypeError, ValueError):
            pass
    for key in ("add_stations", "avoid_stations"):
        values = raw.get(key)
        if isinstance(values, list):
            names = [str(v).strip() for v in values if str(v).strip()]
            settings[key] = list(dict.fromkeys(names))[:50]
    return settings


def load() -> dict:
    try:
        with open(PATH, encoding="utf-8") as f:
            return clean(json.load(f))
    except (OSError, ValueError):
        return clean({})


def fetch() -> None:
    """Save the LINE bot's settings to data/settings.json (keeps the saved ones on failure)."""
    settings = load()
    url = os.environ.get("GAS_URL")
    if not url:
        print("GAS_URL が未設定のため、保存済みの条件を使います。")
    else:
        try:
            with urllib.request.urlopen(url + "&type=settings", timeout=30) as res:
                settings = clean(json.loads(res.read().decode("utf-8")))
        except (OSError, ValueError) as e:
            print(f"LINEの条件を読めませんでした（保存済みの条件を使います）: {e}")
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    print("条件:", json.dumps(settings, ensure_ascii=False))


if __name__ == "__main__":
    fetch()
