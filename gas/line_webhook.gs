/**
 * 賃貸物件通知の LINE ボット（Google Apps Script・無料）。
 * - 通知カードの ❤️お気に入り / ✖却下 / 💔外す とメモを、このスプレッドシートに記録する
 * - 「お気に入り」… お気に入りの一覧（掲載終了なら印付き）。💔で一覧から外せる
 * - 「最新の物件」… 直近に通知した物件のカード
 * - 「条件」… 通知する条件（家賃・徒歩・面積・築年数・間取り・エリア）の確認と変更
 * リポジトリは公開なので、メモはここにだけ置く。物件の情報は公開リポジトリの data/ から読む。
 *
 * ■ 設定手順
 * 1. Google スプレッドシートを新規作成し、メニュー「拡張機能 > Apps Script」を開く。
 * 2. このファイルの内容をすべて貼り付けて保存する。
 * 3. 左の「プロジェクトの設定（歯車）> スクリプト プロパティ」に次を追加する。
 *      LINE_CHANNEL_ACCESS_TOKEN … GitHub に登録済みの LINE のチャネルアクセストークン
 *      FEEDBACK_TOKEN            … 自分で決めた長いランダムな文字列（合言葉）
 *      LINE_GROUP_ID             … 通知先グループのID（GitHub の LINE_GROUP_ID と同じ）
 * 4. 関数「setup」を選んで実行し、権限を許可する（毎朝の掲載確認が登録される）。
 * 5. 「デプロイ > 新しいデプロイ > 種類: ウェブアプリ」で、
 *      次のユーザーとして実行: 自分 ／ アクセスできるユーザー: 全員
 *    としてデプロイし、表示された「ウェブアプリのURL」をコピーする。
 * 6. LINE Developers のチャネル設定「Messaging API設定」で、
 *      Webhook URL にそのURLを貼り付け、「Webhookの利用」をオンにする。
 * 7. GAS_URL = ウェブアプリのURL + "?token=" + FEEDBACK_TOKEN の値 を、次の2か所に登録する。
 *      - GitHub リポジトリの Settings > Secrets and variables > Actions の Secret「GAS_URL」
 *        （LINE で変えた条件を毎日の収集が読む）
 *      - Claude Code のクラウド環境「いえたすく」の環境変数「GAS_URL」。ネットワークアクセスで
 *        script.google.com と script.googleusercontent.com も許可する（毎日のAI整理が評価履歴を読む）
 *
 * Apps Script では LINE の署名ヘッダーを読めないため、代わりに通知先グループからの
 * イベントだけを受け付け、記録の読み出しは合言葉（FEEDBACK_TOKEN）で守っている。
 */

const DATA_BASE = 'https://raw.githubusercontent.com/Senridogs/searchMyHome/claude/check-rental-listings-9OMi0/data/';
const SHEET_NAME = '評価';
const HEADER = ['日時', 'ユーザー', '評価', '物件ID', '物件', 'メモ', 'URL', '物件名', '詳細', '掲載状況', '確認日'];
const COL = { TIME: 1, USER: 2, ACTION: 3, KEY: 4, SUMMARY: 5, MEMO: 6, URL: 7, TITLE: 8, DETAILS: 9, STATUS: 10, CHECKED: 11 };
const ACTION_LABELS = { fav: '❤️お気に入り', reject: '✖却下', unfav: '💔取り消し' };
const MEMO_WINDOW_MS = 30 * 60 * 1000; // ❤️/✖ を押してから30分以内の「📝」メッセージをメモとして扱う
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';

// settings.py と同じ既定値と範囲（各サイトの検索が家賃22万円・徒歩15分・40㎡までを集めている）
const DEFAULT_SETTINGS = { max_rent: 190000, max_walk: 10, min_area: 45, max_age: 50, min_rooms: 2, add_stations: [], avoid_stations: [] };
const LIMITS = { max_rent: [50000, 220000], max_walk: [1, 15], min_area: [40, 200], max_age: [1, 100], min_rooms: [2, 4] };

// 物件ページの本文（script/style を除く）にこれがあれば掲載終了とみなす
const ENDED_PATTERN = /掲載(が|を)?終了|公開(を|が)?終了|募集(を|は|が)?終了|お探しの(物件|ページ)は(見つかりません|存在しません|削除)|この物件は(現在)?(ご覧いただけません|掲載されていません|公開されていません)/;

/* ───────── Webhook ───────── */

function doPost(e) {
  const groupId = PropertiesService.getScriptProperties().getProperty('LINE_GROUP_ID');
  const events = JSON.parse(e.postData.contents).events || [];
  events.forEach(function (ev) {
    if (groupId && ev.source.groupId !== groupId) return;
    if (ev.type === 'postback') {
      handlePostback_(ev);
    } else if (ev.type === 'message' && ev.message.type === 'text') {
      handleText_(ev);
    }
  });
  return ContentService.createTextOutput('OK');
}

function doGet(e) {
  const token = PropertiesService.getScriptProperties().getProperty('FEEDBACK_TOKEN');
  if (!token || e.parameter.token !== token) {
    return ContentService.createTextOutput('forbidden');
  }
  const body = e.parameter.type === 'settings' ? loadSettings_() : feedbackRecords_();
  return ContentService.createTextOutput(JSON.stringify(body)).setMimeType(ContentService.MimeType.JSON);
}

/* ───────── ❤️ / ✖ / 💔 ───────── */

function handlePostback_(ev) {
  let data;
  try {
    data = JSON.parse(ev.postback.data);
  } catch (err) {
    return; // 物件カード以外のボタン
  }
  if (!ACTION_LABELS[data.a] || !data.k) return;
  const sheet = sheet_();
  const row = findRow_(sheet, data.k);

  if (data.a === 'unfav') {
    if (row) sheet.getRange(row, COL.ACTION).setValue(ACTION_LABELS.unfav);
    reply_(ev.replyToken, [text_('💔 お気に入りから外しました。')]);
    return;
  }

  let target = row;
  if (target) {
    sheet.getRange(target, COL.TIME, 1, 3).setValues([[new Date(), userOf_(ev), ACTION_LABELS[data.a]]]);
  } else {
    const info = notifiedListing_(data.k) || {};
    sheet.appendRow([new Date(), userOf_(ev), ACTION_LABELS[data.a], data.k, data.s || '', '',
                     info.url || '', info.title || '', info.details || '', '', '']);
    target = sheet.getLastRow();
  }
  PropertiesService.getScriptProperties().setProperty(
    'pending_' + userOf_(ev), JSON.stringify({ row: target, at: Date.now() }));
  reply_(ev.replyToken, [text_(ACTION_LABELS[data.a] + 'として記録しました。\n理由やメモがあれば、そのまま送信してください。')]);
}

function findRow_(sheet, key) {
  const keys = sheet.getRange(1, COL.KEY, sheet.getLastRow(), 1).getValues();
  for (let i = keys.length - 1; i >= 1; i--) {
    if (keys[i][0] === key) return i + 1;
  }
  return 0;
}

function notifiedListing_(key) {
  const all = fetchJson_('notified.json');
  return all ? all[key] : null;
}

/* ───────── 話しかけ ───────── */

function handleText_(ev) {
  const raw = ev.message.text.trim();
  if (raw.indexOf('📝') === 0) {
    saveMemo_(ev, raw);
    return;
  }
  const text = raw.normalize('NFKC').replace(/\s+/g, ' ');
  const messages = command_(text);
  if (messages) reply_(ev.replyToken, messages);
}

function saveMemo_(ev, text) {
  const props = PropertiesService.getScriptProperties();
  const key = 'pending_' + userOf_(ev);
  const pending = JSON.parse(props.getProperty(key) || 'null');
  if (!pending || Date.now() - pending.at > MEMO_WINDOW_MS) return;
  const memo = text.replace(/^📝\s*(メモ|理由)?\s*[:：]?\s*/, '').trim();
  if (!memo) return;
  sheet_().getRange(pending.row, COL.MEMO).setValue(memo);
  props.deleteProperty(key);
  reply_(ev.replyToken, [text_('📝 メモを保存しました。次回からの提案に反映します。')]);
}

/** Returns reply messages for a command, or null for ordinary chat (ignored). */
function command_(text) {
  if (text.length > 30) return null;
  if (/^(お気に入り|いいね)(一覧)?(を?(見せて|教えて))?$/.test(text)) return favoritesMessages_();
  if (/最新/.test(text) && /物件|新着|最新$/.test(text)) return latestMessages_();
  if (/^(ヘルプ|使い方|help)$/i.test(text)) return [text_(HELP_TEXT)];
  if (/^条件(を?(見せて|教えて)|確認|一覧)?$/.test(text)) return [settingsMessage_()];
  if (text === '条件リセット') {
    saveSettings_(JSON.parse(JSON.stringify(DEFAULT_SETTINGS)));
    return [settingsMessage_('条件を最初の状態に戻しました。')];
  }
  const choice = CHOICES[text];
  if (choice) return [text_(choice.prompt, choice.items)];
  return changeSetting_(text);
}

const HELP_TEXT = [
  '使い方',
  '・「お気に入り」… ❤️を付けた物件の一覧（💔で外せます）',
  '・「最新の物件」… 直近に通知した物件',
  '・「条件」… 通知する条件の確認と変更',
  '・通知カードの❤️/✖を押したあと「📝メモ: …」で理由を残せます',
].join('\n');

const CHOICES = {
  '家賃': { prompt: '家賃の上限（管理費込み）を選んでください。', items: [15, 16, 17, 18, 19, 20, 21, 22].map(function (v) { return [v + '万円', '家賃 ' + v]; }) },
  '徒歩': { prompt: '駅徒歩の上限を選んでください。', items: [5, 7, 10, 12, 15].map(function (v) { return [v + '分', '徒歩 ' + v]; }) },
  '面積': { prompt: '専有面積の下限を選んでください。', items: [40, 45, 50, 55, 60, 70].map(function (v) { return [v + '㎡', '面積 ' + v]; }) },
  '築年数': { prompt: '築年数の上限を選んでください。', items: [10, 20, 30, 40, 50].map(function (v) { return [v + '年', '築年数 ' + v]; }) },
  '間取り': { prompt: '間取りを選んでください。', items: [2, 3, 4].map(function (v) { return [v + 'LDK以上', '間取り ' + v]; }) },
  'エリア': { prompt: '「エリア追加 吉祥寺」で希望エリアに追加、「エリア除外 〇〇」で通知しないエリアに、「エリア解除 〇〇」で元に戻します（駅名・区市名）。', items: [] },
};

function changeSetting_(text) {
  const s = loadSettings_();
  let m;
  let done = '';
  if ((m = text.match(/^(?:家賃|賃料)\s*([\d.]+)\s*万?円?$/))) {
    const yen = Math.round(parseFloat(m[1]) * 10000);
    if (!inRange_('max_rent', yen)) return [text_('家賃は5万〜22万円の範囲で指定してください（各サイトの検索が22万円までのため）。')];
    s.max_rent = yen;
    done = '家賃の上限を' + yen / 10000 + '万円にしました。';
  } else if ((m = text.match(/^(?:駅?徒歩)\s*(\d+)\s*分?$/))) {
    const v = parseInt(m[1], 10);
    if (!inRange_('max_walk', v)) return [text_('駅徒歩は1〜15分の範囲で指定してください。')];
    s.max_walk = v;
    done = '駅徒歩を' + v + '分以内にしました。';
  } else if ((m = text.match(/^(?:面積|広さ|専有面積)\s*(\d+)\s*(?:㎡|m2)?$/))) {
    const v = parseInt(m[1], 10);
    if (!inRange_('min_area', v)) return [text_('面積は40㎡以上で指定してください（各サイトの検索が40㎡からのため）。')];
    s.min_area = v;
    done = '面積を' + v + '㎡以上にしました。';
  } else if ((m = text.match(/^(?:築年数|築)\s*(\d+)\s*年?$/))) {
    const v = parseInt(m[1], 10);
    if (!inRange_('max_age', v)) return [text_('築年数は1〜100年の範囲で指定してください。')];
    s.max_age = v;
    done = '築年数を' + v + '年以内にしました。';
  } else if ((m = text.match(/^間取り\s*([2-4])\s*(?:LDK)?(?:以上)?$/i))) {
    s.min_rooms = parseInt(m[1], 10);
    done = '間取りを' + s.min_rooms + 'LDK以上にしました。';
  } else if ((m = text.match(/^エリア(追加|除外|解除)\s*(.+)$/))) {
    const name = m[2].trim().replace(/駅$/, '');
    s.add_stations = s.add_stations.filter(function (x) { return x !== name; });
    s.avoid_stations = s.avoid_stations.filter(function (x) { return x !== name; });
    if (m[1] === '追加') s.add_stations.push(name);
    if (m[1] === '除外') s.avoid_stations.push(name);
    done = { '追加': '「' + name + '」を希望エリアに追加しました。', '除外': '「' + name + '」を通知しないエリアにしました。', '解除': '「' + name + '」の設定を元に戻しました。' }[m[1]];
  } else {
    return null;
  }
  saveSettings_(s);
  return [settingsMessage_(done)];
}

function inRange_(key, v) {
  return !isNaN(v) && v >= LIMITS[key][0] && v <= LIMITS[key][1];
}

function settingsMessage_(lead) {
  const s = loadSettings_();
  const lines = [
    lead ? lead + '\n' : '',
    '⚙️ 現在の条件',
    '・家賃: ' + s.max_rent / 10000 + '万円以下（管理費込み）',
    '・駅徒歩: ' + s.max_walk + '分以内',
    '・面積: ' + s.min_area + '㎡以上',
    '・築年数: ' + s.max_age + '年以内',
    '・間取り: ' + s.min_rooms + 'LDK以上',
    '・追加エリア: ' + (s.add_stations.join('、') || 'なし'),
    '・除外エリア: ' + (s.avoid_stations.join('、') || 'なし'),
    '',
    '変える項目をボタンで選ぶか、「家賃 20」のように送ってください。変更は次の収集（毎日17時）から反映されます。',
  ];
  const items = Object.keys(CHOICES).map(function (k) { return [k, k]; }).concat([['最初に戻す', '条件リセット']]);
  return text_(lines.join('\n').trim(), items);
}

function loadSettings_() {
  const saved = JSON.parse(PropertiesService.getScriptProperties().getProperty('SETTINGS') || '{}');
  const s = JSON.parse(JSON.stringify(DEFAULT_SETTINGS));
  Object.keys(s).forEach(function (k) { if (saved[k] !== undefined) s[k] = saved[k]; });
  return s;
}

function saveSettings_(s) {
  PropertiesService.getScriptProperties().setProperty('SETTINGS', JSON.stringify(s));
}

/* ───────── お気に入り一覧・最新の物件 ───────── */

function favoritesMessages_() {
  const rows = sheet_().getDataRange().getValues().slice(1)
    .filter(function (r) { return r[COL.ACTION - 1] === ACTION_LABELS.fav; })
    .reverse();
  if (!rows.length) return [text_('まだお気に入りはありません。通知カードの❤️を押すと登録されます。')];
  const shown = rows.slice(0, 48);
  const ended = rows.filter(function (r) { return r[COL.STATUS - 1] === '掲載終了'; }).length;
  const messages = [text_('❤️ お気に入り ' + rows.length + '件' + (ended ? '（うち掲載終了 ' + ended + '件）' : '') +
                          (shown.length < rows.length ? '\n新しい順に' + shown.length + '件を表示しています。' : ''))];
  for (let i = 0; i < shown.length; i += 12) {
    messages.push({
      type: 'flex',
      altText: 'お気に入りの物件',
      contents: { type: 'carousel', contents: shown.slice(i, i + 12).map(favoriteCard_) },
    });
  }
  return messages;
}

function favoriteCard_(r) {
  const status = r[COL.STATUS - 1];
  const title = r[COL.TITLE - 1] || String(r[COL.SUMMARY - 1]).split(' / ')[0] || '物件';
  const body = [
    { type: 'text', size: 'xs', weight: 'bold',
      text: status === '掲載終了' ? '⚠️ 掲載終了' : (status === '掲載中' ? '✅ 掲載中' : '❔ 掲載状況の確認前'),
      color: status === '掲載終了' ? '#D93025' : '#1E8E3E' },
    { type: 'text', text: String(title), weight: 'bold', size: 'md', wrap: true, maxLines: 2 },
    { type: 'text', text: String(r[COL.DETAILS - 1] || r[COL.SUMMARY - 1] || ' '), size: 'sm', wrap: true, color: '#555555' },
  ];
  if (r[COL.MEMO - 1]) body.push({ type: 'text', text: '📝 ' + r[COL.MEMO - 1], size: 'xs', wrap: true, color: '#888888' });
  const footer = [];
  if (/^https?:\/\//.test(r[COL.URL - 1])) {
    footer.push({ type: 'button', style: 'primary', height: 'sm', action: { type: 'uri', label: '詳細を見る', uri: r[COL.URL - 1] } });
  }
  footer.push({ type: 'button', style: 'secondary', height: 'sm',
                action: { type: 'postback', label: '💔 お気に入りから外す', displayText: '💔 ' + title,
                          data: JSON.stringify({ a: 'unfav', k: r[COL.KEY - 1] }) } });
  return {
    type: 'bubble', size: 'kilo',
    body: { type: 'box', layout: 'vertical', spacing: 'sm', contents: body },
    footer: { type: 'box', layout: 'vertical', spacing: 'xs', contents: footer },
  };
}

function latestMessages_() {
  const latest = fetchJson_('latest_messages.json');
  if (!latest || !latest.messages || !latest.messages.length) return [text_('まだ通知した物件がありません。')];
  const messages = latest.messages.slice(0, 5);
  messages[0] = text_('📋 最新の通知（' + latest.date + '）' + latest.count + '件\n気になる物件は❤️、合わない物件は✖を押してください。');
  return messages;
}

/* ───────── 掲載確認（毎朝） ───────── */

function setup() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'checkFavorites') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('checkFavorites').timeBased().everyDays(1).atHour(7).create();
  sheet_();
}

function checkFavorites() {
  const sheet = sheet_();
  const rows = sheet.getDataRange().getValues();
  for (let i = 1; i < rows.length; i++) {
    const url = rows[i][COL.URL - 1];
    if (rows[i][COL.ACTION - 1] !== ACTION_LABELS.fav || !/^https?:\/\//.test(url)) continue;
    const status = listingStatus_(url);
    if (status) sheet.getRange(i + 1, COL.STATUS, 1, 2).setValues([[status, new Date()]]);
    Utilities.sleep(1000);
  }
}

/** '掲載中' / '掲載終了', or '' when the page could not be checked. */
function listingStatus_(url) {
  let target = url;
  for (let hop = 0; hop < 3; hop++) {
    let res;
    try {
      res = UrlFetchApp.fetch(target, { muteHttpExceptions: true, followRedirects: false, headers: { 'User-Agent': UA } });
    } catch (err) {
      return '';
    }
    const code = res.getResponseCode();
    if (code === 404 || code === 410) return '掲載終了';
    if (code >= 300 && code < 400) {
      const headers = res.getHeaders();
      const loc = headers.Location || headers.location;
      if (!loc) return '';
      const next = /^https?:/.test(loc) ? loc : target.match(/^https?:\/\/[^\/]+/)[0] + loc;
      // A listing that only moved keeps its id; a jump to a top or search page means it ended
      if (next.indexOf(listingId_(target)) < 0) return '掲載終了';
      target = next;
      continue;
    }
    if (code !== 200) return '';
    const visible = res.getContentText().replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi, ' ').replace(/<[^>]+>/g, ' ');
    return ENDED_PATTERN.test(visible) ? '掲載終了' : '掲載中';
  }
  return '';
}

function listingId_(url) {
  return url.split('?')[0].replace(/\/$/, '').split('/').pop();
}

/* ───────── 共通 ───────── */

function feedbackRecords_() {
  const codes = {};
  Object.keys(ACTION_LABELS).forEach(function (k) { codes[ACTION_LABELS[k]] = k; });
  return sheet_().getDataRange().getValues().slice(1).map(function (r) {
    return { time: r[COL.TIME - 1], action: codes[r[COL.ACTION - 1]] || r[COL.ACTION - 1],
             key: r[COL.KEY - 1], summary: r[COL.SUMMARY - 1], comment: r[COL.MEMO - 1] };
  });
}

function fetchJson_(name) {
  try {
    const res = UrlFetchApp.fetch(DATA_BASE + name + '?t=' + Date.now(), { muteHttpExceptions: true });
    return res.getResponseCode() === 200 ? JSON.parse(res.getContentText()) : null;
  } catch (err) {
    return null;
  }
}

function sheet_() {
  const book = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = book.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = book.insertSheet(SHEET_NAME);
    sheet.appendRow(HEADER);
  } else if (sheet.getLastColumn() < HEADER.length) {
    sheet.getRange(1, 1, 1, HEADER.length).setValues([HEADER]);
  }
  return sheet;
}

function userOf_(ev) {
  return ev.source.userId || ev.source.groupId || 'unknown';
}

/** A text message, optionally with quick-reply buttons given as [label, text] pairs. */
function text_(text, items) {
  const message = { type: 'text', text: text };
  if (items && items.length) {
    message.quickReply = {
      items: items.slice(0, 13).map(function (it) {
        return { type: 'action', action: { type: 'message', label: String(it[0]).slice(0, 20), text: it[1] } };
      }),
    };
  }
  return message;
}

function reply_(replyToken, messages) {
  const token = PropertiesService.getScriptProperties().getProperty('LINE_CHANNEL_ACCESS_TOKEN');
  UrlFetchApp.fetch('https://api.line.me/v2/bot/message/reply', {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + token },
    payload: JSON.stringify({ replyToken: replyToken, messages: messages.slice(0, 5) }),
    muteHttpExceptions: true,
  });
}
