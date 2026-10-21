# 寫未？

> 「寫未？」是台語的「寫了沒？」——就像長輩問「食飽未？」一樣，每天問你雅思題目寫了沒。

每天用 LINE 盯你做雅思哥的題目，交題目給 Claude 批改錯題，偷懶就懲罰。

- **提醒**：早上告訴你今日目標，晚上沒做完再警告一次
- **批改**：貼上題目＋你的答案＋正確答案 → 錯誤類型分析、原文定位、下次怎麼做；寫作/口說給預估分數與改寫
- **錯題本**：依書本／Test／Part／錯誤類型篩選，每篇一張卡片，搞懂了就標記
- **已做題目**：所有提交一覽，可篩選、看錯題、刪除交錯的
- **手動修正**：Claude 判錯可以改成答對／答錯、改答案、補漏批的題目、改科目或出處，分數與當天進度自動更新
- **寫作工具書**：Academic Task 1／Task 2 題型、數據用語、連接詞（可搜尋）
- **懲罰（可各自開關）**：連續紀錄歸零＋欠債累積、群組公開羞恥、罰金記帳、截止後升級轟炸
- **防反悔**：開啟懲罰立即生效；關閉或放寬要等 24 小時
- **請假**：每月 N 次，生病或真的很忙時用

## 1. 建立 LINE 機器人

1. 到 [LINE Developers](https://developers.line.biz/console/) 建立 Provider → 建立 **Messaging API** channel（會同時建立 LINE 官方帳號）
2. Basic settings 複製 **Channel secret**
3. Messaging API 分頁 → 發行 **Channel access token (long-lived)**
4. 到 [LINE Official Account Manager](https://manager.line.biz/) → 回應設定：**關閉「自動回應訊息」**、**開啟 Webhook**；帳號設定開啟「允許加入群組」
5. 查看你方案的每月免費訊息數，填到網頁設定的「LINE 每月推播上限」（預設 200）。回覆訊息不算額度，只有主動推播會算，群組推播按人數計算

## 2. 先在 localhost 測試

```bash
uv sync                 # 安裝依賴（含開發用的 pytest）
cp .env.example .env    # 填 LINE 金鑰、ANTHROPIC_API_KEY、WEB_PASSWORD；BASE_URL 先填 http://localhost:8000
uv run --env-file .env uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- 打開 http://localhost:8000 登入，到「交題目」貼一篇測試批改
- 要測 LINE：另開終端機跑 `cloudflared tunnel --url http://localhost:8000`（臨時網址），把 `https://xxx.trycloudflare.com/callback` 填到 LINE 的 Webhook URL → Verify，再用手機傳 `綁定 密碼`
- 想快速測提醒/結算：到設定把早上提醒、截止、結算時間改成幾分鐘後（排程每分鐘檢查一次）
- 測試資料在 `data/app.db`，上主機前刪掉即可重來

## 3. 部署到你的伺服器

```bash
cp .env.example .env    # BASE_URL 改成 tunnel 的正式網址
docker compose up -d --build
```

要換 port 就在 `.env` 加 `PORT=8067`，容器內外都會用這個 port，不用改 `Dockerfile` 或 `docker-compose.yml`。

服務只監聽 `127.0.0.1:8000`，不對外開埠。用你的 tunnel 把 `http://127.0.0.1:8000` 對外開放（例如 Cloudflare Tunnel 的 ingress 指向它），然後到 LINE Developers → Messaging API → Webhook URL 填 `https://你的網址/callback` → 按 **Verify**。

## 4. 開始使用

1. 手機掃 QR code 加機器人好友，傳 `綁定 你的WEB_PASSWORD`
2. 用瀏覽器開 `https://你的網址`，登入後到「設定」調整每日目標、時間、懲罰
3. iPhone Safari 開網頁 → 分享 → 「加入主畫面」，就像一個 App
4. 想要公開羞恥：建一個有朋友的 LINE 群組，把機器人拉進去，你在群組傳 `監督群組`

### LINE 指令

| 指令 | 說明 |
|---|---|
| （傳截圖） | 先存著，等你下「交」指令 |
| `交 閱讀` | 批改剛剛傳的截圖（聽力 / 閱讀 / 寫作 / 口說） |
| `交 閱讀`＋換行＋文字 | 批改貼上的文字（有截圖也會一起用） |
| `補 37 NO 38 NG` | 補上答案（複製文字時選擇題勾選會消失、漏批的題目），會補到最近一份有這些題號的提交 |
| `清除` | 丟掉還沒交的截圖 |
| `進度` | 今日進度與連續天數 |
| `錯題` | 最近 5 題還沒搞懂的錯題 |
| `請假` | 使用一次請假 |
| `罰金` | 未付罰金 |
| `說明` | 指令列表 |

### 怎麼交題目（擇一或混用）

從雅思哥複製文字時，**單選題和 YES/NO/NOT GIVEN 的勾選會遺失**，所以建議：

1. **截圖（最簡單）**：在雅思哥的檢討頁截圖，要截到每組題目下方「正确答案／我的答案」那塊。
   - 網頁：「交題目」選擇截圖，或在 Mac 上按 Cmd+Shift+Ctrl+4 截到剪貼簿，再到頁面按 ⌘V 貼上
   - LINE：先傳截圖（可一次選多張），再傳 `交 閱讀`
2. **文字＋答案列**：貼上複製的文章和題目，最後加一行你的答案：
   ```
   我的答案：27A 28A 29C 30D 37 NO 38 NOT GIVEN 39 NO 40 YES
   ```
   網頁「交題目」也有獨立的「我的答案」欄，填了就會蓋過教練讀到的答案。
3. **只給你的答案**：沒附正確答案也可以，教練會自己依原文解題，解析會標「（教練判斷）」。

填空沒寫算錯（未作答）。看不到你答案的題目（例如選擇題勾選沒複製到）不會亂猜，會列出題號、先不計分，之後在解析頁「補答案」或 LINE 傳 `補 37 NO 38 NG` 補上。長文章（寫作）建議用網頁交。

### 怎麼判對錯

聽力/閱讀由 Claude 把每一題的「你的答案」和「正解」讀出來，**對錯由程式比對**（`app/judge.py`），同一組答案永遠得到同一個結果：大小寫、標點、`5.30`=`5:30`、`13 June`=`June 13th`、`theater/theatre`、`(the) leaflet(s)` 都算同一個答案；選擇/配對題一律比字母（`C people would…` 和 `C` 一樣，複製時字母消失的選項依順序補 A、B、C）；NG / T / F / Y / N 縮寫都認得。每題在資料庫只有一筆（`Answer` 表），分數永遠由這些列重新計算。

- 補答案：已經有正解的題目直接比對，答錯或沒有正解的才請教練看原文寫解析
- 「其實答對了」：你的答案之後就算對；「其實答錯了」：移到錯題

## 規則細節

- 一天以「台北時間」計算；在 **結算時間** 判定當天是否完成
- 目標以「篇」計算：每提交一次算一篇（一篇閱讀、一個聽力 Section、一篇作文、一組口說），題數只用來算正確率
- 欠債：沒做完的篇數加到隔天，但隔天目標最多是原目標 ×「欠債上限」倍
- 轟炸：截止後依「間隔」推播（如 `30,15,10` = 30 分、15 分，之後每 10 分），達每日上限或做完就停；只用保留早晚提醒/結算額度之後剩下的推播
- 週日的結算訊息會附上本週週報
- 伺服器重啟時會補結算漏掉的日子

## 自動測試

```bash
uv run pytest
```

## 結構

```
app/
  main.py         FastAPI 入口、啟動排程
  models.py       資料表
  logic.py        目標、進度、連續紀錄、欠債、請假、設定冷靜期
  penalties.py    結算、四種懲罰、週報
  scheduler.py    每分鐘 tick：提醒、轟炸、結算
  push.py         LINE 推播與每月額度管控
  grader.py       Claude 批改（structured output）
  submissions.py  提交流程（網頁與 LINE 共用）
  judge.py        答案比對（正規化、選項字母、可接受寫法）
  review.py       每題的建立、補答案、手動修正、重算分數
  migrate.py      舊版資料（Mistake 表＋JSON）一次轉成 Answer
  line_bot.py     webhook 與指令
  web.py          網頁
```
