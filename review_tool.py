"""Helper for the daily Claude routine that reviews new listings (no API cost).

  python3 review_tool.py show   # wish list, how to review, ❤️/✖ history, and the queued listings
  python3 review_tool.py check  # validate data/ai_review.json before committing it

The routine writes data/ai_review.json and pushes it; that push makes the
notify workflow send the LINE cards in the reviewed order.
"""

import json
import os
import sys

from ranking import REVIEW_GUIDE, WISH_LIST, load_feedback

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
LISTING_FIELDS = ("key", "match_score", "property_name", "rent", "management_fee", "floor_plan",
                  "area_sqm", "railway_line", "nearest_station", "walk_minutes", "address",
                  "building_year_month", "floor_info", "structure", "area_preference")


def _pending():
    path = os.path.join(DATA_DIR, "pending.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def show() -> int:
    pending = _pending()
    print("# 希望条件\n" + WISH_LIST)
    print("# 整理のしかた\n" + REVIEW_GUIDE)
    print("# 評価履歴（❤️お気に入り／✖却下）")
    try:
        feedback = load_feedback()
    except (OSError, ValueError) as e:
        feedback = []
        print(f"（読み込めませんでした: {e}）")
    if not os.environ.get("FEEDBACK_URL"):
        print("（FEEDBACK_URL が未設定のため、評価履歴はありません）")
    for f in feedback:
        mark = {"fav": "❤️", "reject": "✖"}.get(f.get("action"), f.get("action"))
        memo = f" / メモ: {f['comment']}" if f.get("comment") else ""
        print(f"- {mark} {f.get('summary', '')}{memo}")
    print(f"\n# 未通知の物件（{len(pending)}件。rule_score は match_score の値）")
    for p in pending:
        print(json.dumps({k: p[k] for k in LISTING_FIELDS if p.get(k)}, ensure_ascii=False))
    return 0


def check() -> int:
    path = os.path.join(DATA_DIR, "ai_review.json")
    keys = {p["key"] for p in _pending()}
    try:
        with open(path, encoding="utf-8") as f:
            items = json.load(f)["items"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"NG: {path} を読めません: {e}")
        return 1
    errors = []
    seen = set()
    for i, item in enumerate(items):
        key = item.get("key")
        if key not in keys:
            errors.append(f"items[{i}]: 未通知リストにない key {key!r}")
        seen.add(key)
        if not isinstance(item.get("score"), int) or not 0 <= item["score"] <= 100:
            errors.append(f"items[{i}]: score は0〜100の整数にしてください")
        for field in ("title", "comment", "duplicate_of"):
            if not isinstance(item.get(field), str):
                errors.append(f"items[{i}]: {field} は文字列にしてください")
        if item.get("duplicate_of") and item["duplicate_of"] not in keys:
            errors.append(f"items[{i}]: duplicate_of {item['duplicate_of']!r} は未通知リストにありません")
    missing = keys - seen
    if missing:
        errors.append(f"未整理の物件が{len(missing)}件あります: {sorted(missing)[:5]}")
    for e in errors:
        print("NG:", e)
    if not errors:
        print(f"OK: {len(items)}件")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit({"show": show, "check": check}[sys.argv[1]]())
