/**
 * AudioWorklet processor — 輸出 16kHz mono Int16 PCM。
 *
 * ★ 必須是獨立檔案。AudioWorklet 用 URL 載入:
 *     await ctx.audioWorklet.addModule('/js/worklet/pcm-processor.js');
 *   它跑在另一個全域環境裡，不能 import 主執行緒的東西。
 *
 * ★ 不強制 AudioContext 的取樣率。
 *   本來是用 new AudioContext({sampleRate: 16000}) 讓這裡不用重採樣，
 *   但 Windows 上硬體多半是 48kHz，Chrome 會插一層自己的重採樣，
 *   某些 WASAPI 設定下那條路徑會吐出一片零 —— 而且完全不報錯。
 *   改成吃硬體原生取樣率，在這裡自己降。
 *
 * ★ 降採樣用箱型平均（box filter），不是點取樣。
 *   48k → 16k 直接每三個取一個的話，8kHz 以上的能量會混疊折回來，
 *   變成聽不見但 VAD 和 Whisper 看得到的雜訊。
 *   把每個輸出樣本涵蓋範圍內的來源樣本平均掉就沒這問題，成本幾乎是零。
 */
const TARGET_RATE = 16000;
const CHUNK = 512;              // 512 sample @16k = 32ms，Silero 的固定要求

class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / TARGET_RATE;   // sampleRate 是 worklet 全域
    this.buf = new Float32Array(CHUNK);
    this.n = 0;
    this.pos = 0;               // 下一個輸出樣本在來源上的位置
    this.carry = 0;             // 跨 buffer 的累加
    this.carryN = 0;
    this.port.postMessage({ hello: sampleRate });
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;

    if (this.ratio === 1) {
      for (let i = 0; i < ch.length; i++) this.push(ch[i]);
      return true;
    }

    // 箱型平均降採樣，同時處理整數與非整數比率（48k→3、44.1k→2.756）
    let p = this.pos;
    while (p < ch.length) {
      const end = p + this.ratio;
      let sum = this.carry;
      let n = this.carryN;
      this.carry = 0;
      this.carryN = 0;

      for (let i = Math.max(0, Math.ceil(p)); i < Math.min(ch.length, end); i++) {
        sum += ch[i];
        n++;
      }

      if (end > ch.length) {
        // 這個輸出樣本跨到下一個 buffer，先存起來
        this.carry = sum;
        this.carryN = n;
        this.pos = p - ch.length;
        return true;
      }
      this.push(n ? sum / n : 0);
      p = end;
    }
    this.pos = p - ch.length;
    return true;
  }

  push(sample) {
    this.buf[this.n++] = sample;
    if (this.n < CHUNK) return;

    // Float32 [-1,1] → Int16
    const out = new Int16Array(CHUNK);
    for (let i = 0; i < CHUNK; i++) {
      const s = Math.max(-1, Math.min(1, this.buf[i]));
      out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    this.port.postMessage(out.buffer, [out.buffer]);
    this.n = 0;
  }
}

registerProcessor('pcm-processor', PCMProcessor);
