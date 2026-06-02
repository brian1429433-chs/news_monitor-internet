# 高雄新聞監控（雲端版 / GitHub Actions）

每 5 分鐘自動爬取**自由時報**、**東森新聞**即時新聞，比對關鍵字「高雄」，
截圖後透過 **LINE Messaging API** 推播通知。在 GitHub Actions 上免費執行，
**不需要一直開著電腦**。

> 社群監控（Facebook / Threads）因需要登入 session，仍留在本機執行，不在此專案範圍。

---

## 為什麼 repo 要設為 Public

| repo 類型 | 免費 Actions 分鐘 | 每 5 分鐘排程是否夠用 |
|-----------|------------------|----------------------|
| Private | 2000 分/月 | ❌ 不夠 |
| **Public** | **無上限免費** | ✅ 可以 |

本專案的程式碼與去重檔（`sent_news_ids.json` 只是一堆 md5 雜湊）**不含機密**，
所有機密（LINE token、imgbb key）一律放 GitHub Secrets，`config.json` 由 `.gitignore` 排除、絕不上傳。
因此設為 **Public** 才能享有不限量的免費排程。

---

## 一次性設定步驟

### 1. 建立 Public repo 並上傳程式
把本資料夾的檔案上傳到一個新的 **public** GitHub repo（`config.json` 不要上傳）。

```bash
git init
git add .
git commit -m "init: 高雄新聞監控雲端版"
git branch -M main
git remote add origin https://github.com/<你的帳號>/<repo名稱>.git
git push -u origin main
```

### 2. 設定 Secrets
repo → **Settings → Secrets and variables → Actions → New repository secret**，新增三個：

| Secret 名稱 | 內容 |
|-------------|------|
| `LINE_CHANNEL_ACCESS_TOKEN` | 你的 LINE Channel access token |
| `LINE_USER_ID` | 接收通知的 LINE user / group id |
| `IMGBB_API_KEY` | imgbb API key（沒有可留空，會略過截圖上傳） |

### 3. 手動測試一次
repo → **Actions → 高雄新聞監控 → Run workflow**，
跑完後確認：
- LINE 有收到通知（若當下有「高雄」相關新聞）
- log 中顯示抓取與推播筆數正常
- `sent_news_ids.json` 已被 `github-actions[bot]` 更新（代表去重狀態有保存）

### 4. 確認自動排程
之後每 5 分鐘會自動觸發（UTC cron，尖峰可能延遲幾分鐘，屬正常）。

### 5. 關閉本機的新聞排程
到 Windows 工作排程器**停用新聞監控的任務**（社群監控的任務繼續保留）。

---

## 運作原理

- **設定來源**：程式優先讀環境變數（GitHub Secrets 注入），找不到才 fallback 讀本機 `config.json`，因此同一份程式本機 / 雲端都能跑。
- **去重保存**：GitHub Actions 每次都是全新環境，workflow 跑完會把更新後的 `sent_news_ids.json` **commit 回 repo**，下次執行讀回來，避免重複推播。
- **保持排程啟用**：GitHub 對「連續 60 天無活動」的 repo 會停用排程；因為每次執行都會 commit 狀態檔，等於持續有活動，排程不會被停用。

---

## 本機測試（可選）

```bash
pip install -r requirements.txt
python -m playwright install chromium
# 方式一：用環境變數
set LINE_CHANNEL_ACCESS_TOKEN=xxx   # PowerShell: $env:LINE_CHANNEL_ACCESS_TOKEN="xxx"
set LINE_USER_ID=xxx
set IMGBB_API_KEY=xxx
python news_monitor.py
# 方式二：複製 config.example.json 為 config.json 填入後執行
```

---

## 檔案說明

| 檔案 | 用途 |
|------|------|
| `news_monitor.py` | 主程式（環境變數優先、fallback config.json） |
| `requirements.txt` | Python 相依套件 |
| `.github/workflows/news.yml` | GitHub Actions 排程設定 |
| `.gitignore` | 排除機密與暫存檔 |
| `config.example.json` | 設定範本（本機測試用） |
| `sent_news_ids.json` | 去重狀態（自動維護，只留最後 1000 筆） |

---

## 常見問題

- **抓到 0 筆**：可能新聞網站改版導致選擇器失效，或當下無「高雄」新聞。建議日後加上「連續多次抓 0 筆就發 LINE 告警」。
- **排程沒觸發**：確認 repo 為 public、Actions 已啟用，且近期有活動（commit）。
- **沒有 imgbb key**：留空即可，程式會略過截圖上傳，只推文字通知。
