# 操作手冊總覽

這份文件是圖片單字學習器的操作手冊入口頁，目的是把不同角色要讀的文件分開，避免一份文件同時塞入太多使用情境。

## 你應該看哪一份

- 如果你只想使用學習器、匯出作答紀錄、了解基本操作，請看 [beginner-WI.md](beginner-WI.md)。
- 如果你要管理候選圖、套用 selection、維護題庫或修改程式，請看 [developer-WI.md](developer-WI.md)。
- 如果你要在 GitHub 上提 Issue、送 Pull Request 或協作提交，請看 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 建議閱讀順序

1. 一般使用者先讀 [beginner-WI.md](beginner-WI.md)。
2. 題庫維護者與開發者再讀 [developer-WI.md](developer-WI.md)。
3. 準備推送到 GitHub 前，再讀 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 共用前提

- 此專案必須透過靜態伺服器開啟，不能直接用 file:// 開 HTML。
- 正式圖片來源僅限 Pexels 與 Pixabay 官方 API。
- 正式題庫以 images/approved/ 與 data/image_words.json 為準。
- images/raw/ 是工作區，不是正式題庫。

## 最常用命令

啟動本機伺服器：

```bash
python -m http.server 8000
```

產生管理頁 manifest：

```bash
python tools/question_bank_manager.py manifest
```

預覽套用管理頁選擇：

```bash
python tools/question_bank_manager.py apply --selection-file path/to/manager_selection.json --dry-run
```

驗證正式題庫：

```bash
python tools/validate_image_bank.py
```

## 角色對應

- 新手版：偏「怎麼用」
- 開發者版：偏「怎麼維護、怎麼改、怎麼驗證」
- CONTRIBUTING：偏「怎麼在 GitHub 上協作」
