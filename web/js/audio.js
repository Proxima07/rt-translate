// getUserMedia → AudioWorklet → 16kHz mono Int16 PCM → socket
// 不要用已棄用的 ScriptProcessorNode。

export class AudioCapture {
  constructor(onChunk, onLevel) {
    this.onChunk = onChunk;
    this.onLevel = onLevel;
    this.ctx = null;
    this.stream = null;
    this.frames = 0;
    this.deviceLabel = '';
  }

  async start() {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    const track = this.stream.getAudioTracks()[0];
    this.deviceLabel = track ? track.label : '';

    // ★ 不指定 sampleRate。讓 AudioContext 用硬體原生取樣率，
    //   重採樣交給 worklet 自己做 —— 見 pcm-processor.js 的說明。
    this.ctx = new AudioContext();
    if (this.ctx.state === 'suspended') await this.ctx.resume();

    await this.ctx.audioWorklet.addModule('/js/worklet/pcm-processor.js');

    const src = this.ctx.createMediaStreamSource(this.stream);
    const node = new AudioWorkletNode(this.ctx, 'pcm-processor');
    node.port.onmessage = (e) => {
      if (e.data && e.data.hello) {
        console.info('[rt] AudioContext', e.data.hello, 'Hz ·', this.deviceLabel);
        return;
      }
      const pcm = new Int16Array(e.data);
      this.frames++;
      this.onChunk(pcm);
      if (this.onLevel) this.onLevel(rms(pcm));
    };

    // ★ AudioWorkletNode 必須在通往 destination 的算圖路徑上，
    //   process() 才會被呼叫。只做 src.connect(node) 而不往下接的話，
    //   瀏覽器不會拉這個節點，port.onmessage 一次都不會觸發。
    //   gain=0 讓它在路徑上但不從喇叭放出自己的聲音。
    this.sink = this.ctx.createGain();
    this.sink.gain.value = 0;
    src.connect(node);
    node.connect(this.sink);
    this.sink.connect(this.ctx.destination);

    this.watchdog = setTimeout(() => {
      if (this.frames === 0 && this.onSilent) this.onSilent();
    }, 3000);

    return { rate: this.ctx.sampleRate, device: this.deviceLabel };
  }

  stop() {
    clearTimeout(this.watchdog);
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    if (this.ctx) this.ctx.close();
    this.stream = null;
    this.ctx = null;
  }
}

function rms(pcm) {
  let sum = 0;
  for (let i = 0; i < pcm.length; i++) sum += pcm[i] * pcm[i];
  return Math.sqrt(sum / pcm.length) / 32768;
}
