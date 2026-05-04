# GitHub 貢獻指南

這份文件說明如何在 GitHub 上協作維護圖片單字學習器，包括 Issue、Commit、Pull Request 與提交前檢查。

## 1. 適用情境

- 要回報 bug
- 要提功能需求
- 要更新前端介面
- 要補題庫、更新圖片、調整 metadata
- 要送 Pull Request 到 GitHub

## 2. 提交前先確認的原則

- 正式圖片來源只允許 Pexels 與 Pixabay 官方 API。
- 不可提交 scraping 來源內容。
- 不可提交 .env、API key 或其他憑證。
- 正式題庫異動應以 images/approved/ 與 data/image_words.json 為準。
- 若 raw 或 approved 有變動，通常也要同步更新 data/manager_candidates.json。

## 3. 建議分支命名

可使用以下格式：

- feat/chinese-docs
- feat/manager-workflow
- fix/localstorage-export
- docs/readme-contributing
- chore/validator-cleanup

## 4. 建議 Commit 訊息

可使用短句、動詞開頭：

- docs: 將 README 與操作手冊改為全中文
- docs: 新增 GitHub CONTRIBUTING 指南
- feat: 新增題庫管理頁與 selection 匯出
- fix: 保留 sync 時的 zh 與 definition

## 5. Pull Request 應包含什麼

請在 PR 內清楚寫出：

- 這次改了什麼
- 為什麼要改
- 影響哪些檔案或流程
- 如何驗證
- 是否有畫面變更或資料格式變更

若有 UI 變動，建議附上：

- 首頁畫面
- 練習頁畫面
- 管理頁畫面
- 匯出結果或 validator 結果摘要

## 6. 提交前檢查清單

### 文件異動

- README 與相關操作手冊是否一致
- 連結是否正確
- 文字是否已更新為實際行為

### 題庫或圖片異動

```bash
python tools/question_bank_manager.py manifest
python tools/validate_image_bank.py
```

確認：

- approved 圖片存在
- metadata 完整
- image_words.json 可正常使用

### 前端異動

```bash
python -m http.server 8000
```

手動檢查：

- index.html
- manager.html
- 提示與揭答時序
- 匯出按鈕
- 本機資料重設

## 7. 建議的 GitHub 協作流程

1. 先同步最新主分支。
2. 建立自己的工作分支。
3. 完成修改後先在本機驗證。
4. 整理 Commit 訊息。
5. 推送分支到 GitHub。
6. 建立 Pull Request。
7. 在 PR 中寫清楚驗證方式與風險。

## 8. 題庫更新時的提交建議

若本次變更包含題庫內容，建議一併提交：

- images/approved/ 內實際有變動的正式圖片與 sidecar
- data/image_words.json
- data/manager_candidates.json
- 相關文件更新

不要提交：

- .env
- .venv
- 未整理完的臨時測試檔

## 9. Issue 建議內容

### Bug 回報

請附上：

- 發生頁面
- 重現步驟
- 預期結果
- 實際結果
- 若有錯誤訊息，請附上訊息文字或截圖

### 功能需求

請附上：

- 想解決的問題
- 建議的使用情境
- 是否影響學習器、管理頁或 Python 工具

## 10. 最後提醒

- 文件與實際行為要同步。
- 題庫資料異動一定要驗證。
- 任何會影響正式資料的操作，先做 dry-run 再正式寫入。
