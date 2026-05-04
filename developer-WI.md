# 開發者與題庫維護手冊

這份文件給需要維護題庫、套用圖片、修改前端或整理 GitHub 提交流程的人。

## 1. 適用角色

- 題庫維護者
- 內容營運人員
- 前端維護者
- Python 工具維護者

## 2. 開發前提

建議環境：

- Python 3.11 以上
- Pillow 已安裝

如未安裝 Pillow：

```bash
pip install Pillow
```

若要下載官方授權圖片，請在 .env 或系統環境變數中提供至少一組 API key：

```bash
PEXELS_API_KEY=your_key_here
PIXABAY_API_KEY=your_key_here
```

不要提交 .env 到版本控制。

## 3. 檔案分工

前端：

- index.html：學習器結構
- app.js：學習器邏輯、計時、匯出、localStorage
- style.css：共用樣式
- manager.html：管理頁結構
- manager.js：管理頁互動邏輯

資料：

- data/image_words.json：正式題庫
- data/manager_candidates.json：管理頁 manifest
- data/vocab_seed.csv：單字種子資料

工具：

- tools/download_licensed_images.py：下載 raw 候選圖與 sync approved 題庫
- tools/question_bank_manager.py：建立 manifest 與套用 selection
- tools/validate_image_bank.py：驗證正式題庫

## 4. 題庫維護標準流程

### 步驟 1：下載官方授權候選圖

```bash
python tools/download_licensed_images.py download
```

結果：

- 候選圖會進到 images/raw/<category>/<word_slug>/
- 每張圖會有對應 JSON sidecar
- download_report.json 會更新

### 步驟 2：產生管理頁 manifest

```bash
python tools/question_bank_manager.py manifest
```

結果：

- 產生或更新 data/manager_candidates.json
- 管理頁可以載入候選圖

注意：只要 raw 或 approved 有變動，就應該重跑一次 manifest。

### 步驟 3：在管理頁挑圖並匯出 selection

```bash
python -m http.server 8000
```

開啟：

- http://localhost:8000/manager.html

在頁面中：

- 為每題選最佳圖片
- 填入中文名稱
- 匯出 selection JSON

### 步驟 4：先用 dry-run 檢查 apply

```bash
python tools/question_bank_manager.py apply --selection-file path/to/manager_selection.json --dry-run
```

目標：

- 確認每個單字會套到哪張 raw 圖片
- 在真正寫入前先抓出遺失檔案或 selection 異常

### 步驟 5：正式套用 selection

```bash
python tools/question_bank_manager.py apply --selection-file path/to/manager_selection.json
```

結果：

- 選中的圖片會被轉成正式 approved 圖片
- sidecar 會一起更新
- zh 會寫入 approved metadata
- data/image_words.json 會重建

### 步驟 6：必要時手動 sync approved 題庫

如果你是直接手動整理 images/approved/，可以額外執行：

```bash
python tools/download_licensed_images.py sync
```

預覽版本：

```bash
python tools/download_licensed_images.py sync --dry-run
```

目前 sync 會保留或回填：

- zh
- definition
- partOfSpeech
- source
- sourceUrl
- photographer
- license

### 步驟 7：驗證正式題庫

```bash
python tools/validate_image_bank.py
```

至少會檢查：

- JSON 結構是否合法
- 是否有重複 id
- 正式圖片是否存在
- 路徑是否位於 images/approved/
- 是否誤用 SVG placeholder
- choices 是否固定為 4
- answer 是否存在於 choices
- source、sourceUrl、license 是否存在
- hint1、hint2 是否存在
- 圖片是否真的能被讀取

### 步驟 8：本機 smoke test

```bash
python -m http.server 8000
```

手動檢查：

- index.html 可正常載入
- manager.html 可正常載入
- 提示與揭答時序正常
- 匯出 JSON/CSV 功能正常
- 題庫管理頁可正確顯示 selection 狀態

## 5. 前端修改建議

修改學習器時，優先看：

- index.html
- app.js
- style.css

目前學習器關鍵規則：

- 3 秒顯示提示
- 10 秒自動揭答
- 可手動提前揭答
- 答題紀錄可匯出 JSON 與 CSV

修改管理頁時，優先看：

- manager.html
- manager.js
- data/manager_candidates.json

## 6. 釋出前最小檢查清單

1. 執行 python tools/question_bank_manager.py manifest。
2. 執行 python tools/validate_image_bank.py。
3. 啟動 python -m http.server 8000。
4. 開啟 index.html 與 manager.html。
5. 實測至少一輪學習器與一次管理頁匯出。
6. 確認沒有把 .env 提交進 git。

## 7. 常見問題

### 管理頁讀不到 data/manager_candidates.json

通常是 manifest 尚未建立或已過期。

```bash
python tools/question_bank_manager.py manifest
```

### apply 失敗，說找不到檔案

通常是 selection JSON 指到的 raw 圖片或 sidecar 已被移動或刪除。

處理方式：

1. 重跑 manifest
2. 重新開 manager.html
3. 重新匯出 selection JSON
4. 再跑 apply

### validator 失敗

先讀錯誤輸出，再回頭修正指定檔案，不要直接跳過 validator。

## 8. 安全規則

- 正式圖片來源只允許 Pexels 與 Pixabay 官方 API。
- 不可加入 scraping 流程。
- 不要手動亂改 data/image_words.json，除非你清楚 sync 與 apply 的影響。
- 題庫內容更新後一定要跑 validator。
- .env 不可提交。

## 9. GitHub 協作

如果你要在 GitHub 上送出 Issue、Commit 或 Pull Request，請再看 [CONTRIBUTING.md](CONTRIBUTING.md)。
