# 圖片單字學習器

這是一個以圖片為核心的英文單字學習專案，前端使用純 HTML、CSS 與 Vanilla JavaScript，部署方式以靜態網站為主，適合放在 GitHub Pages。

學習器目前提供以下功能：

- 看圖片做英文四選一
- 3 秒後顯示提示
- 10 秒後自動揭示答案
- 可手動提前顯示答案
- 以瀏覽器 localStorage 保存作答紀錄、統計與錯題庫
- 可匯出 JSON 與 CSV 作答紀錄
- 提供錯題重練模式
- 提供本機題庫管理頁，協助挑選最佳圖片並填入中文名稱

圖片來源流程支援兩種模式：

- **官方授權模式**：僅使用 Pexels API 與 Pixabay API（適用正式題庫）
- **混合模式（Hybrid）**：優先使用官方 API，不足時自動啟動 Web Scraper 補齊（僅限個人使用，授權標註為 Personal Use Only）

## 這份 README 適合誰看

- 一般使用者：只想啟動學習器練習單字
- 題庫維護者：要挑選圖片、更新中文名稱、套用到正式題庫
- 開發者：要調整前端行為、維護 Python 工具、整理 GitHub 協作流程

如果你只想先把網站跑起來，先看「快速開始」。

如果你要維護題庫或程式，請再看 [developer-WI.md](developer-WI.md) 與 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 快速開始

### 只想使用學習器

1. 在專案根目錄開啟終端機。
2. 啟動本機靜態伺服器。
3. 用瀏覽器開啟學習器頁面。

```bash
python -m http.server 8000
```

開啟：

- http://localhost:8000/index.html

首頁提供：

- 開始練習：練完整題庫
- 錯題重練：只練錯題庫中的題目
- 學習進度：看統計與匯出紀錄
- 設定：調整亂數、自動下一題與重設本機資料

### 想使用題庫管理頁

1. 先產生管理頁需要的 manifest。
2. 啟動本機靜態伺服器。
3. 開啟管理頁。

```bash
python tools/question_bank_manager.py manifest
python -m http.server 8000
```

開啟：

- http://localhost:8000/manager.html

管理頁可讓你：

- 逐題查看候選圖
- 選出最佳圖片
- 填入中文名稱
- 匯出 selection JSON，供後續套用回正式題庫

## 專案主要檔案

前端頁面：

- index.html：學習器頁面
- app.js：學習器邏輯、計時、localStorage、匯出
- style.css：學習器與管理頁共用樣式
- manager.html：本機題庫管理頁
- manager.js：管理頁邏輯與選擇暫存

資料檔：

- data/image_words.json：正式題庫
- data/manager_candidates.json：管理頁候選 manifest
- data/vocab_seed.csv：單字種子清單

Python 工具：

- tools/download_licensed_images.py：下載官方授權候選圖與同步 approved 題庫（正式 pipeline）
- tools/download_hybrid.py：混合下載工具，支援新主題詞庫擴充（官方 API + Web Scraper 補齊）
- tools/question_bank_manager.py：產生管理頁 manifest、套用管理頁選擇
- tools/validate_image_bank.py：嚴格驗證正式題庫

資料檔：

- data/new_words.csv：新詞彙種子清單（辦公室 / 會議 / 商業合約，供 download_hybrid.py 使用）

圖片資料夾：

- images/raw/：候選圖工作區
- images/approved/：正式採用圖庫

## 初學者重點

- 請不要直接雙擊 HTML 檔。此專案會讀取 JSON，必須透過 http://localhost 方式開啟。
- 題目規則是 3 秒提示、10 秒揭答。若按「提前顯示答案」，該題會被記為看答案後作答。
- 作答紀錄、偏好設定、錯題庫都存在瀏覽器本機，不會自動上傳到伺服器。
- 若你只需要操作步驟，請直接看 [beginner-WI.md](beginner-WI.md)。

## 詞庫擴充（混合模式）

若要新增辦公室、會議、商業合約等新主題詞彙，使用 `download_hybrid.py`：

```bash
# 完整下載 43 個新單字（每字 5 張候選圖）
python tools/download_hybrid.py --input data/new_words.csv

# 僅使用官方 API，停用爬蟲
python tools/download_hybrid.py --input data/new_words.csv --no-scraper

# Dry-run 預覽前 3 個單字（不實際寫入檔案）
python tools/download_hybrid.py --input data/new_words.csv --max-seeds 3 --dry-run
```

混合下載工具特性：

- 優先使用 Pexels → Pixabay 官方 API
- API 數量不足時自動啟動 DuckDuckGo 爬蟲補齊
- 官方圖片 sidecar 填入對應授權，爬蟲圖片標註 `Personal Use Only`
- sha256 去重，跳過已下載圖片
- ThreadPoolExecutor 並發下載（預設 6 threads）
- 完全獨立，**不影響** image_words.json 等官方 pipeline 檔案

> 注意：混合模式爬蟲圖片僅限個人使用，請勿將其混入 images/approved/ 正式題庫。

## 題庫維護與開發流程

標準流程如下：

1. 用官方 API 下載 raw 候選圖。
2. 產生管理頁 manifest。
3. 在管理頁挑圖並匯出 selection JSON。
4. 先用 dry-run 預覽 apply 結果。
5. 正式 apply 到 images/approved/ 與 data/image_words.json。
6. 執行 validator。
7. 用本機靜態伺服器做 smoke test。

常用命令：

```bash
python tools/download_licensed_images.py download
python tools/question_bank_manager.py manifest
python tools/question_bank_manager.py apply --selection-file path/to/manager_selection.json --dry-run
python tools/question_bank_manager.py apply --selection-file path/to/manager_selection.json
python tools/validate_image_bank.py
```

更完整的維護步驟請看 [developer-WI.md](developer-WI.md)。

## 驗證與部署

正式題庫更新後，至少要做以下檢查：

```bash
python tools/validate_image_bank.py
python -m http.server 8000
```

然後手動確認：

- index.html 能正常載入
- manager.html 能正常載入
- 圖片沒有壞圖
- 匯出功能正常

若要部署到 GitHub Pages：

- 將變更推上 GitHub
- 啟用 GitHub Pages
- 保留根目錄的 .nojekyll

## 建議接著閱讀

- [operator WI.md](operator%20WI.md)：操作手冊總入口
- [beginner-WI.md](beginner-WI.md)：新手版操作手冊
- [developer-WI.md](developer-WI.md)：開發者與題庫維護手冊
- [CONTRIBUTING.md](CONTRIBUTING.md)：GitHub 協作與 Pull Request 規範
