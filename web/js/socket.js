/**
 * WebSocket 連線、heartbeat、自動重連。
 *
 * ★ heartbeat 是必需品不是加分項:
 *   Cloudflare 對閒置的 WebSocket 約 100 秒就會斷線。
 *   使用者沉默兩分鐘，連線就死了。
 *   驗收要實測 —— 故意沉默 3 分鐘。
 *
 * ★ 零保存架構下，重連無法續接舊 session:
 *   伺服器記憶體一釋放就沒了。所以重連視為「新 session 接著往下寫」，
 *   前端自己那份 Store 才是完整的。
 */
const PING_MS = 30_000;
const TIMEOUT_MS = 90_000;

export class Socket {
  constructor({ onMessage, onState }) {
    this.onMessage = onMessage;
    this.onState = onState;
    this.ws = null;
    this.config = null;
    this.lastPong = 0;
    this.timer = null;
    this.closing = false;
  }

  connect(config) {
    this.config = config;
    this.closing = false;
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    this.ws = new WebSocket(`${proto}//${location.host}/ws`);
    this.ws.binaryType = 'arraybuffer';

    this.ws.onopen = () => {
      this.lastPong = Date.now();
      this.send({ type: 'start', ...this.config });
      this.startHeartbeat();
      this.onState('connected');
    };

    this.ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === 'pong') { this.lastPong = Date.now(); return; }
      this.onMessage(msg);
    };

    this.ws.onclose = () => {
      this.stopHeartbeat();
      if (this.closing) { this.onState('closed'); return; }
      this.onState('reconnecting');
      setTimeout(() => this.connect(this.config), 1000);
    };
  }

  startHeartbeat() {
    this.stopHeartbeat();
    this.timer = setInterval(() => {
      if (Date.now() - this.lastPong > TIMEOUT_MS) {
        // 沒回應了，主動斷掉讓 onclose 觸發重連。
        this.ws.close();
        return;
      }
      this.send({ type: 'ping' });
    }, PING_MS);
  }

  stopHeartbeat() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  send(obj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(obj));
    }
  }

  sendAudio(int16) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(int16.buffer);
    }
  }

  close() {
    this.closing = true;
    this.send({ type: 'stop' });
    this.stopHeartbeat();
    setTimeout(() => this.ws && this.ws.close(), 500);
  }
}
