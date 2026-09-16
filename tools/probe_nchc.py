"""
探測 NCHC 端點能力。

已確認:
  OK  client.audio.transcriptions.create 可用
  OK  language 參數
  OK  prompt 參數
  OK  wav 輸入
  OK  無明文速率限制

待確認:
  ?   模型清單裡有沒有 Breeze-ASR-25
      → 影響 S2-4 中文路由。沒有的話改用 large-v3-turbo，
        中英夾雜品質會下降但可用。
  ?   verbose_json 有沒有回 avg_logprob
      → 影響 S2-3 切早了的判定。沒有的話只能靠標點 + 時長。
"""
# TODO
