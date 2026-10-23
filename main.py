import os
import sys
import re
import json
import time
import threading
import subprocess
import urllib.request
import webbrowser
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

# ==================== 路徑與環境配置 ====================
def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

ADB_BIN = get_resource_path(os.path.join("platform-tools", "adb.exe"))
LAUNCHER_APK = get_resource_path(os.path.join("assets", "launcher.apk"))
LAUNCHER_PKG_FILE = get_resource_path(os.path.join("assets", "launcher_pkg.txt"))
BASE_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
CONFIG_FILE = os.path.join(BASE_DIR, "ai_config.json")

# 讀取編譯階段自動提取的 Gathin23/cleanyourtv/launcher 真實包名
DYNAMIC_LAUNCHER_PKG = "com.cleanyourtv.launcher"
if os.path.exists(LAUNCHER_PKG_FILE):
    try:
        with open(LAUNCHER_PKG_FILE, "r", encoding="utf-8") as f:
            read_pkg = f.read().strip()
            if read_pkg:
                DYNAMIC_LAUNCHER_PKG = read_pkg
    except Exception:
        pass

# Gathin23 原生 Apple TV 風格桌面已知與動態包名集合 (用於白名單保護與還原卸載)
CUSTOM_LAUNCHER_PKGS = {
    DYNAMIC_LAUNCHER_PKG,
    "com.cleanyourtv.launcher",
    "dev.gathin.cleanyourtv",
    "com.gathin.cleanyourtv",
    "com.example.launcher",
    "com.spocky.projengmenu"
}

# ==================== 驗證攔截包與完整原方案禁用列表 ====================
# 1. 各大電視品牌禁止安裝第三方 APK 的安全驗證包名單
KNOWN_INSTALL_BLOCKERS = [
    "com.tcl.apkverifier",
    "com.tcl.security",
    "com.tcl.guard",
    "com.tcl.appmarket2.verifier",
    "com.ffalcon.apkverifier",
    "com.hisense.tv.security",
    "com.hisense.appverifier",
    "com.miui.guardprovider",
    "com.xiaomi.mitv.security",
    "com.miui.securitycenter",
    "com.skyworth.security",
    "com.coocaa.security",
    "com.konka.security",
    "com.changhong.security",
    "com.google.android.packageinstaller.verifier"
]

VERIFIER_REGEX = re.compile(
    r"(apkverifier|appverifier|installverifier|securityguard|tvsecurity|guardprovider|packageverifier)",
    re.IGNORECASE
)

# 2. 原方案完整禁用套件清單 (涵蓋 Google TV / Android TV 原廠桌面、推薦服務、遙測廣告與品牌預裝肥大內容)
DEFAULT_BLOATWARE = [
    # --- Google TV / Android TV 原廠桌面與首頁廣告推薦流 (核心替換對象) ---
    "com.google.android.tvlauncher",               # Android TV 原廠桌面
    "com.google.android.tungsten.setupwraith",     # Google TV Launcher 核心守護進程
    "com.google.android.tvrecommendations",        # 首頁橫幅廣告與推薦橫條

    # --- Google 預裝非必要系統肥大套件与遙測服務 ---
    "com.google.android.videos",                   # Google Play Movies & TV / Google TV 商城
    "com.google.android.music",                    # Google Play Music
    "com.google.android.youtube.tvmusic",          # YouTube Music
    "com.google.android.play.games",               # Google Play 遊戲
    "com.google.android.leanbacklauncher.recommendations", # 舊版推薦服務
    "com.google.android.feedback",                 # 錯誤回報與遙測
    "com.google.android.partnersetup",             # 合作夥伴廣告客製化介面
    "com.google.android.syncadapters.calendar",    # 日曆同步 (電視無需使用)
    "com.google.android.syncadapters.contacts",    # 聯絡人同步 (電視無需使用)
    "com.android.dreams.basic",                    # 基礎螢幕保護程式
    "com.android.printspooler",                    # 列印服務 (電視無需使用)
    "com.android.bips",                            # 內建列印服務

    # --- 常見預裝串流與合作推廣肥大軟體 (Bloatware) ---
    "com.amazon.amazonvideo.livingroom",           # Amazon Prime Video 預裝版
    "com.netflix.ninja",                           # Netflix (若不需要可停用，也可於清單取消)
    "com.disney.disneyplus",                       # Disney+ 預裝版
    "tv.pluto.android",                            # Pluto TV
    "com.tubitv",                                  # Tubi TV
    "com.apple.atve.androidtv.appletv",            # Apple TV+ 預裝版

    # --- Sony / Bravia 電視專屬預裝與廣告服務 ---
    "com.sony.dtv.osat.music",
    "com.sony.dtv.youview",
    "com.sony.dtv.braviapcore",
    "com.sony.dtv.b2b.hotelmode",
    "com.sony.dtv.sonytvplayer",
    "com.sony.dtv.tvx",
    "com.sony.dtv.livingdecor",
    "com.sony.dtv.promotions",
    "com.sony.dtv.InteractiveApplicationManager",

    # --- TCL / 雷鳥 (FFALCON) / 海信 (Hisense) / 小米 (Xiaomi) 預裝與廣告定制 ---
    "com.tcl.partnercustomizer",
    "com.tcl.messagebox",
    "com.tcl.cyberui",                             # TCL 瀑布流桌面
    "com.tcl.bi",                                  # TCL 數據統計遙測
    "com.hisense.tv.partnercustomizer",
    "com.mitv.tvhome",                             # 小米 PatchWall 廣告桌面
    "com.xiaomi.mitv.DSA",                         # 小米系統廣告服務
    "com.xiaomi.mitv.upgrade",
    "com.xiaomi.mitv.shop",
    "org.droidtv.nettv.market"                     # Philips 預裝市場
]

# 3. 核心系統保護白名單 (包含系統核心組件 + Gathin23 原生 Apple TV 風格桌面)
CORE_WHITELIST = {
    "android",
    "com.android.systemui",
    "com.android.settings",
    "com.android.providers.settings",
    "com.google.android.gms",
    "com.google.android.gsf",
    "com.android.vending",
    "com.android.packageinstaller",
    "com.google.android.packageinstaller",
    "com.android.inputmethod.latin",
    "com.google.android.inputmethod.latin",
    "com.google.android.katniss"                   # Google 語音助理 (保留以免遙控器語音鍵失效)
} | CUSTOM_LAUNCHER_PKGS

# ==================== ADB 底層工具函式 (隱藏黑窗) ====================
def run_adb(args, timeout=25):
    cmd = [ADB_BIN] + args
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
    try:
        res = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="ignore",
            timeout=timeout, startupinfo=startupinfo
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "指令執行超時 (Timeout)"
    except Exception as e:
        return -1, "", str(e)

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

# ==================== 現代 macOS 風格主程式 GUI ====================
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class MacOSTVCleanerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("CleanYourTV Pro — macOS Edition (Native Apple TV Launcher)")
        self.geometry("1000x660")
        self.minsize(940, 620)
        self.configure(fg_color="#1E1E1E")

        self.cfg = load_config()
        self.device_id = None
        self.installed_launcher_pkg = DYNAMIC_LAUNCHER_PKG

        self._build_layout()
        self.log(f"系統就緒。內嵌原生桌面保護包名: {self.installed_launcher_pkg}")
        threading.Thread(target=lambda: run_adb(["start-server"]), daemon=True).start()

    # -------------------- UI 佈局建構 --------------------
    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # 左側：macOS 側邊欄 (Sidebar)
        self.sidebar = ctk.CTkFrame(self, width=235, corner_radius=0, fg_color="#252526")
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        # macOS 紅黃綠交通燈裝飾
        dots_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        dots_frame.pack(anchor="w", padx=18, pady=(16, 10))
        for color in ("#FF5F56", "#FFBD2E", "#27C93F"):
            dot = ctk.CTkLabel(dots_frame, text="●", text_color=color, font=("Segoe UI", 16))
            dot.pack(side="left", padx=3)

        ctk.CTkLabel(
            self.sidebar, text="CleanYourTV",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color="#FFFFFF"
        ).pack(anchor="w", padx=20, pady=(4, 2))

        ctk.CTkLabel(
            self.sidebar, text="Apple TV 風格桌面與系統精簡",
            font=ctk.CTkFont(size=12), text_color="#8E8E93"
        ).pack(anchor="w", padx=20, pady=(0, 18))

        self.nav_buttons = {}
        nav_items = [
            ("connect", "📡  設備連線與配對"),
            ("clean",   "🍎  突破限制與換桌面"),
            ("ai",      "🤖  豆包 / WorkBuddy 分析"),
            ("restore", "🛡️  一鍵救磚與還原")
        ]
        for key, text in nav_items:
            btn = ctk.CTkButton(
                self.sidebar, text=text, anchor="w", height=40, corner_radius=8,
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color="transparent", text_color="#EBEBF5", hover_color="#3A3A3C",
                command=lambda k=key: self.switch_tab(k)
            )
            btn.pack(fill="x", padx=12, pady=4)
            self.nav_buttons[key] = btn

        self.status_card = ctk.CTkFrame(self.sidebar, corner_radius=10, fg_color="#1C1C1E")
        self.status_card.pack(side="bottom", fill="x", padx=14, pady=16)
        self.status_dot = ctk.CTkLabel(self.status_card, text="● 未連接電視", text_color="#FF453A", font=ctk.CTkFont(size=12, weight="bold"))
        self.status_dot.pack(padx=12, pady=10)

        # 右側主內容區
        self.right_container = ctk.CTkFrame(self, fg_color="#1E1E1E", corner_radius=0)
        self.right_container.grid(row=0, column=1, sticky="nsew", padx=18, pady=16)
        self.right_container.grid_rowconfigure(0, weight=1)
        self.right_container.grid_rowconfigure(1, weight=0)
        self.right_container.grid_columnconfigure(0, weight=1)

        self.pages_frame = ctk.CTkFrame(self.right_container, fg_color="transparent")
        self.pages_frame.grid(row=0, column=0, sticky="nsew")
        self.pages_frame.grid_rowconfigure(0, weight=1)
        self.pages_frame.grid_columnconfigure(0, weight=1)

        self.pages = {
            "connect": self._create_connect_page(),
            "clean": self._create_clean_page(),
            "ai": self._create_ai_page(),
            "restore": self._create_restore_page()
        }

        # 底部 macOS Console 日誌面板
        log_card = ctk.CTkFrame(self.right_container, corner_radius=12, fg_color="#141414", height=185)
        log_card.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        log_card.grid_propagate(False)
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(log_card, text="  >_ 即時執行日誌 (ADB Console Output)", font=ctk.CTkFont(size=11, weight="bold"), text_color="#8E8E93", anchor="w").grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 0))

        self.log_box = ctk.CTkTextbox(log_card, fg_color="#141414", text_color="#30D158", font=ctk.CTkFont(family="Consolas", size=12), wrap="word")
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=8, pady=(2, 8))

        self.switch_tab("connect")

    def switch_tab(self, tab_key):
        for k, btn in self.nav_buttons.items():
            btn.configure(fg_color="#0A84FF" if k == tab_key else "transparent")
        for k, page in self.pages.items():
            if k == tab_key:
                page.grid(row=0, column=0, sticky="nsew")
            else:
                page.grid_forget()

    def log(self, msg):
        def _append():
            ts = time.strftime("%H:%M:%S")
            self.log_box.insert("end", f"[{ts}] {msg}\n")
            self.log_box.see("end")
        self.after(0, _append)

    def set_connected_device(self, dev_id):
        self.device_id = dev_id
        def _upd():
            if dev_id:
                self.status_dot.configure(text=f"● 已連線: {dev_id}", text_color="#30D158")
            else:
                self.status_dot.configure(text="● 未連接電視", text_color="#FF453A")
        self.after(0, _upd)

    # -------------------- 頁面 1：設備連線與 Android 11~14 配對 --------------------
    def _create_connect_page(self):
        frame = ctk.CTkFrame(self.pages_frame, fg_color="transparent")
        frame.grid_columnconfigure((0, 1), weight=1)

        pair_card = ctk.CTkFrame(frame, corner_radius=14, fg_color="#2C2C2E")
        pair_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=4)

        ctk.CTkLabel(pair_card, text="步驟 1：首次無線調試配對 (Android 11~14)", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=18, pady=(16, 4))
        ctk.CTkLabel(pair_card, text="在電視「無線調試」點開「使用配對碼配對設備」彈窗，\n填寫彈窗上的 IP:配對埠 與 6 位數配對碼：", font=ctk.CTkFont(size=12), text_color="#AEAEB2", justify="left").pack(anchor="w", padx=18, pady=(0, 12))

        self.pair_ip_entry = ctk.CTkEntry(pair_card, placeholder_text="配對 IP:Port (例如 192.168.1.100:38192)", height=36)
        self.pair_ip_entry.pack(fill="x", padx=18, pady=6)

        self.pair_code_entry = ctk.CTkEntry(pair_card, placeholder_text="6 位數配對碼 (例如 849201)", height=36)
        self.pair_code_entry.pack(fill="x", padx=18, pady=6)

        btn_row = ctk.CTkFrame(pair_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=18, pady=12)
        ctk.CTkButton(btn_row, text="🔍 自動掃描配對埠", fg_color="#3A3A3C", hover_color="#48484A", width=130, command=self.action_scan_mdns).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="🔗 執行配對 (adb pair)", fg_color="#0A84FF", command=self.action_pair_device).pack(side="left", fill="x", expand=True)

        conn_card = ctk.CTkFrame(frame, corner_radius=14, fg_color="#2C2C2E")
        conn_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=4)

        ctk.CTkLabel(conn_card, text="步驟 2：建立連線 (自動固化 5555 埠)", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=18, pady=(16, 4))
        ctk.CTkLabel(conn_card, text="配對成功或已配對過的電視，請輸入「無線調試」\n主頁面的 IP:連線埠 (舊電視直接填 IP 即可)：", font=ctk.CTkFont(size=12), text_color="#AEAEB2", justify="left").pack(anchor="w", padx=18, pady=(0, 12))

        self.conn_ip_entry = ctk.CTkEntry(conn_card, placeholder_text="電視 IP 或 IP:隨機連線埠 (如 192.168.1.100:42519)", height=36)
        self.conn_ip_entry.pack(fill="x", padx=18, pady=6)
        if self.cfg.get("last_tv_ip"):
            self.conn_ip_entry.insert(0, self.cfg.get("last_tv_ip"))

        self.lock_5555_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(conn_card, text="連上隨機埠後自動開啟固定 5555 埠 (下次免查埠)", variable=self.lock_5555_var, font=ctk.CTkFont(size=12)).pack(anchor="w", padx=18, pady=10)

        ctk.CTkButton(conn_card, text="⚡ 立即連接電視 (adb connect)", height=38, fg_color="#30D158", text_color="#000000", hover_color="#28B84C", font=ctk.CTkFont(weight="bold"), command=self.action_connect_device).pack(fill="x", padx=18, pady=(6, 16))

        return frame

    # -------------------- 頁面 2：突破限制 + 原生 Apple TV 桌面 + 原方案禁用清單 --------------------
    def _create_clean_page(self):
        frame = ctk.CTkFrame(self.pages_frame, fg_color="transparent")
        frame.grid_columnconfigure((0, 1), weight=1)
        frame.grid_rowconfigure(0, weight=1)

        # 左側：執行控制區
        left_card = ctk.CTkFrame(frame, corner_radius=14, fg_color="#2C2C2E")
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=4)

        ctk.CTkLabel(left_card, text="🛡️ 階段一：解除第三方安裝攔截", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            left_card,
            text="關閉系統驗證鎖 (package_verifier_enable=0 等 3 項)\n並自動掃描禁用 TCL/海信/小米等內建安裝攔截器。",
            font=ctk.CTkFont(size=11), text_color="#AEAEB2", justify="left"
        ).pack(anchor="w", padx=16, pady=(0, 8))

        ctk.CTkButton(
            left_card, text="🔓 單獨執行：解除安裝限制與驗證包", height=34,
            fg_color="#FF9F0A", text_color="#000000", hover_color="#E08900", font=ctk.CTkFont(weight="bold"),
            command=lambda: threading.Thread(target=self.worker_bypass_verification, daemon=True).start()
        ).pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(left_card, text="🍎 階段二：安裝 Gathin23 原生桌面 + 精簡", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(4, 4))
        ctk.CTkLabel(
            left_card,
            text=f"• 安裝內嵌 Gathin23/cleanyourtv 原生 Apple TV 桌面\n  (受保護包名: {self.installed_launcher_pkg})\n• 自動停用右側列出的原方案肥大軟體與原廠桌面",
            font=ctk.CTkFont(size=11), text_color="#AEAEB2", justify="left"
        ).pack(anchor="w", padx=16, pady=(0, 10))

        ctk.CTkButton(
            left_card, text="✨ 一鍵執行：解鎖 + 換 Apple TV 桌面 + 停用肥大應用", height=42,
            fg_color="#0A84FF", font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: threading.Thread(target=self.worker_full_clean, daemon=True).start()
        ).pack(fill="x", padx=16, pady=(4, 14))

        # 右側：原方案預設禁用清單 (可隨時自訂增刪)
        right_card = ctk.CTkFrame(frame, corner_radius=14, fg_color="#2C2C2E")
        right_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=4)
        right_card.grid_rowconfigure(1, weight=1)
        right_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right_card, text="📦 原方案預設禁用套件清單 (可自由增刪)", font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))

        self.default_bloat_textbox = ctk.CTkTextbox(right_card, fg_color="#1C1C1E", text_color="#EBEBF5", font=ctk.CTkFont(family="Consolas", size=11))
        self.default_bloat_textbox.grid(row=1, column=0, sticky="nsew", padx=16, pady=(4, 14))
        self.default_bloat_textbox.insert("1.0", "\n".join(DEFAULT_BLOATWARE))

        return frame

    # -------------------- 頁面 3：豆包 / WorkBuddy AI 分析 --------------------
    def _create_ai_page(self):
        frame = ctk.CTkFrame(self.pages_frame, fg_color="transparent")
        frame.grid_columnconfigure((0, 1), weight=1)
        frame.grid_rowconfigure(0, weight=1)

        left_card = ctk.CTkFrame(frame, corner_radius=14, fg_color="#2C2C2E")
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=4)

        ctk.CTkLabel(left_card, text="🤖 豆包 / WorkBuddy 登入與分析", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=16, pady=(14, 6))

        self.ai_mode_seg = ctk.CTkSegmentedButton(left_card, values=["網頁登入連動 (免Key)", "API Key 直連"], command=self._toggle_ai_mode_ui)
        self.ai_mode_seg.pack(fill="x", padx=16, pady=6)
        self.ai_mode_seg.set("API Key 直連" if self.cfg.get("mode") == "api" else "網頁登入連動 (免Key)")

        self.web_url_entry = ctk.CTkEntry(left_card, placeholder_text="網頁端網址 (預設豆包 https://www.doubao.com/chat/)", height=32)
        self.web_url_entry.pack(fill="x", padx=16, pady=4)
        self.web_url_entry.insert(0, self.cfg.get("web_url", "https://www.doubao.com/chat/"))

        self.api_url_entry = ctk.CTkEntry(left_card, placeholder_text="API URL (火山方舟或 WorkBuddy OpenAI 接口)", height=32)
        self.api_url_entry.pack(fill="x", padx=16, pady=4)
        self.api_url_entry.insert(0, self.cfg.get("api_url", "https://ark.cn-beijing.volces.com/api/v3/chat/completions"))

        self.api_model_entry = ctk.CTkEntry(left_card, placeholder_text="Model ID (如 doubao-pro-32k 或接入點 ep-xxx)", height=32)
        self.api_model_entry.pack(fill="x", padx=16, pady=4)
        self.api_model_entry.insert(0, self.cfg.get("model", ""))

        self.api_key_entry = ctk.CTkEntry(left_card, placeholder_text="API Key (Bearer Token)", show="*", height=32)
        self.api_key_entry.pack(fill="x", padx=16, pady=4)
        self.api_key_entry.insert(0, self.cfg.get("api_key", ""))

        ctk.CTkButton(left_card, text="1. 讀取電視套件並發送給 AI 分析", fg_color="#0A84FF", height=36, command=self.action_start_ai_analysis).pack(fill="x", padx=16, pady=(10, 6))

        right_card = ctk.CTkFrame(frame, corner_radius=14, fg_color="#2C2C2E")
        right_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=4)
        right_card.grid_rowconfigure(1, weight=1)
        right_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right_card, text="📋 AI 建議停用清單 (已自動過濾保護新桌面)", font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))

        self.ai_pkg_textbox = ctk.CTkTextbox(right_card, fg_color="#1C1C1E", text_color="#EBEBF5", font=ctk.CTkFont(family="Consolas", size=12))
        self.ai_pkg_textbox.grid(row=1, column=0, sticky="nsew", padx=16, pady=6)

        ctk.CTkButton(right_card, text="⚡ 2. 一鍵停用上方列出的所有套件", fg_color="#FF453A", hover_color="#D70015", height=36, font=ctk.CTkFont(weight="bold"), command=self.action_apply_ai_disable).grid(row=2, column=0, sticky="ew", padx=16, pady=(4, 14))

        self._toggle_ai_mode_ui(self.ai_mode_seg.get())
        return frame

    def _toggle_ai_mode_ui(self, val):
        if "網頁" in val:
            self.web_url_entry.configure(state="normal")
            self.api_url_entry.configure(state="disabled")
            self.api_model_entry.configure(state="disabled")
            self.api_key_entry.configure(state="disabled")
        else:
            self.web_url_entry.configure(state="disabled")
            self.api_url_entry.configure(state="normal")
            self.api_model_entry.configure(state="normal")
            self.api_key_entry.configure(state="normal")

    # -------------------- 頁面 4：一鍵救磚與原廠還原 --------------------
    def _create_restore_page(self):
        frame = ctk.CTkFrame(self.pages_frame, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)

        card = ctk.CTkFrame(frame, corner_radius=14, fg_color="#2C2C2E")
        card.grid(row=0, column=0, sticky="nsew", pady=4)

        ctk.CTkLabel(card, text="🛡️ 一鍵恢復原廠狀態 (救磚還原)", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=20, pady=(18, 6))
        ctk.CTkLabel(
            card,
            text="點擊下方按鈕將自動執行：\n"
                 "1. 掃描並重新啟用 (pm enable) 所有被停用的系統應用與 Google TV / Android TV 原廠桌面。\n"
                 f"2. 若勾選下方選項，將同步卸載 Gathin23 原生 Apple TV 桌面 ({self.installed_launcher_pkg}) 並切回原廠首頁。\n"
                 "   (若不勾選，則保留新桌面在背景保護，不被誤刪)",
            font=ctk.CTkFont(size=12), text_color="#AEAEB2", justify="left"
        ).pack(anchor="w", padx=20, pady=(0, 14))

        self.uninstall_launcher_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(card, text=f"還原為原廠桌面時，一併卸載替換的 Apple TV 桌面 ({self.installed_launcher_pkg})", variable=self.uninstall_launcher_var).pack(anchor="w", padx=20, pady=8)

        ctk.CTkButton(
            card, text="🔄 立即恢復電視所有原廠應用與預設桌面", height=42,
            fg_color="#30D158", text_color="#000000", hover_color="#28B84C", font=ctk.CTkFont(size=14, weight="bold"),
            command=lambda: threading.Thread(target=self.worker_restore_all, daemon=True).start()
        ).pack(fill="x", padx=20, pady=16)

        return frame

    # ==================== 核心業務邏輯與背景工作執行緒 ====================

    def action_scan_mdns(self):
        def _scan():
            self.log("正在透過 mDNS 掃描區域網路內的 Android 11~14 無線調試廣播...")
            _, out, _ = run_adb(["mdns", "services"])
            pair_found, conn_found = [], []
            for line in out.splitlines():
                m = re.search(r'(\d+\.\d+\.\d+\.\d+:\d+)', line)
                if m:
                    addr = m.group(1)
                    if "_adb-tls-pairing._tcp" in line:
                        pair_found.append(addr)
                    elif "_adb-tls-connect._tcp" in line:
                        conn_found.append(addr)
            if pair_found:
                self.log(f"[+] 發現正在等待配對的設備: {pair_found[0]}")
                self.after(0, lambda: (self.pair_ip_entry.delete(0, "end"), self.pair_ip_entry.insert(0, pair_found[0])))
            if conn_found:
                self.log(f"[+] 發現可連線的無線調試埠: {conn_found[0]}")
                self.after(0, lambda: (self.conn_ip_entry.delete(0, "end"), self.conn_ip_entry.insert(0, conn_found[0])))
            if not pair_found and not conn_found:
                self.log("[-] 未掃描到 mDNS 廣播，請直接手動輸入電視畫面上的 IP:Port。")
        threading.Thread(target=_scan, daemon=True).start()

    def action_pair_device(self):
        pair_addr = self.pair_ip_entry.get().strip()
        pair_code = self.pair_code_entry.get().strip()
        if not pair_addr or not pair_code:
            messagebox.showwarning("提示", "請輸入電視配對彈窗上的【IP:配對埠】與【6 位數配對碼】！")
            return
        def _pair():
            self.log(f"正在向 {pair_addr} 發送配對碼 [{pair_code}] ...")
            _, out, err = run_adb(["pair", pair_addr, pair_code])
            combined = f"{out} {err}"
            if "successfully paired" in combined.lower():
                self.log("[√] 配對成功！電視彈窗應已自動關閉。請查看電視主頁面的連線埠進行步驟 2 連線。")
                ip_only = pair_addr.split(":")[0]
                self.after(0, lambda: (self.conn_ip_entry.delete(0, "end"), self.conn_ip_entry.insert(0, f"{ip_only}:")))
            else:
                self.log(f"[-] 配對失敗: {combined}")
        threading.Thread(target=_pair, daemon=True).start()

    def action_connect_device(self):
        raw_target = self.conn_ip_entry.get().strip()
        if not raw_target:
            messagebox.showwarning("提示", "請輸入電視 IP 或 IP:連線埠！")
            return
        target = f"{raw_target}:5555" if ":" not in raw_target else raw_target

        def _conn():
            self.log(f"正在連線至 {target} ...")
            _, out, err = run_adb(["connect", target])
            time.sleep(1.5)
            _, dev_out, _ = run_adb(["devices"])
            if f"{target}\tunauthorized" in dev_out:
                self.log("[!] 電視尚未授權！請看電視畫面勾選「永遠允許」並點擊確定...")
                messagebox.showinfo("請在電視上確認授權", "請留意電視畫面彈出的偵錯授權視窗，\n勾選「永遠允許」並點擊確定後，按 OK 繼續。")
                _, dev_out, _ = run_adb(["devices"])

            if f"{target}\tdevice" in dev_out:
                self.log(f"[√] 成功連接至電視: {target}")
                pure_ip = target.split(":")[0]
                self.cfg["last_tv_ip"] = pure_ip
                save_config(self.cfg)

                final_dev = target
                if self.lock_5555_var.get() and not target.endswith(":5555"):
                    self.log("[*] 正在將隨機埠固化為 5555 埠 (adb tcpip 5555)...")
                    run_adb(["-s", target, "tcpip", "5555"])
                    time.sleep(2)
                    run_adb(["connect", f"{pure_ip}:5555"])
                    _, dev_out2, _ = run_adb(["devices"])
                    if f"{pure_ip}:5555\tdevice" in dev_out2:
                        final_dev = f"{pure_ip}:5555"
                        self.log(f"[√] 已成功切換並固定至 {final_dev}！")

                self.set_connected_device(final_dev)
            else:
                self.log(f"[-] 連線失敗: {out} {err}")
        threading.Thread(target=_conn, daemon=True).start()

    # -------------------- 階段一：查詢並禁用所有第三方安裝限制與驗證包 --------------------
    def worker_bypass_verification(self):
        if not self.device_id:
            messagebox.showwarning("未連線", "請先在「設備連線與配對」頁面連接電視！")
            return False

        self.log("=" * 55)
        self.log("🔍 [步驟 1/2] 正在檢測並修改系統底層安裝限制參數 (Settings DB)...")

        settings_cmds = [
            ("global", "package_verifier_enable", "0", "關閉全域包驗證器"),
            ("global", "verifier_verify_adb_installs", "0", "關閉 ADB 安裝驗證"),
            ("secure", "install_non_market_apps", "1", "允許安裝未知來源應用")
        ]

        for namespace, key, target_val, desc in settings_cmds:
            _, cur_val, _ = run_adb(["-s", self.device_id, "shell", "settings", "get", namespace, key])
            run_adb(["-s", self.device_id, "shell", "settings", "put", namespace, key, target_val])
            _, new_val, _ = run_adb(["-s", self.device_id, "shell", "settings", "get", namespace, key])
            self.log(f"  ✅ {namespace} {key}: {cur_val} -> {new_val} ({desc})")

        self.log("🔍 [步驟 2/2] 正在掃描電視內禁止安裝第三方應用的安全驗證套件...")
        _, pkg_out, _ = run_adb(["-s", self.device_id, "shell", "pm", "list", "packages", "-e"])
        installed_pkgs = [line.replace("package:", "").strip() for line in pkg_out.splitlines() if line.strip()]

        detected_blockers = set()
        for pkg in installed_pkgs:
            if pkg in CORE_WHITELIST:
                continue
            if pkg in KNOWN_INSTALL_BLOCKERS or VERIFIER_REGEX.search(pkg):
                detected_blockers.add(pkg)

        if detected_blockers:
            self.log(f"⚠️ 檢測到 {len(detected_blockers)} 個安裝攔截套件，正在全部強制禁用...")
            for blocker in sorted(detected_blockers):
                _, d_out, _ = run_adb(["-s", self.device_id, "shell", "pm", "disable-user", "--user", "0", blocker])
                run_adb(["-s", self.device_id, "shell", "am", "force-stop", blocker])
                self.log(f"    🚫 已禁用攔截器: {blocker} ({d_out})")
        else:
            self.log("✅ 未檢測到額外的廠商專屬 APK 攔截套件，系統驗證鎖已全面解除。")

        self.log("=" * 55)
        return True

    # -------------------- 階段二：安裝 Gathin23 原生桌面 + 停用原方案肥大列表 --------------------
    def worker_full_clean(self):
        if not self.worker_bypass_verification():
            return

        # 安裝前先記錄第三方套件清單，以便安裝後雙重確認新桌面的真實包名
        _, before_out, _ = run_adb(["-s", self.device_id, "shell", "pm", "list", "packages", "-3"])
        before_pkgs = {l.replace("package:", "").strip() for l in before_out.splitlines() if l.strip()}

        launcher_ok = False
        if os.path.exists(LAUNCHER_APK) and os.path.getsize(LAUNCHER_APK) > 1024:
            self.log(f"🍎 正在安裝 Gathin23/cleanyourtv 原生 Apple TV 風格桌面...")
            code, out, err = run_adb(["-s", self.device_id, "install", "-r", LAUNCHER_APK], timeout=90)
            if code == 0 and "Success" in out:
                launcher_ok = True
                # 動態偵測實際新增的桌面包名並寫入 CORE_WHITELIST 保護
                _, after_out, _ = run_adb(["-s", self.device_id, "shell", "pm", "list", "packages", "-3"])
                after_pkgs = {l.replace("package:", "").strip() for l in after_out.splitlines() if l.strip()}
                new_diff = after_pkgs - before_pkgs
                if new_diff:
                    actual_pkg = list(new_diff)[0]
                    self.installed_launcher_pkg = actual_pkg
                    CUSTOM_LAUNCHER_PKGS.add(actual_pkg)
                    CORE_WHITELIST.add(actual_pkg)

                self.log(f"  ✅ 原生桌面安裝成功！已將 [{self.installed_launcher_pkg}] 加入核心白名單保護。")
                # 嘗試自動綁定為系統預設 Home 桌面
                run_adb(["-s", self.device_id, "shell", "cmd", "package", "set-home-activity", f"{self.installed_launcher_pkg}/.MainActivity"])
            else:
                self.log(f"  ❌ 桌面安裝失敗 ({out} {err})，為防黑屏將保留原廠桌面！")
        else:
            self.log("⚠️ 未找到有效的內嵌 Launcher APK，將跳過停用原廠桌面。")

        # 讀取右側面板中的原方案禁用清單
        raw_list = self.default_bloat_textbox.get("1.0", "end").splitlines()
        target_bloatware = [l.split("#")[0].strip() for l in raw_list if l.split("#")[0].strip() and "." in l]

        self.log(f"🧹 正在執行原方案精簡清單 (共 {len(target_bloatware)} 項檢測)...")
        disabled_count = 0
        for pkg in target_bloatware:
            if pkg in CORE_WHITELIST:
                self.log(f"  [🛡️ 白名單保護] 跳過 {pkg}")
                continue
            if not launcher_ok and pkg in ["com.google.android.tvlauncher", "com.google.android.tungsten.setupwraith"]:
                self.log(f"  [跳過原廠桌面] {pkg}")
                continue
            _, out, _ = run_adb(["-s", self.device_id, "shell", "pm", "disable-user", "--user", "0", pkg])
            if "disabled-user" in out:
                disabled_count += 1
                self.log(f"  [√] 已停用: {pkg}")

        run_adb(["-s", self.device_id, "shell", "input", "keyevent", "KEYCODE_HOME"])
        self.log(f"🎉 全部流程執行完畢！共停用 {disabled_count} 個肥大組件，電視已切換至 Apple TV 風格桌面。")

    # -------------------- 豆包 / WorkBuddy AI 分析與停用 --------------------
    def action_start_ai_analysis(self):
        if not self.device_id:
            messagebox.showwarning("未連線", "請先連接電視！")
            return

        mode = "web" if "網頁" in self.ai_mode_seg.get() else "api"
        self.cfg.update({
            "mode": mode,
            "web_url": self.web_url_entry.get().strip(),
            "api_url": self.api_url_entry.get().strip(),
            "model": self.api_model_entry.get().strip(),
            "api_key": self.api_key_entry.get().strip()
        })
        save_config(self.cfg)

        def _analyze():
            self.log("正在從電視導出目前已啟用的套件清單 (已自動排除白名單與新桌面)...")
            _, out, _ = run_adb(["-s", self.device_id, "shell", "pm", "list", "packages", "-e"])
            pkgs = sorted([
                l.replace("package:", "").strip()
                for l in out.splitlines()
                if l.strip() and l.replace("package:", "").strip() not in CORE_WHITELIST
            ])
            if not pkgs:
                self.log("[-] 無法取得套件清單。")
                return

            prompt = (
                "你是一位資深 Android TV / Google TV 系統精簡專家。以下是從電視導出的已啟用套件名。\n"
                f"注意：千萬不要停用第三方桌面 ({', '.join(CUSTOM_LAUNCHER_PKGS)})。\n"
                "請挑選出可 100% 安全停用的『預裝垃圾、廣告系統、廠商監控與多餘影音應用』，並在回覆最後將包名每行一個列在 [SAFE_DISABLE_START] 與 [SAFE_DISABLE_END] 之間：\n\n"
                + "\n".join(pkgs)
            )

            if mode == "web":
                self.clipboard_clear()
                self.clipboard_append(prompt)
                self.log(f"[+] 已將 {len(pkgs)} 個套件與分析提示詞複製到剪貼簿！正在打開瀏覽器...")
                webbrowser.open(self.cfg["web_url"])
                self.log("[提示] 請在打開的豆包/WorkBuddy網頁按 Ctrl+V 發送，再將 AI 輸出的包名貼到右側清單框內。")
            else:
                self.log(f"正在呼叫 API ({self.cfg['api_url']}) 進行深度分析...")
                payload = {
                    "model": self.cfg["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1
                }
                req = urllib.request.Request(
                    self.cfg["api_url"],
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.cfg['api_key']}"},
                    method="POST"
                )
                try:
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        reply = json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"]
                        self.log("[√] AI 分析完成！")
                        if "[SAFE_DISABLE_START]" in reply and "[SAFE_DISABLE_END]" in reply:
                            block = reply.split("[SAFE_DISABLE_START]")[1].split("[SAFE_DISABLE_END]")[0].strip()
                        else:
                            block = reply
                        self.after(0, lambda: (self.ai_pkg_textbox.delete("1.0", "end"), self.ai_pkg_textbox.insert("1.0", block)))
                except Exception as e:
                    self.log(f"[-] API 請求失敗: {e}")

        threading.Thread(target=_analyze, daemon=True).start()

    def action_apply_ai_disable(self):
        if not self.device_id:
            messagebox.showwarning("未連線", "請先連接電視！")
            return
        raw_text = self.ai_pkg_textbox.get("1.0", "end").strip()
        pkgs = [l.strip() for l in raw_text.splitlines() if l.strip() and "." in l.strip() and not l.strip().startswith("[")]
        if not pkgs:
            messagebox.showwarning("清單為空", "右側文本框內沒有有效的套件名稱！")
            return

        def _disable():
            self.log(f"開始批量停用 AI 建議的 {len(pkgs)} 個套件...")
            for pkg in pkgs:
                if pkg in CORE_WHITELIST or pkg in CUSTOM_LAUNCHER_PKGS:
                    self.log(f"  [🛡️ 白名單保護] 已攔截並保護核心/新桌面套件: {pkg}")
                    continue
                _, out, _ = run_adb(["-s", self.device_id, "shell", "pm", "disable-user", "--user", "0", pkg])
                self.log(f"  [√] {pkg} -> {out}")
            self.log("🎉 AI 批量停用完成！")
        threading.Thread(target=_disable, daemon=True).start()

    # -------------------- 一鍵救磚還原 (保護或同步卸載原生新桌面) --------------------
    def worker_restore_all(self):
        if not self.device_id:
            messagebox.showwarning("未連線", "請先連接電視！")
            return
        self.log("正在掃描電視上所有處於 Disabled 狀態的套件...")
        _, out, _ = run_adb(["-s", self.device_id, "shell", "pm", "list", "packages", "-d"])
        disabled_pkgs = [l.replace("package:", "").strip() for l in out.splitlines() if l.strip()]

        for pkg in disabled_pkgs:
            run_adb(["-s", self.device_id, "shell", "pm", "enable", pkg])
            self.log(f"  [√] 已重新啟用: {pkg}")

        # 強制確保原廠桌面核心套件已啟用
        for stock in ("com.google.android.tvlauncher", "com.google.android.tungsten.setupwraith", "com.google.android.tvrecommendations"):
            run_adb(["-s", self.device_id, "shell", "pm", "enable", stock])

        # 根據勾選狀態決定是否卸載 Gathin23 原生 Apple TV 桌面
        if self.uninstall_launcher_var.get():
            self.log("正在卸載替換的第三方 Apple TV 桌面...")
            for l_pkg in CUSTOM_LAUNCHER_PKGS:
                _, u_out, _ = run_adb(["-s", self.device_id, "uninstall", l_pkg])
                if "Success" in u_out:
                    self.log(f"  [√] 已成功卸載新桌面: {l_pkg}")
        else:
            self.log(f"[🛡️ 已保留新桌面] {self.installed_launcher_pkg} 處於白名單保護狀態。")

        run_adb(["-s", self.device_id, "shell", "input", "keyevent", "KEYCODE_HOME"])
        self.log("🎉 電視已完全恢復為原廠初始狀態！")

if __name__ == "__main__":
    app = MacOSTVCleanerApp()
    app.mainloop()
