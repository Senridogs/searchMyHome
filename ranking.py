"""Match scores for new listings, and merging in the daily AI review.

rule_score() rates a listing from the マンションノート tiers. The AI review is
done free of API charges by a daily Claude routine: it reads
`python3 review_tool.py show`, writes data/ai_review.json, and apply_review()
merges that file in before notifying.
"""

import hashlib
import json
import os
import urllib.request

from conditions import building_age, number, yen

WISH_LIST = """\
【必須条件】賃料19万円以下（管理費込み）、2LDK/3LDK/4LDK以上、駅徒歩10分以内、専有面積45㎡以上、
築50年以内、鉄筋系・鉄骨系、ペット相談可、コンロ2口以上、バス・トイレ別、室内洗濯機置場

【程度の目安】
- 賃料: 14万円以下なら割安でラッキー / 16万円くらいが妥当 / 19万円が限界
- 間取り: 2LDK・3LDKが第一希望（4LDK以上も候補）
- 駅徒歩: 5分以内なら他を多少妥協できる / 7分以内なら不満なし / 10分が限界
- 専有面積: 70㎡以上なら他を多少妥協できる / 50㎡以上なら不満なし / 45㎡が下限
- 築年数: 5年以内なら他を多少妥協できる / 30年以内なら不満なし / 50年が限界

【なるべく満たしてほしい（特に重視）】カウンターキッチン、南向き、TVモニタ付インターホン、都市ガス
【あればすごく嬉しい】2階以上、オートロック、エアコン、宅配ボックス、ごみ出し24時間OK、
24時間換気システム、敷地内ゴミ置き場、インターネット無料
【あると少し嬉しい】東向き、西向き、楽器相談
【口コミで重視】騒音・防音性（かなり重視）、お部屋・共用部分・住人の雰囲気・治安など

【通勤】赤坂見附駅・京橋駅まで、それぞれ40分以内（乗換1回まで）

【エリア】
- 特に狙っている: 久我山とその前後の駅（富士見ヶ丘・三鷹台）、仙川とその前後の駅（千歳烏山・つつじヶ丘）
- 住めたら理想的: 大岡山、三鷹台、学芸大学、鷺沼、元住吉、祖師ヶ谷大蔵、青葉台、市が尾、宮崎台、あざみ野、
  大田区、練馬区、中野区、梶が谷、杉並区、新百合ヶ丘、平和台、狛江、荻窪、菊名、南阿佐ケ谷、地下鉄成増、成増、
  藤が丘、仙川、下赤塚、地下鉄赤塚、つつじヶ丘、光が丘、宮前平、大倉山、石神井公園、千歳烏山、永福町、浜田山、
  西小山、成城学園前、経堂、千歳船橋、富士見ヶ丘、都立大学、新中野、東高円寺、二子新地、新高円寺、多摩川、
  小竹向原、富士見台、高井戸、下丸子、氷川台、西太子堂、久我山、江田、西永福、武蔵新田
- 住みたい: 等々力、西荻窪、井の頭公園、たまプラーザ、尾山台、日吉、和光市、用賀、調布、北区、日吉本町、
  大泉学園、志木、朝霞、朝霞台、桜新町、練馬高野台、津田山、東長崎、駒沢大学、千川、要町、南千住
- 避けたい: 鴨居、志村三丁目、鶴川、宿河原、新板橋、希望ヶ丘、東山田、鈴木町、和泉多摩川、江戸川区、足立区、
  荒川区、葛飾区、田奈、江東区、緑園都市、五月台、中山、川崎市川崎区、立場、金沢文庫、市川市
"""

REVIEW_GUIDE = """\
未通知の物件それぞれについて、希望条件と評価履歴（❤️お気に入り／✖却下と理由）に照らして整理し、
data/ai_review.json に次の形で書く:
{"items": [{"key": "...", "score": 0-100の整数, "title": "...", "comment": "...", "duplicate_of": ""}, ...]}

- key: 物件のkeyをそのまま。未通知の物件すべてについて1件ずつ書く。
- score: マッチ度。rule_score（希望条件の段階から機械的に計算した点数）を出発点に、エリアの好み、
  狙っている駅との近さ、評価履歴から読み取れる好み・嫌うポイントを加味して決める。
  却下された物件と同じ理由が当てはまる物件は大きく下げ、お気に入りに似た物件は上げる。
- title: 通知に表示する物件名（24文字まで）。物件名が「京王線 千歳烏山駅 2階建 築3年」のように
  建物名でない場合は「町名＋間取り（最寄駅）」などで分かりやすくする。
- comment: 45文字までの一言。良い点と気になる点。リポジトリは公開なので、評価履歴のメモの文面は
  そのまま引用しない（「以前の却下理由に近い」程度の書き方にする）。
- duplicate_of: 同じ部屋が別名・別サイトで重複していると判断できる場合、残す方の物件のkey。
  所在地・間取り・面積・階がほぼ同じなら同じ部屋とみなす。重複でなければ空文字。
"""


def listing_key(p) -> str:
    """Short stable id for a listing (pending queue, AI review, LINE postbacks)."""
    basis = "|".join(str(p.get(k) or "") for k in ("address", "floor_plan", "area_sqm", "rent"))
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def _tier(value, tiers, unknown):
    """Points for the first tier whose limit the value meets."""
    if value is None:
        return unknown
    for meets, points in tiers:
        if meets(value):
            return points
    return 0


def rule_score(p) -> int:
    """0-100 from the マンションノート ideal / OK / limit tiers."""
    rent = yen(p.get("rent"))
    total = rent + (yen(p.get("management_fee")) or 0) if rent else None
    plan = str(p.get("floor_plan") or "")
    score = (
        _tier(total, [(lambda v: v <= 140_000, 25), (lambda v: v <= 160_000, 18), (lambda v: v <= 190_000, 8)], 12)
        + _tier(number(p.get("walk_minutes")), [(lambda v: v <= 5, 20), (lambda v: v <= 7, 15), (lambda v: v <= 10, 8)], 10)
        + _tier(number(p.get("area_sqm")), [(lambda v: v >= 70, 20), (lambda v: v >= 50, 14), (lambda v: v >= 45, 6)], 10)
        + _tier(building_age(p.get("building_year_month")), [(lambda v: v <= 5, 10), (lambda v: v <= 30, 7), (lambda v: v <= 50, 3)], 5)
        + {"理想": 20, "住みたい": 12}.get(p.get("area_preference") or "", 0)
        + (5 if plan[:1] in ("2", "3") else 3)
    )
    return min(score, 100)


def load_feedback() -> list[dict]:
    """❤️/✖ records from the LINE webhook (gas/line_webhook.gs), if FEEDBACK_URL is set."""
    url = os.environ.get("FEEDBACK_URL")
    if not url:
        return []
    with urllib.request.urlopen(url, timeout=30) as res:
        data = json.loads(res.read().decode("utf-8"))
    return data if isinstance(data, list) else []


def apply_review(properties: list[dict], review: dict) -> list[dict]:
    """Merge an AI review into the listings, drop its duplicates, sort best first."""
    items = {i.get("key"): i for i in review.get("items", []) if isinstance(i, dict)}
    keys = {p["key"] for p in properties}
    ranked = []
    for p in properties:
        r = items.get(p["key"])
        if r:
            dup = r.get("duplicate_of") or ""
            if dup and dup != p["key"] and dup in keys:
                continue
            try:
                p["match_score"] = max(0, min(100, int(r["score"])))
            except (KeyError, TypeError, ValueError):
                pass
            p["ai_title"] = str(r.get("title") or "").strip()
            p["ai_comment"] = str(r.get("comment") or "").strip()
        ranked.append(p)
    ranked.sort(key=lambda p: p.get("match_score", 0), reverse=True)
    return ranked
