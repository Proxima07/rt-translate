/**
 * 捲動控制。
 *
 * 內容會一直往下長。但使用者往上捲去看前面的內容時，
 * 畫面不該在他眼前跳動 —— 而三層翻譯都會回頭改已顯示的句子，
 * 不管的話會很難讀。
 *
 * 規則:
 *   在底部   → 照常更新，並黏在底部
 *   捲上去了 → 更新照收（Store 是真實來源），但不重畫；
 *              顯示一個「N 則新內容」讓他一鍵回到底部
 */
const NEAR_BOTTOM_PX = 72;

export class ScrollGate {
  constructor(el, onFlush) {
    this.el = el;
    this.onFlush = onFlush;
    this.queued = 0;
    el.addEventListener('scroll', () => {
      if (this.atBottom() && this.queued > 0) this.flush();
    }, { passive: true });
  }

  atBottom() {
    const { scrollTop, clientHeight, scrollHeight } = this.el;
    return scrollHeight - (scrollTop + clientHeight) < NEAR_BOTTOM_PX;
  }

  /** true = 可以立刻重畫；false = 已計入佇列 */
  allow() {
    if (this.atBottom()) return true;
    this.queued++;
    return false;
  }

  flush() {
    this.queued = 0;
    this.onFlush();
  }

  stick() {
    this.el.scrollTop = this.el.scrollHeight;
  }
}
