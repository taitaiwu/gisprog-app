---
title: YouBike 空站觀察
emoji: 🚲
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# 臺北 YouBike 空站觀察

> 上面 `---` 之間的設定是給 HuggingFace Spaces 讀的（W5 部署時使用），請保留。

115-1 地理資訊系統運用程式的 App 範本。選擇時段與空站門檻，查看臺北各區的 YouBike 空站比例。

## App 用途

本系統目前可以依據所輸入的時間資料，顯示臺北市各個行政區的 YouBike 當時狀況

## 資料

### YouBike 站點快照

| 項目 | 內容 |
|---|---|
| 來源 | 臺北市資料大平臺「YouBike2.0 臺北市公共自行車即時資訊」 |
| 網址 | `https://tcgbusfs.blob.core.windows.net/dotapp/youbike/v2/youbike_immediate.json` |
| 授權 | 政府資料開放授權條款－第 1 版（使用時須註明來源） |
| 資料時間 | 2026-09-24 至 2026-10-07 共 8 個時段的快照：09/24 11:20、15:47；09/25 12:30、18:00、23:30；09/30 17:00；10/01 13:58；10/07 14:21 |
| 檔案 | `data/03_youbike_snapshots_clean.csv` |

`app.py` 需要的欄位：`snapshot_time`、`sno`、`sarea`、`act`、`available_rent_bikes`、`latitude`、`longitude`。

### 行政區界線

| 項目 | 內容 |
|---|---|
| 來源 | 內政部國土測繪中心「鄉鎮市區界線（TWD97 經緯度）」，政府資料開放平臺 |
| 授權 | 政府資料開放授權條款－第 1 版（使用時須註明來源） |
| 資料版本 | 1140318 |
| 檔案 | `data/鄉(鎮、市、區)界線1140318/TOWN_MOI_1140318.shp`（`.shx`、`.dbf`、`.prj`、`.CPG` 需放在同一個資料夾） |

### 資料處理

- 只分析營運中的站（`act` 為 `True`）。
- 用 `snapshot_time` 產生「月/日 時:分」格式的 `時段`，作為時段選項。
- YouBike 資料的 `sarea` 有一區「臺大公館校區」（65 站），它不是行政區。App 用站點經緯度和行政區界線做空間連結，把這些站歸回實際所在的行政區：大安區 59 站、中正區 6 站。所以圖表只有臺北市的 12 個行政區。

## 在 Codespaces 執行

1. 在 repo 頁面按 **Code → Codespaces → Create codespace on main**。
2. 等環境建好（第一次約 2–3 分鐘，會自動安裝 `requirements.txt` 的套件）。
3. 在終端機輸入：

   ```bash
   solara run app.py
   ```

4. 右下角出現提示時，按 **Open in Browser**；或到「連接埠」分頁，開啟 8765 埠。

## 修改之後

```bash
git status          # 哪些檔案被改了？
git diff            # 改了哪幾行？
git add app.py      # 只加入你確認過的檔案
git commit -m "說明你改了什麼"
git push
```

**agent 改完之後，一定先看 `git diff` 再 commit。**

## 授權

- **程式碼**（`app.py`、`Dockerfile` 等）：MIT License，見 [`LICENSE`](LICENSE)。可以自由使用、修改、公開，請保留 `LICENSE` 檔。
- **資料**（`data/` 內的檔案）：YouBike 資料取自臺北市資料大平臺，行政區界線取自內政部國土測繪中心，皆依政府資料開放授權條款－第 1 版使用，不適用 MIT。
