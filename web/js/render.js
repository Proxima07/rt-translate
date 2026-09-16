/**
 * 畫面繪製。
 *
 * ★ 每個 segment 都帶 lang 屬性。
 *   中文和日文共用漢字但字形不同（例如「直」「海」的寫法）。
 *   不標語言的話瀏覽器會用字體堆疊裡第一個有該字的字體，
 *   在中日混雜的畫面上看得出來哪裡不對。
 *
 * ★ 為什麼講話時不顯示草稿文字:
 *   要即時顯示就得在本地跑小模型，而 tiny/base 的中日文品質是真的差 ——
 *   會產出「看起來像句子但完全不是那個意思」的字。
 *   給錯誤資訊比沒有資訊更糟。
 *   所以講話時只有插入點游標在閃，告訴你字要出現在哪裡。
 */
const LANG_TAG = { zh: 'zh-Hant', en: 'en', ja: 'ja' };

export class Renderer {
  constructor(el, caret) {
    this.el = el;
    this.caret = caret;
  }

  draw(store, targetLang) {
    const nodes = store.ordered().map((s) => this.node(s, targetLang));
    this.el.replaceChildren(...nodes, this.caret);
  }

  node(s, targetLang) {
    const div = document.createElement('div');
    div.className = `seg ${(s.layer || 'ASR').toLowerCase()}`;
    div.dataset.id = s.id;
    div.dataset.rev = s.rev;

    const src = document.createElement('div');
    src.className = 'src';
    src.lang = LANG_TAG[s.lang] || LANG_TAG[s.source_lang] || '';
    src.textContent = s.text || '';
    div.appendChild(src);

    if (s.translation) {
      const dst = document.createElement('div');
      dst.className = 'dst';
      dst.lang = LANG_TAG[targetLang] || '';
      dst.textContent = s.translation;
      div.appendChild(dst);
    }
    return div;
  }
}
