"""LINE notification: one card per listing with ❤️ / ✖ buttons.

Tapping ❤️ or ✖ sends a postback to the webhook (gas/line_webhook.gs), which
records it, and opens the keyboard pre-filled with "📝メモ: " so the reason can
be typed straight away. The webhook stores both for the next ranking run.

Usage from the workflow:  python3 line_notify.py data/latest_messages.json
(env LINE_TOKEN and LINE_GROUP_ID)
"""

import json
import os
import sys
import urllib.error
import urllib.request

from conditions import building_age, number, yen
from ranking import listing_key

CARDS_PER_CAROUSEL = 12  # LINE carousel limit
MAX_CAROUSELS = 4        # a push carries at most 5 messages: 1 header + 4 carousels
MEMO_PREFIX = "📝メモ: "


def _title(p) -> str:
    return (p.get("ai_title") or p.get("property_name") or "物件")[:40]


def _summary(p) -> str:
    """Short text stored with the ❤️/✖ record so later rankings know what was rated."""
    parts = [_title(p), _rent_text(p), p.get("floor_plan"), p.get("area_sqm"),
             f"{p.get('nearest_station')}徒歩{p.get('walk_minutes')}分" if p.get("nearest_station") else "",
             p.get("address")]
    return " / ".join(str(x) for x in parts if x)[:200]


def _rent_text(p) -> str:
    rent = yen(p.get("rent"))
    if not rent:
        return "賃料不明"
    total = rent + (yen(p.get("management_fee")) or 0)
    return f"{total / 10000:.1f}万円（管理費込）"


def _spec_text(p) -> str:
    area = number(p.get("area_sqm"))
    age = building_age(p.get("building_year_month"))
    parts = [p.get("floor_plan") or "", f"{area:g}㎡" if area else "", f"築{age}年" if age is not None else ""]
    return " / ".join(x for x in parts if x) or "間取り不明"


def notified_entry(p, date: str) -> dict:
    """What the LINE bot shows for a listing in the ❤️ list (data/notified.json)."""
    station = f"🚶 {p.get('nearest_station')} 徒歩{p.get('walk_minutes')}分" if p.get("nearest_station") else ""
    return {
        "title": _title(p),
        "details": " / ".join(x for x in (f"💰 {_rent_text(p)}", f"🏠 {_spec_text(p)}", station) if x),
        "url": p.get("detail_url") or "",
        "score": p.get("match_score"),
        "comment": p.get("ai_comment") or "",
        "date": date,
    }


def _text(text, **style):
    return {"type": "text", "text": str(text), "wrap": True, **style}


def _postback(label, action, p, display):
    data = json.dumps({"a": action, "k": listing_key(p), "s": _summary(p)}, ensure_ascii=False)
    return {
        "type": "button", "style": "secondary", "height": "sm",
        "action": {
            "type": "postback", "label": label, "data": data,  # ≤300 chars: summary is capped
            "displayText": f"{display} {_title(p)}"[:300],
            "inputOption": "openKeyboard", "fillInText": MEMO_PREFIX,
        },
    }


def _card(p) -> dict:
    pref = p.get("area_preference")
    head = [_text(f"マッチ度 {p.get('match_score', '-')}", size="xs", weight="bold", color="#E8590C", flex=0)]
    if pref:
        head.append(_text(f"⭐{pref}エリア", size="xs", color="#888888", align="end"))
    station = (f"🚶 {p.get('nearest_station')} 徒歩{p.get('walk_minutes')}分"
               if p.get("nearest_station") else "🚶 最寄駅不明")
    body = [
        {"type": "box", "layout": "baseline", "contents": head},
        _text(_title(p), weight="bold", size="md", maxLines=2),
        _text(f"💰 {_rent_text(p)}", size="sm"),
        _text(f"🏠 {_spec_text(p)}", size="sm"),
        _text(station, size="sm"),
    ]
    if p.get("ai_comment"):
        body.append(_text(p["ai_comment"], size="xs", color="#555555"))

    footer = []
    if str(p.get("detail_url", "")).startswith("http"):
        footer.append({"type": "button", "style": "primary", "height": "sm",
                       "action": {"type": "uri", "label": "詳細を見る", "uri": p["detail_url"]}})
    footer.append({"type": "box", "layout": "horizontal", "spacing": "xs", "contents": [
        _postback("❤️ お気に入り", "fav", p, "❤️"),
        _postback("✖ 却下", "reject", p, "✖"),
    ]})
    return {
        "type": "bubble", "size": "kilo",
        "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": body},
        "footer": {"type": "box", "layout": "vertical", "spacing": "xs", "contents": footer},
    }


def build_messages(properties: list[dict]) -> list[dict]:
    """Header text plus carousels for the best-matching listings (already sorted)."""
    if not properties:
        return []
    shown = properties[:CARDS_PER_CAROUSEL * MAX_CAROUSELS]
    header = f"🏠 新着物件 {len(properties)}件（マッチ度の高い順）"
    if len(shown) < len(properties):
        header += f"\n上位{len(shown)}件を表示しています。残りはGitHubのIssueで確認できます。"
    header += "\n気になる物件は❤️、合わない物件は✖を押して、理由をメモで送ってください。次回からの提案に反映します。"
    messages = [{"type": "text", "text": header}]
    for i in range(0, len(shown), CARDS_PER_CAROUSEL):
        chunk = shown[i:i + CARDS_PER_CAROUSEL]
        messages.append({
            "type": "flex",
            "altText": f"新着物件 {i + 1}〜{i + len(chunk)}件目: {_title(chunk[0])} ほか"[:400],
            "contents": {"type": "carousel", "contents": [_card(p) for p in chunk]},
        })
    return messages


def push(messages: list[dict]) -> None:
    body = json.dumps({"to": os.environ["LINE_GROUP_ID"], "messages": messages}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ['LINE_TOKEN']}"},
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        print(f"LINE push: HTTP {res.status}")


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        msgs = json.load(f)["messages"]
    if msgs:
        try:
            push(msgs)
        except urllib.error.HTTPError as e:
            # Still let the user know if LINE rejects the cards
            print(f"LINE push failed: HTTP {e.code} {e.read().decode('utf-8', 'replace')}")
            push([{"type": "text", "text": msgs[0]["text"] + "\n（カードを表示できなかったため、詳細はGitHubのIssueで確認してください）"}])
