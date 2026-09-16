/**
 * 組裝。
 *
 * 流程:
 *   選語言 → 按麥克風 → WebSocket + 麥克風
 *   → 伺服器切句 → NCHC 辨識 → upsert 推回 → 畫面更新
 *
 * ★ 按下麥克風之後語言整場鎖定。要換就停止再開新的 session。
 *   中途改的話 ASR 模型要換、VAD 狀態要重置，
 *   而且已辨識好的內容語言會對不上。
 *
 * ★ 術語清單（glossary）暫時不在介面上，但協定照送空陣列 ——
 *   之後要加回來不用動後端。
 */
import { AudioCapture } from './audio.js';
import { Socket } from './socket.js';
import { Store } from './store.js';
import { Renderer } from './render.js';
import { ScrollGate } from './scroll.js';

const $ = (id) => document.getElementById(id);

const store = new Store();
const renderer = new Renderer($('transcript'), $('caret'));
const gate = new ScrollGate($('transcript'), () => redraw(true));

let socket = null;
let capture = null;
let running = false;
let targetLang = 'en';
let lastHeard = 0;
let notice = false;
let silentTimer = null;

// ── 畫面 ──────────────────────────────────────────────────

function redraw(force = false) {
  if (!force && !gate.allow()) {
    $('jump-count').textContent = `${gate.queued} 則新內容`;
    $('jump').hidden = false;
    return;
  }
  $('jump').hidden = true;
  $('empty')?.remove();
  renderer.draw(store, targetLang);
  gate.stick();
}

function setStatus(text, live = false) {
  $('status').textContent = text;
  $('status').classList.toggle('live', live);
}

function setMic(state) {
  // idle | wait | live
  $('mic').dataset.state = state;
  $('mic').setAttribute('aria-label', state === 'idle' ? '開始錄音' : '停止錄音');
  if (state !== 'live') $('mic').style.setProperty('--level', 0);
}

// ── 開始 / 停止 ───────────────────────────────────────────

async function start() {
  targetLang = $('target-lang').value;
  const config = {
    source_lang: $('source-lang').value,
    target_lang: targetLang,
    glossary: [],
  };

  running = true;
  notice = false;
  setMic('wait');
  setStatus('連線中…');
  lockLangs(true);

  socket = new Socket({
    onMessage: (msg) => {
      if (msg.type === 'segment') {
        if (store.upsert(msg)) redraw();
      } else if (msg.type === 'speaking') {
        $('caret').hidden = !msg.active;
      } else if (msg.type === 'ready') {
        setMic('live');
        setStatus('聆聽中', true);
      } else if (msg.type === 'heard') {
        // 伺服器每 2 秒回報它聽到什麼。音訊完全沒進來時
        // 這個訊息根本不會出現 —— 這本身就是最有用的線索。
        lastHeard = Date.now();
        if (msg.rms < 0.002) {
          // 原始振幅幾乎是零 —— 麥克風沒在收音，不是 VAD 的問題
          setStatus('麥克風沒有收到聲音，請確認 Windows 的輸入裝置');
        } else if (msg.voiced_pct === 0) {
          setStatus('收得到聲音，但沒偵測到語音');
        } else if (running && !notice) {
          setStatus(msg.cuts ? '聆聽中' : '聆聽中…', true);
        }
      } else if (msg.type === 'notice') {
        notice = true;
        setStatus(msg.message);
      } else if (msg.type === 'error') {
        setStatus(msg.message || '連線發生問題');
        stop();
      }
    },
    onState: (s) => {
      if (s === 'reconnecting') { setMic('wait'); setStatus('重新連線…'); }
      if (s === 'closed' && running) stop();
    },
  });
  socket.connect(config);

  capture = new AudioCapture(
    (pcm) => socket.sendAudio(pcm),
    (level) => $('mic').style.setProperty('--level', Math.min(1, level * 6).toFixed(3)),
  );
  // 麥克風開了但一個 frame 都沒產生 —— 通常是 AudioWorklet
  // 沒被算圖路徑拉到。這種失敗完全不會報錯，只能自己偵測。
  capture.onSilent = () => setStatus('麥克風沒有輸出，請重新整理後再試一次');

  try {
    const info = await capture.start();
    // 讓伺服器 log 裡看得到取樣率和裝置，省得兩邊對不起來
    socket.send({ type: 'client', sample_rate: info.rate, device: info.device });
  } catch {
    setStatus('需要麥克風權限才能開始');
    stop();
    return;
  }

  // 伺服器每 2 秒會回報一次。超過 6 秒沒收到，表示音訊沒送到。
  lastHeard = Date.now();
  silentTimer = setInterval(() => {
    if (running && Date.now() - lastHeard > 6000) {
      setStatus('伺服器沒收到音訊，請檢查連線');
    }
  }, 2000);
}

function stop() {
  clearInterval(silentTimer);
  notice = false;
  if (capture) capture.stop();
  if (socket) socket.close();
  capture = socket = null;
  running = false;
  setMic('idle');
  setStatus(store.size ? '已停止' : '');
  $('caret').hidden = true;
  lockLangs(false);
}

function lockLangs(locked) {
  $('source-lang').disabled = locked;
  $('target-lang').disabled = locked;
}

// ── 事件 ──────────────────────────────────────────────────

$('mic').addEventListener('click', () => (running ? stop() : start()));
$('jump').addEventListener('click', () => { gate.flush(); gate.stick(); });

// 零保存：關掉分頁內容就沒了。S4 會加自動存檔與匯出。
window.addEventListener('beforeunload', (e) => {
  if (store.size > 0) { e.preventDefault(); e.returnValue = ''; }
});

setMic('idle');
