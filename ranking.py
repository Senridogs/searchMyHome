"""Order new listings by how well they fit the user's wishes.

A rule-based match score from the マンションノート tiers always runs. When
ANTHROPIC_API_KEY is set, Claude re-scores the listings against the whole
wish list and the user's ❤️/✖ feedback from LINE, tidies each title, writes
a one-line comment, and marks rooms that are listed twice under other names.
"""

import json
import os
import urllib.request

from conditions import building_age, number, yen

MODEL = "claude-opus-5-5"
AI_BATCH_SIZE = 40

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

SYSTEM_PROMPT = f"""\
あなたは賃貸物件探しを手伝うアシスタントです。ユーザーはペットと暮らす部屋を探しています。
新着物件の一覧を受け取ったら、ユーザーの希望とこれまでの評価（❤️お気に入り／✖却下とその理由）に
照らして、各物件のマッチ度を判定し、通知用に内容を整理してください。

# ユーザーの希望（マンションノートの設定）
{WISH_LIST}
# 判定のしかた
- score: 0〜100のマッチ度。rule_score（希望条件の段階から機械的に計算した点数）を出発点に、
  エリアの好み、狙っている駅との近さ、評価履歴から読み取れる好み・嫌うポイントを加味して決める。
  却下された物件と同じ理由が当てはまる物件は大きく下げ、お気に入りに似た物件は上げる。
- title: 通知に表示する物件名。最大24文字。物件名が「京王線 千歳烏山駅 2階建 築3年」のように
  建物名でない場合は「町名＋最寄駅」などで分かりやすくする（例: 給田2丁目の2LDK（千歳烏山）)。
- comment: 日本語で最大45文字。この物件の良い点と気になる点を一言で。評価履歴を反映した場合はそれも書く。
- duplicate_of: 同じ部屋が別名・別サイトで重複して載っていると判断できる場合、先に出てきた方のid。
  所在地・間取り・面積・階がほぼ同じなら同じ部屋とみなす。重複でなければ空文字。
渡された全物件について、必ず1件ずつ結果を返してください。
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "listings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "score": {"type": "integer"},
                    "title": {"type": "string"},
                    "comment": {"type": "string"},
                    "duplicate_of": {"type": "string"},
                },
                "required": ["id", "score", "title", "comment", "duplicate_of"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["listings"],
    "additionalProperties": False,
}


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
    """❤️/✖ records from the LINE webhook (gas/line_webhook.gs), if configured."""
    url = os.environ.get("FEEDBACK_URL")
    if not url:
        return []
    try:
        with urllib.request.urlopen(url, timeout=30) as res:
            data = json.loads(res.read().decode("utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError) as e:
        print(f"  評価履歴を読めませんでした: {e}")
        return []


def _feedback_text(feedback: list[dict]) -> str:
    lines = []
    for f in feedback[-100:]:
        mark = {"fav": "❤️お気に入り", "reject": "✖却下"}.get(f.get("action"), f.get("action"))
        comment = f" 理由・メモ: {f['comment']}" if f.get("comment") else ""
        lines.append(f"- {mark}: {f.get('summary', '')}{comment}")
    return "\n".join(lines) or "（まだ評価はありません）"


def _listing_for_ai(i: int, p: dict) -> dict:
    keys = ("property_name", "rent", "management_fee", "floor_plan", "area_sqm", "railway_line",
            "nearest_station", "walk_minutes", "address", "building_year_month", "floor_info",
            "structure", "area_preference")
    return {"id": str(i), "rule_score": p["match_score"], **{k: p.get(k) for k in keys if p.get(k)}}


def _ask_claude(client, listings: list[dict], feedback_text: str) -> list[dict] | None:
    system = [{
        "type": "text",
        "text": SYSTEM_PROMPT + "\n# これまでの評価\n" + feedback_text,
        "cache_control": {"type": "ephemeral"},
    }]
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=32000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        system=system,
        messages=[{"role": "user", "content": json.dumps(listings, ensure_ascii=False)}],
    ) as stream:
        response = stream.get_final_message()
    if response.stop_reason in ("refusal", "max_tokens"):
        print(f"  AIの整理を中断しました（{response.stop_reason}）")
        return None
    text = next((b.text for b in response.content if b.type == "text"), "")
    return json.loads(text)["listings"]


def rank(properties: list[dict]) -> list[dict]:
    """Add match_score (and AI title/comment), drop AI-found duplicates, sort best first."""
    for p in properties:
        p["match_score"] = rule_score(p)
    properties.sort(key=lambda p: p["match_score"], reverse=True)

    if not properties or not os.environ.get("ANTHROPIC_API_KEY"):
        return properties
    try:
        import anthropic
    except ImportError:
        print("  anthropic パッケージが無いため、AIの整理を省略しました")
        return properties

    client = anthropic.Anthropic()
    feedback_text = _feedback_text(load_feedback())
    duplicates = set()
    for start in range(0, len(properties), AI_BATCH_SIZE):
        batch = properties[start:start + AI_BATCH_SIZE]
        listings = [_listing_for_ai(start + i, p) for i, p in enumerate(batch)]
        try:
            results = _ask_claude(client, listings, feedback_text)
        except (anthropic.APIError, ValueError, KeyError) as e:
            print(f"  AIの整理に失敗しました: {e}")
            results = None
        for r in results or []:
            idx = int(r["id"]) if r.get("id", "").isdigit() else -1
            if not start <= idx < start + len(batch):
                continue
            p = properties[idx]
            p["match_score"] = max(0, min(100, int(r["score"])))
            p["ai_title"] = r["title"].strip()
            p["ai_comment"] = r["comment"].strip()
            if r["duplicate_of"].isdigit() and int(r["duplicate_of"]) != idx:
                duplicates.add(idx)
    print(f"  AIで整理しました（重複として除外: {len(duplicates)}件）")
    ranked = [p for i, p in enumerate(properties) if i not in duplicates]
    ranked.sort(key=lambda p: p["match_score"], reverse=True)
    return ranked
