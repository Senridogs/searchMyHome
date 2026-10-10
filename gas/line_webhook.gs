/**
 * LINE の ❤️お気に入り / ✖却下 とメモを Google スプレッドシートに記録する Webhook。
 * 記録は毎日の物件チェック（ranking.py）が読み、次回からのマッチ度判定に使う。
 *
 * ■ 設定手順
 * 1. Google スプレッドシートを新規作成し、メニュー「拡張機能 > Apps Script」を開く。
 * 2. このファイルの内容をすべて貼り付けて保存する。
 * 3. 左の「プロジェクトの設定（歯車）> スクリプト プロパティ」に次を追加する。
 *      LINE_CHANNEL_ACCESS_TOKEN … GitHub に登録済みの LINE のチャネルアクセストークン
 *      FEEDBACK_TOKEN            … 自分で決めた長いランダムな文字列（合言葉）
 *      LINE_GROUP_ID             … 通知先グループのID（GitHub の LINE_GROUP_ID と同じ）
 * 4. 「デプロイ > 新しいデプロイ > 種類: ウェブアプリ」で、
 *      次のユーザーとして実行: 自分 ／ アクセスできるユーザー: 全員
 *    としてデプロイし、表示された「ウェブアプリのURL」をコピーする。
 * 5. LINE Developers のチャネル設定「Messaging API設定」で、
 *      Webhook URL にそのURLを貼り付け、「Webhookの利用」をオンにする。
 * 6. GitHub リポジトリの Settings > Secrets and variables > Actions に Secret を追加する。
 *      FEEDBACK_URL = ウェブアプリのURL + "?token=" + FEEDBACK_TOKEN の値
 *
 * Apps Script では LINE の署名ヘッダーを読めないため、代わりに通知先グループからの
 * イベントだけを受け付け、記録の読み出しは合言葉（FEEDBACK_TOKEN）で守っている。
 */

const SHEET_NAME = '評価';
const MEMO_WINDOW_MS = 30 * 60 * 1000; // ❤️/✖ を押してから30分以内の「📝」メッセージをメモとして扱う
const ACTION_LABELS = { fav: '❤️お気に入り', reject: '✖却下' };

function doPost(e) {
  const props = PropertiesService.getScriptProperties();
  const groupId = props.getProperty('LINE_GROUP_ID');
  const events = JSON.parse(e.postData.contents).events || [];
  events.forEach(function (ev) {
    if (groupId && ev.source.groupId !== groupId) return;
    if (ev.type === 'postback') {
      handlePostback_(ev);
    } else if (ev.type === 'message' && ev.message.type === 'text') {
      handleMemo_(ev);
    }
  });
  return ContentService.createTextOutput('OK');
}

function handlePostback_(ev) {
  let data;
  try {
    data = JSON.parse(ev.postback.data);
  } catch (err) {
    return; // 物件カード以外のボタン
  }
  if (!ACTION_LABELS[data.a]) return;
  const sheet = sheet_();
  sheet.appendRow([new Date(), userOf_(ev), ACTION_LABELS[data.a], data.k, data.s, '']);
  PropertiesService.getScriptProperties().setProperty(
    'pending_' + userOf_(ev),
    JSON.stringify({ row: sheet.getLastRow(), at: Date.now() })
  );
  reply_(ev.replyToken, ACTION_LABELS[data.a] + 'として記録しました。\n理由やメモがあれば、そのまま送信してください。');
}

function handleMemo_(ev) {
  const text = ev.message.text;
  if (text.indexOf('📝') !== 0) return; // 普段の会話は記録しない
  const props = PropertiesService.getScriptProperties();
  const key = 'pending_' + userOf_(ev);
  const pending = JSON.parse(props.getProperty(key) || 'null');
  if (!pending || Date.now() - pending.at > MEMO_WINDOW_MS) return;
  const memo = text.replace(/^📝\s*(メモ|理由)?\s*[:：]?\s*/, '').trim();
  if (!memo) return;
  sheet_().getRange(pending.row, 6).setValue(memo);
  props.deleteProperty(key);
  reply_(ev.replyToken, '📝 メモを保存しました。次回からの提案に反映します。');
}

function doGet(e) {
  const token = PropertiesService.getScriptProperties().getProperty('FEEDBACK_TOKEN');
  if (!token || e.parameter.token !== token) {
    return ContentService.createTextOutput('forbidden');
  }
  const rows = sheet_().getDataRange().getValues().slice(1);
  const actions = { '❤️お気に入り': 'fav', '✖却下': 'reject' };
  const records = rows.map(function (r) {
    return { time: r[0], action: actions[r[2]] || r[2], key: r[3], summary: r[4], comment: r[5] };
  });
  return ContentService.createTextOutput(JSON.stringify(records)).setMimeType(ContentService.MimeType.JSON);
}

function sheet_() {
  const book = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = book.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = book.insertSheet(SHEET_NAME);
    sheet.appendRow(['日時', 'ユーザー', '評価', '物件ID', '物件', 'メモ']);
  }
  return sheet;
}

function userOf_(ev) {
  return ev.source.userId || ev.source.groupId || 'unknown';
}

function reply_(replyToken, text) {
  const token = PropertiesService.getScriptProperties().getProperty('LINE_CHANNEL_ACCESS_TOKEN');
  UrlFetchApp.fetch('https://api.line.me/v2/bot/message/reply', {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + token },
    payload: JSON.stringify({ replyToken: replyToken, messages: [{ type: 'text', text: text }] }),
    muteHttpExceptions: true,
  });
}
