/**
 * ★ S2 的核心：upsert，不是 append。
 *
 * 伺服器推回來的訊息不是「附加一句」，是「依 id 覆寫一句」。
 * 同一句話的典型生命週期:
 *
 *     rev 1  layer=ASR   原文
 *     rev 2  layer=L1    ＋譯文          (S3)
 *     rev 3  layer=L2    譯文改好         (S3)
 *     rev 4  layer=L3    被合併進別的 id  (S5)
 *
 * ★ 零保存架構下，這個 Map 是整份逐字稿唯一的真實來源。
 *   伺服器記憶體斷線即釋放，什麼都不留。
 */
export class Store {
  constructor() {
    this.map = new Map();
  }

  /**
   * 回傳 { added, updated, removed } 供 render 決定怎麼動畫。
   * 訊息被判定為過期時回傳 null。
   */
  upsert(msg) {
    const removed = [];

    // ① replaces：L3 合併句子時，舊的那幾個要整個拿掉。
    //    沒有這步的話畫面上會留下鬼影 —— 合併後的新句出現了，
    //    但被合併的舊句還在。
    for (const id of msg.replaces || []) {
      if (this.map.delete(id)) removed.push(id);
    }

    // ② rev 檢查：收到比現有更舊的直接丟棄。
    //    網路亂序時沒有這一步，症狀是「字改好了又變回錯的」，
    //    偶發、難重現、難查。
    const cur = this.map.get(msg.id);
    if (cur && cur.rev >= msg.rev) {
      return removed.length ? { added: [], updated: [], removed } : null;
    }

    this.map.set(msg.id, msg);
    return {
      added: cur ? [] : [msg.id],
      updated: cur ? [msg.id] : [],
      removed,
    };
  }

  /** 依時間排序。合併過的句子時間範圍會變，所以每次都重排。 */
  ordered() {
    return [...this.map.values()].sort((a, b) => a.t_start - b.t_start);
  }

  get size() {
    return this.map.size;
  }

  clear() {
    this.map.clear();
  }
}
