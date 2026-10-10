"""Turn the queue of new listings into the GitHub Issue report and LINE cards.

  python3 notify.py prepare  # data/pending.json (+ data/ai_review.json) -> report.md, latest_messages.json
  python3 notify.py done     # after sending: empty the queue and drop the used review

latest_messages.json (the cards just sent) and notified.json (every notified
listing by key) are committed so the LINE bot can answer 「最新の物件」 and show
the ❤️ list with links.

`prepare` exits 1 when the queue is empty, so the workflow skips sending.
"""

import json
import os
import sys
from datetime import datetime, timedelta

from line_notify import build_messages, notified_entry
from ranking import apply_review

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PENDING_PATH = os.path.join(DATA_DIR, "pending.json")
REVIEW_PATH = os.path.join(DATA_DIR, "ai_review.json")
LATEST_PATH = os.path.join(DATA_DIR, "latest_messages.json")
NOTIFIED_PATH = os.path.join(DATA_DIR, "notified.json")
NOTIFIED_KEEP_DAYS = 180
ISSUE_BODY_LIMIT = 60000  # GitHub rejects issue bodies over 65,536 characters


def _load(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def _report(properties, reviewed) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    order = "AIのマッチ度" if reviewed else "マッチ度"
    lines = [f"# 新着物件レポート ({now})\n", f"**新着 {len(properties)}件**（{order}の高い順）\n", "---\n"]
    for p in properties:
        lines.append(f"### [{p.get('ai_title') or p.get('property_name', '不明')}]({p.get('detail_url', '')})\n")
        lines.append("| 項目 | 内容 |")
        lines.append("|------|------|")
        lines.append(f"| マッチ度 | {p.get('match_score', '-')} |")
        if p.get("ai_comment"):
            lines.append(f"| AIコメント | {p['ai_comment']} |")
        if p.get("area_preference"):
            lines.append(f"| エリア | {p['area_preference']}エリア |")
        lines.append(f"| 家賃 | {p.get('rent', '?')}（管理費 {p.get('management_fee', '?')}） |")
        lines.append(f"| 間取り | {p.get('floor_plan', '?')} / {p.get('area_sqm', '?')} |")
        lines.append(f"| 最寄駅 | {p.get('railway_line', '')} {p.get('nearest_station', '?')} 徒歩{p.get('walk_minutes', '?')}分 |")
        lines.append(f"| 築年月 | {p.get('building_year_month') or '?'} |")
        lines.append(f"| 住所 | {p.get('address', '?')} |")
        lines.append(f"| サイト | {p.get('source_site', '?')} |")
        lines.append("")
    text = "\n".join(lines)
    if len(text) > ISSUE_BODY_LIMIT:
        cut = text.rfind("\n### [", 0, ISSUE_BODY_LIMIT)
        rest = text[cut:].count("\n### [")
        text = text[:cut] + f"\n\n…ほか{rest}件（マッチ度の低い物件）は省略しました。"
    return text


def prepare() -> int:
    pending = _load(PENDING_PATH, [])
    if not pending:
        print("未通知の物件はありません。")
        return 1
    review = _load(REVIEW_PATH, {})
    ranked = apply_review(pending, review)
    print(f"通知: {len(ranked)}件（AIの整理: {'あり' if review else 'なし'}）")
    with open(os.path.join(DATA_DIR, "report.md"), "w", encoding="utf-8") as f:
        f.write(_report(ranked, bool(review)))
    now = datetime.now()
    _save(LATEST_PATH, {"date": now.strftime("%Y-%m-%d %H:%M"), "count": len(ranked),
                        "messages": build_messages(ranked)})

    oldest = (now - timedelta(days=NOTIFIED_KEEP_DAYS)).strftime("%Y-%m-%d")
    notified = {k: v for k, v in _load(NOTIFIED_PATH, {}).items() if v.get("date", "") >= oldest}
    for p in ranked:
        notified[p["key"]] = notified_entry(p, now.strftime("%Y-%m-%d"))
    _save(NOTIFIED_PATH, notified)
    return 0


def done() -> int:
    with open(PENDING_PATH, "w", encoding="utf-8") as f:
        json.dump([], f)
    if os.path.exists(REVIEW_PATH):
        os.remove(REVIEW_PATH)
    return 0


if __name__ == "__main__":
    sys.exit({"prepare": prepare, "done": done}[sys.argv[1]]())
