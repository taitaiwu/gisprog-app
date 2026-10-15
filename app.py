"""臺北 YouBike 空站觀察：115-1 地理資訊系統運用程式的 App 範本。

執行方式：
1. Linux    ：在終端機輸入 solara run app.py
2. Windows  ：在終端機輸入 py -m solara run app.py
   （不要用 python：這台電腦的 python 會連到 Anaconda，套件版本不對，圖表會畫不出來）
"""

import html
import json
import urllib.request
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import ipyleaflet
import ipywidgets
import ipyvue
import leafmap
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import solara
import solara.server.settings
import traitlets

# 關掉 Solara 預設固定在右下角的「This website runs on Solara」，改寫在頁尾。
solara.server.settings.theme.show_banner = False

DATA_PATH = Path(__file__).parent / "data" / "03_youbike_snapshots_clean.csv"
BOUNDARY_PATH = (
    Path(__file__).parent / "data" / "鄉(鎮、市、區)界線1140318" / "TOWN_MOI_1140318.shp"
)
即時資料網址 = "https://tcgbusfs.blob.core.windows.net/dotapp/youbike/v2/youbike_immediate.json"
即時更新秒數 = 60
即時選項 = "即時"

# 讀檔放在元件外面：App 啟動時只讀一次，切換選項時不會重新讀檔。
# sno、act 指定為字串，避免被自動轉成整數（W3 的 read_json 陷阱，read_csv 也一樣）。
df = pd.read_csv(DATA_PATH, dtype={"sno": str, "act": str})
df = df[df["act"] == "True"]  # 只看營運中的站（這份資料的 act 是 True／False）

# 這份資料沒有「時段」欄，用快照時間 snapshot_time 轉成「09/25 12:30」這種短格式。
# 格式是「月/日 時:分」，排序結果和時間先後一致（資料都在同一年）。
快照時間 = pd.to_datetime(df["snapshot_time"])
df["時段"] = 快照時間.dt.strftime("%m/%d %H:%M")

# 行政區界線（內政部國土測繪中心，TWD97 經緯度）。
# 原檔是全臺灣的鄉鎮市區，用 where 只讀臺北市的 12 區，讀檔比較快。
行政區界 = gpd.read_file(BOUNDARY_PATH, where="COUNTYNAME = '臺北市'")


def 臺大站對應行政區(資料, 界線):
    """用經緯度判斷「臺大公館校區」各站實際在哪個行政區，回傳 sno → 行政區 的對照表。

    YouBike 把臺大校園內的站另外分成「臺大公館校區」，但它不是行政區，
    這些站其實分屬大安區和中正區，所以用空間連結（點落在哪個面裡）找出正確的行政區。
    """
    臺大站 = 資料[資料["sarea"] == "臺大公館校區"].drop_duplicates("sno")  # 每站留一筆就好
    點 = gpd.points_from_xy(臺大站["longitude"], 臺大站["latitude"])
    站點 = gpd.GeoDataFrame(臺大站[["sno"]], geometry=點, crs="EPSG:4326")  # YouBike 座標是 WGS84
    站點 = 站點.to_crs(界線.crs)  # 轉成和界線相同的座標系統，兩邊才能比對
    結果 = gpd.sjoin(站點, 界線[["TOWNNAME", "geometry"]], predicate="within")
    return 結果.set_index("sno")["TOWNNAME"]


對照 = 臺大站對應行政區(df, 行政區界)
是臺大站 = df["sno"].isin(對照.index)
df.loc[是臺大站, "sarea"] = df.loc[是臺大站, "sno"].map(對照)


def 取得即時資料():
    """從臺北市資料大平臺取得最新的 YouBike 站點資料。"""
    with urllib.request.urlopen(即時資料網址, timeout=20) as 回應:
        內容 = json.load(回應)

    if not isinstance(內容, list) or not 內容:
        raise ValueError("即時資料格式不正確或沒有站點資料。")

    即時表 = pd.DataFrame(內容)
    必要欄位 = {
        "sno",
        "sna",
        "sarea",
        "act",
        "ar",
        "Quantity",
        "available_rent_bikes",
        "available_return_bikes",
        "latitude",
        "longitude",
        "updateTime",
    }
    缺少欄位 = 必要欄位 - set(即時表.columns)
    if 缺少欄位:
        raise ValueError(f"即時資料缺少必要欄位：{', '.join(sorted(缺少欄位))}")

    即時表["sno"] = 即時表["sno"].astype(str)
    即時表 = 即時表[即時表["act"].astype(str).str.lower().isin(["1", "true"])].copy()
    臺大站行政區 = 即時表["sno"].map(對照)
    有對應行政區 = 臺大站行政區.notna()
    即時表.loc[有對應行政區, "sarea"] = 臺大站行政區[有對應行政區]

    if 即時表.empty:
        raise ValueError("即時資料中沒有營運中的站點。")
    return 即時表


def 即時資料更新(停止事件, 啟用):
    """即時模式下每 60 秒抓取一次資料，並保留最近一次成功結果。"""
    if not 啟用:
        return

    最新資料 = None
    最新更新時間 = None
    while not 停止事件.is_set():
        try:
            最新資料 = 取得即時資料()
            最新更新時間 = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            更新錯誤 = None
        except (OSError, ValueError) as 錯誤:
            更新錯誤 = f"{type(錯誤).__name__}: {錯誤}"

        yield 最新資料, 最新更新時間, 更新錯誤
        if 停止事件.wait(即時更新秒數):
            break


# 防呆：剛好落在界線上、或在界線外的站對不到行政區，維持原本的分區並提醒。
沒對到 = df.loc[df["sarea"] == "臺大公館校區", "sno"].nunique()
if 沒對到 > 0:
    print(f"注意：有 {沒對到} 個臺大公館校區的站對不到行政區，維持原本的分區。")

時段們 = sorted(df["時段"].unique())

# reactive：值改變時，用到它的元件會自動重新執行。
門檻 = solara.reactive(0)
時段 = solara.reactive(時段們[0])
選取站點 = solara.reactive(None)

# 行政區選單：「全部」看各區比較，選某一區就看該區每個站。
行政區們 = ["全部"] + sorted(df["sarea"].unique())
行政區 = solara.reactive("全部")


def 各區空站比例(資料, 門檻值):
    """計算各區的站數、空站數與空站比例（可借車 <= 門檻值 算空站）。"""
    資料 = 資料.assign(空站=資料["available_rent_bikes"] <= 門檻值)
    表 = 資料.groupby("sarea").agg(站數=("sno", "size"), 空站數=("空站", "sum"))
    表["空站比例"] = (表["空站數"] / 表["站數"]).round(3)
    return 表.sort_values("空站比例", ascending=False).reset_index()


def 某區各站(資料, 區名, 門檻值):
    """取出某個行政區每個站的車輛數，並標示是否為空站（可借車 <= 門檻值）。"""
    表 = 資料[資料["sarea"] == 區名]
    表 = 表.assign(
        站名=表["sna"].str.removeprefix("YouBike2.0_"),  # 每站都有這個前綴，去掉比較好讀
        狀態=(表["available_rent_bikes"] <= 門檻值).map({True: "空站", False: "有車"}),
    )
    表 = 表.rename(
        columns={
            "available_rent_bikes": "可借車",
            "available_return_bikes": "可還車",
            "Quantity": "總車位",
            "ar": "地址",
        }
    )
    表 = 表[["sno", "站名", "狀態", "可借車", "可還車", "總車位", "地址"]]
    表 = 表.sort_values("可借車").reset_index(drop=True)
    表.index = 表.index + 1  # 編號從 1 開始
    return 表


def 各區表格(表):
    """把各區統計表整理成給人看的樣子：欄名改中文、比例改成百分比文字。"""
    表 = 表.rename(columns={"sarea": "行政區"})
    表["空站比例"] = 表["空站比例"].map("{:.1%}".format)
    表.index = range(1, len(表) + 1)  # 編號從 1 開始，剛好是排名
    return 表


# ---------- 畫面樣式 ----------
# 配色集中放在這裡，要換顏色只改這幾行。
主色 = "#2563eb"  # 藍：一般長條
強調色 = "#f97316"  # 橘：選取的行政區
灰色 = "#d1d5db"  # 灰：沒選取的行政區
空站色 = "#dc2626"  # 紅：空站

# 頁面的 CSS：像 Bootstrap 的 card 一樣，每一塊內容放在一個白色「容器」裡。
頁面樣式 = """
.v-application { background: #f3f4f6 !important; }
/* 欄位裡的內容（表格、圖）不能把欄位撐寬，否則手機上整頁會超出螢幕 */
.v-application, .v-application__wrap, .整頁, .整頁 .v-sheet, .整頁 [class*="v-col"] {
    min-width: 0 !important; }
.容器 .js-plotly-plot, .容器 .plot-container { max-width: 100%; }
.地圖容器 .jupyter-widgets, .地圖容器 .leaflet-container { max-width: 100%; min-width: 0; }
.整頁 { max-width: 1280px; width: 100%; align-self: center; margin: 0 auto; padding: 24px 16px; }
.容器 { background: white; border: 1px solid #e5e7eb; border-radius: 10px;
        padding: 20px 24px; }
.標題容器 { background: #1e3a8a; border: none; color: white; }
.大標題 { font-size: 28px; font-weight: 700; }
.副標題 { font-size: 15px; opacity: .85; }
.容器標題 { font-size: 18px; font-weight: 700; color: #111827; }
.說明文字 { color: #6b7280; font-size: 13px; }
.solara-data-table table { width: 100% !important; }  /* 表格和容器同寬（要蓋過 Solara 預設樣式） */
.圖說明 { min-height: 40px; }  /* 並排的兩張圖，說明文字一行或兩行都佔一樣的高度，圖才會對齊 */
.頁尾 { color: #6b7280; font-size: 12px; line-height: 1.8; text-align: center; }
"""


class 圖表重新量寬度(ipyvue.VueTemplate):
    """看不見的小元件：顯示到畫面上 0.5 秒後，通知瀏覽器「視窗大小變了」。

    Plotly 圖在第一次畫的時候就決定寬度，如果那時版面還沒排好（常發生在手機上），
    圖會用預設的 700 px，超出螢幕。收到通知後，圖會依照所在的容器重新量寬度。
    """

    template = traitlets.Unicode(
        """
        <template><span></span></template>
        <script>
        module.exports = {
            mounted() {
                setTimeout(() => window.dispatchEvent(new Event("resize")), 500);
            },
        };
        </script>
        """
    ).tag(sync=True)


def 統一圖表樣式(圖, 高度):
    """所有圖表共用的外觀：白底、緊湊的邊界、隱藏圖例標題。"""
    圖.update_layout(
        template="plotly_white",
        height=高度,
        margin={"l": 10, "r": 40, "t": 10, "b": 10},
        font={"size": 13},
        legend_title_text="",
    )
    return 圖


def 各區比較圖(表, 選取區, 高度=None):
    """畫各區空站比例的橫條圖；選了某一區時，那一區用橘色標示，其他區變灰色。

    高度沒指定時，每區給 32 px；和其他圖並排時，可以指定成一樣的高度。
    """
    圖 = px.bar(
        表,
        x="空站比例",
        y="sarea",
        orientation="h",
        text="空站比例",
        labels={"sarea": "", "空站比例": "空站比例"},
    )
    if 選取區 == "全部":
        圖.update_traces(marker_color=主色)
    else:
        # 顏色清單的順序要和「表」的列順序一致，每一列對應一根長條。
        顏色們 = [強調色 if 區 == 選取區 else 灰色 for 區 in 表["sarea"]]
        圖.update_traces(marker_color=顏色們)
    圖.update_traces(texttemplate="%{x:.1%}", textposition="outside", cliponaxis=False)
    # x 軸右邊多留 20% 空間，長條外面的百分比數字才不會被截掉。
    圖.update_layout(
        yaxis={"categoryorder": "total ascending"},
        xaxis={"tickformat": ".0%", "range": [0, 表["空站比例"].max() * 1.2]},
    )
    # 每區至少給 32 px 高度，行政區名稱才不會被 Plotly 自動隔行省略。
    if 高度 is None:
        高度 = 60 + 32 * len(表)
    return 統一圖表樣式(圖, 高度)


def 單區各站圖(表, 高度):
    """畫某區可借車最少的幾個站：有顏色的是可借車（空站紅色），淺灰色是空位（可還車）。

    只畫可借車的話，0 台的長條長度是 0 會看不到；疊上空位後，空站會是一整條灰色，一眼就看得出來。
    （表要先依可借車由少到多排好）
    """
    站名們 = 表["站名"][::-1]  # Plotly 橫條圖由下往上畫，反過來才會讓最缺車的站在最上面
    可借車顏色 = [空站色 if 狀態 == "空站" else 主色 for 狀態 in 表["狀態"][::-1]]
    圖 = go.Figure()
    圖.add_bar(
        name="可借車",
        x=表["可借車"][::-1],
        y=站名們,
        orientation="h",
        marker_color=可借車顏色,
        customdata=表["地址"][::-1],
        hovertemplate="%{y}<br>可借車：%{x} 台<br>%{customdata}<extra></extra>",
    )
    圖.add_bar(
        name="空位（可還車）",
        x=表["可還車"][::-1],
        y=站名們,
        orientation="h",
        marker_color="#e5e7eb",
        hovertemplate="%{y}<br>空位：%{x} 個<extra></extra>",
    )
    圖.update_layout(
        barmode="stack",
        xaxis_title="車位數",
        legend={"orientation": "h", "y": 1.0, "yanchor": "bottom", "x": 0, "traceorder": "normal"},
    )
    return 統一圖表樣式(圖, 高度)


@solara.component
def 站點地圖(資料, 站點編號):
    """依照目前的時段、行政區與空站門檻繪製可點擊的 Leafmap 站點圖。"""
    with solara.Column(classes=["容器", "地圖容器"]):
        solara.Text("YouBike 站點地圖", classes=["容器標題"])
        solara.Text(
            "點擊站點可查看詳細資訊；黃色標記為表格中選取的站點。"
            "顏色依可借車數分級，分級說明見地圖圖例。",
            classes=["說明文字"],
        )

        if 資料.empty:
            solara.Text("目前選取的時段與行政區沒有站點資料。", classes=["說明文字"])
            return

        地圖表 = 資料.assign(
            站名=資料["sna"].str.removeprefix("YouBike2.0_"),
            狀態=(資料["available_rent_bikes"] <= 門檻.value).map(
                {True: "空站", False: "有車"}
            ),
            可借車級距=pd.cut(
                pd.to_numeric(資料["available_rent_bikes"], errors="coerce"),
                bins=[-1, 0, 2, 5, float("inf")],
                labels=["0 台", "1–2 台", "3–5 台", "6 台以上"],
            ),
        ).rename(
            columns={
                "sarea": "行政區",
                "available_rent_bikes": "可借車",
                "available_return_bikes": "可還車",
                "Quantity": "總車位",
                "ar": "地址",
                "updateTime": "資料更新時間",
            }
        )
        地圖表["longitude"] = pd.to_numeric(地圖表["longitude"], errors="coerce")
        地圖表["latitude"] = pd.to_numeric(地圖表["latitude"], errors="coerce")
        地圖表 = 地圖表.dropna(subset=["longitude", "latitude"])
        if 地圖表.empty:
            solara.Text("目前站點沒有有效座標，無法顯示地圖。", classes=["說明文字"])
            return

        定位站 = 地圖表[地圖表["sno"].astype(str) == str(站點編號)]
        if not 定位站.empty:
            地圖中心 = [
                float(定位站.iloc[0]["latitude"]),
                float(定位站.iloc[0]["longitude"]),
            ]
            縮放層級 = 17
        else:
            地圖中心 = [
                float(地圖表["latitude"].mean()),
                float(地圖表["longitude"].mean()),
            ]
            縮放層級 = 11 if 行政區.value == "全部" else 13

        地圖 = leafmap.Map(
            center=地圖中心,
            zoom=縮放層級,
            height="520px",
            width="100%",
            basemap="OpenStreetMap",
            prefer_canvas=True,
        )
        顏色對照 = {
            "0 台": "darkred",
            "1–2 台": "orange",
            "3–5 台": "cadetblue",
            "6 台以上": "darkgreen",
        }

        def 顯示值(值):
            if pd.isna(值) or str(值).strip() == "":
                return "—"
            return html.escape(str(值))

        標記們 = []
        for _, 站 in 地圖表.iterrows():
            站名 = str(站["sna"]).removeprefix("YouBike2.0_")
            站點級距 = str(站["可借車級距"])
            顏色 = 顏色對照[站點級距]
            是否選取 = str(站["sno"]) == str(站點編號)
            標記顏色 = "#facc15" if 是否選取 else 顏色
            邊框顏色 = "#111827" if 是否選取 else "#ffffff"
            圖示 = ipyleaflet.DivIcon(
                html=(
                    '<div style="width:14px;height:14px;border:2px solid '
                    f'{邊框顏色};border-radius:50%;background:{標記顏色};'
                    'box-sizing:border-box;"></div>'
                ),
                icon_size=(14, 14),
                icon_anchor=(7, 7),
                class_name="",
            )

            資訊列 = [
                ("站名", 站名),
                ("行政區", 站["行政區"]),
                ("狀態", 站["狀態"]),
                ("可借車", f'{站["可借車"]} 台'),
                ("可借車級距", 站點級距),
                ("可還車", f'{站["可還車"]} 個'),
                ("總車位", f'{站["總車位"]} 個'),
                ("地址", 站["地址"]),
                ("資料更新時間", 站["資料更新時間"]),
            ]
            資訊內容 = "".join(
                f"<div><strong>{html.escape(欄名)}：</strong>{顯示值(值)}</div>"
                for 欄名, 值 in 資訊列
            )
            標記們.append(
                ipyleaflet.Marker(
                    location=(float(站["latitude"]), float(站["longitude"])),
                    title=站名,
                    icon=圖示,
                    popup=ipywidgets.HTML(
                        value=(
                            '<div style="min-width:180px;line-height:1.7">'
                            f"{資訊內容}</div>"
                        )
                    ),
                )
            )

        地圖.add_layer(
            ipyleaflet.MarkerCluster(
                markers=標記們,
                name="YouBike 站點",
                show_coverage_on_hover=False,
                spiderfy_on_max_zoom=True,
                disable_clustering_at_zoom=17,
            )
        )
        圖例列 = "".join(
            '<div style="display:flex;align-items:center;gap:8px;margin-top:5px">'
            f'<span style="width:11px;height:11px;border-radius:50%;background:{顏色};'
            f'flex:none"></span><span>{html.escape(級距)}</span></div>'
            for 級距, 顏色 in 顏色對照.items()
        )
        圖例 = ipywidgets.HTML(
            value=(
                '<div style="background:white;padding:10px 12px;border-radius:6px;'
                'box-shadow:0 1px 5px #0005;color:#111827;font:12px/1.4 sans-serif;'
                'max-width:190px">'
                '<strong>可借車分級</strong>'
                f"{圖例列}</div>"
            )
        )
        圖例.layout.max_width = "190px"
        地圖.add_control(
            ipyleaflet.WidgetControl(widget=圖例, position="bottomright")
        )
        圖表重新量寬度.element()
        solara.display(地圖)


@solara.component
def Page():
    solara.Title("YouBike 空站觀察")
    solara.Style(頁面樣式)

    即時模式 = 時段.value == 即時選項
    即時結果 = solara.use_thread(
        lambda 停止事件: 即時資料更新(停止事件, 即時模式),
        dependencies=[即時模式],
    )
    即時資料, 即時更新時間, 即時錯誤 = 即時結果.value or (None, None, None)
    if 即時結果.error is not None:
        即時錯誤 = f"{type(即時結果.error).__name__}: {即時結果.error}"

    with solara.Column(classes=["整頁"], gap="16px"):
        # ---------- 容器 1：標題 ----------
        with solara.Column(classes=["容器", "標題容器"], gap="4px"):
            solara.Text("臺北 YouBike 空站觀察", classes=["大標題"])
            solara.Text("哪些行政區、哪些站最容易借不到車？", classes=["副標題"])

        # ---------- 容器 2：選項（兩個下拉選單並排，下面放滑桿） ----------
        with solara.Column(classes=["容器"], gap="8px"):
            # 寬螢幕兩個選單並排（各佔 6/12），手機上下排（各佔 12/12）。
            with solara.ColumnsResponsive(12, small=[6, 6]):
                solara.Select(label="時段", value=時段, values=[即時選項] + 時段們)
                solara.Select(label="行政區", value=行政區, values=行政區們)
            solara.SliderInt("空站門檻：可借車 ≤", value=門檻, min=0, max=5)
            solara.Text(
                f"可借車 ≤ {門檻.value} 台的站算「空站」，只計算營運中的站。",
                classes=["說明文字"],
            )

        if 即時模式 and 即時資料 is None:
            with solara.Column(classes=["容器"]):
                if 即時錯誤:
                    solara.Text(f"即時資料更新失敗：{即時錯誤}", classes=["說明文字"])
                    solara.Button("重新取得即時資料", on_click=即時結果.retry)
                else:
                    solara.Text("正在取得 YouBike 即時站點資料……", classes=["說明文字"])
        else:
            當時 = 即時資料 if 即時模式 else df[df["時段"] == 時段.value]
            各區表 = 各區空站比例(當時, 門檻.value)
            地圖資料 = (
                當時
                if 行政區.value == "全部"
                else 當時[當時["sarea"] == 行政區.value]
            )
            站點地圖(地圖資料, 選取站點.value)

            if 即時錯誤:
                with solara.Column(classes=["容器"]):
                    solara.Text(
                        f"即時資料更新失敗，地圖保留最近一次成功資料：{即時錯誤}",
                        classes=["說明文字"],
                    )
                    solara.Button("重新取得即時資料", on_click=即時結果.retry)

            # ---------- 容器 3：表格；容器 4：長條圖 ----------
            if 行政區.value != "全部" and 行政區.value not in 各區表["sarea"].values:
                with solara.Column(classes=["容器"]):
                    solara.Text("目前資料中沒有這個行政區的營運站點。", classes=["說明文字"])
            elif 行政區.value == "全部":
                內容_全部(各區表)
            else:
                內容_單區(當時, 各區表)

        # ---------- 容器 5：頁尾（資料來源） ----------
        with solara.Column(classes=["容器", "頁尾"], gap="0px"):
            if 即時模式:
                資料時間 = 即時更新時間 or "等待首次更新"
                solara.Text(
                    "資料來源：臺北市 YouBike 2.0 即時資料（臺北市資料大平臺），"
                    f"依政府資料開放授權條款第 1 版使用。最近成功抓取時間：{資料時間}；"
                    f"每 {即時更新秒數} 秒更新一次。"
                )
            else:
                solara.Text(
                    "資料來源：臺北市 YouBike 2.0 即時資料（臺北市資料大平臺），"
                    f"依政府資料開放授權條款第 1 版使用。資料時間：{時段.value}。"
                )
            solara.Text(
                "行政區界線：內政部國土測繪中心「鄉鎮市區界線（TWD97 經緯度）」，"
                "依政府資料開放授權條款第 1 版使用。「臺大公館校區」的站已依經緯度歸入所在行政區。"
            )
            solara.Text("本網頁使用 Solara 製作")


@solara.component
def 內容_全部(各區表):
    """選「全部」時：一個容器放各區統計表，下一個容器放和容器同寬的各區比較圖。"""
    with solara.Column(classes=["容器"]):
        solara.Text(f"各區空站比例（{時段.value}）", classes=["容器標題"])
        solara.DataFrame(各區表格(各區表), items_per_page=12)

    with solara.Column(classes=["容器"]):
        圖表重新量寬度.element()
        solara.Text("各區空站比例長條圖", classes=["容器標題"])
        solara.FigurePlotly(各區比較圖(各區表, "全部"))


@solara.component
def 內容_單區(當時, 各區表):
    """選了某一區時：一個容器放該區各站明細，下一個容器並排兩張圖。"""
    站表 = 某區各站(當時, 行政區.value, 門檻.value)
    空站數 = (站表["狀態"] == "空站").sum()
    排名 = 各區表.index[各區表["sarea"] == 行政區.value][0] + 1  # 各區表已依空站比例由高到低排好
    顯示站數 = min(30, len(站表))  # 一區最多兩百多站，圖只畫最缺車的 30 站，完整清單看表格
    圖高度 = 90 + 24 * 顯示站數  # 兩張圖並排，用同一個高度才整齊（每站 24 px）

    with solara.Column(classes=["容器"]):
        solara.Text(f"{行政區.value}各站明細（{時段.value}）", classes=["容器標題"])
        solara.Text(
            "在站點資料列的任一欄位按 ⋮，選「地圖定位」即可跳到該站。",
            classes=["說明文字"],
        )
        solara.Text(
            f"營運中 {len(站表)} 站，空站 {空站數} 站（{空站數 / len(站表):.1%}），"
            f"空站比例在全市 {len(各區表)} 區中排第 {排名}。",
            classes=["說明文字"],
        )
        表格欄位 = [欄位 for 欄位 in 站表.columns if 欄位 != "sno"]

        def 地圖定位(欄位, 列號):
            if 欄位 not in 表格欄位:
                raise ValueError(f"無法定位表格欄位：{欄位}")
            選取站點.value = str(站表.loc[int(列號), "sno"])

        solara.DataFrame(
            站表[表格欄位],
            items_per_page=10,
            cell_actions=[
                solara.CellAction(
                    name="地圖定位",
                    icon="mdi-map-marker",
                    on_click=地圖定位,
                )
            ],
        )

    with solara.Column(classes=["容器"]):
        圖表重新量寬度.element()
        with solara.ColumnsResponsive(12, medium=[6, 6]):  # 寬螢幕兩張圖並排，手機上下排
            with solara.Column():
                solara.Text("各區空站比例", classes=["容器標題"])
                solara.Text(f"橘色是{行政區.value}", classes=["說明文字", "圖說明"])
                solara.FigurePlotly(各區比較圖(各區表, 行政區.value, 圖高度))
            with solara.Column():
                solara.Text(f"{行政區.value}最缺車的 {顯示站數} 站", classes=["容器標題"])
                solara.Text("有顏色的是可借車（紅色是空站），灰色是空位；滑鼠移到長條上可看地址。", classes=["說明文字", "圖說明"])
                solara.FigurePlotly(單區各站圖(站表.head(顯示站數), 圖高度))
