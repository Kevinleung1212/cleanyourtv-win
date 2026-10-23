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
from tkinter import messagebox, filedialog
import customtkinter as ctk

# ==================== 路徑與雙桌面資源配置 ====================
def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

ADB_BIN = get_resource_path(os.path.join("platform-tools", "adb.exe"))
CLEAN_APK = get_resource_path(os.path.join("assets", "cleanyourtv_launcher.apk"))
AERIAL_APK = get_resource_path(os.path.join("assets", "aerial_launcher.apk"))
CLEAN_PKG_FILE = get_resource_path(os.path.join("assets", "cleanyourtv_pkg.txt"))
AERIAL_PKG_FILE = get_resource_path(os.path.join("assets", "aerial_pkg.txt"))

BASE_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
CONFIG_FILE = os.path.join(BASE_DIR, "ai_config.json")

def _read_pkg_file(path, default_val):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                val = f.read().strip()
                if val:
                    return val
        except Exception:
            pass
    return default_val

CLEAN_LAUNCHER_PKG = _read_pkg_file(CLEAN_PKG_FILE, "com.cleanyourtv.launcher")
AERIAL_LAUNCHER_PKG = _read_pkg_file(AERIAL_PKG_FILE, "me.qust.aerial")

# 將兩款新桌面的所有可能包名全部納入保護集合
CUSTOM_LAUNCHER_PKGS = {
    CLEAN_LAUNCHER_PKG,
    AERIAL_LAUNCHER_PKG,
    "com.cleanyourtv.launcher",
    "dev.gathin.cleanyourtv",
    "me.qust.aerial",
    "com.pengchujin.aerial",
    "com.aerial.tv",
    "com.spocky.projengmenu"
}

STOCK_LAUNCHER_PKGS = [
    "com.google.android.tungsten.setupwraith",
    "com.google.android.apps.tv.launcherx",
    "com.google.android.tvlauncher",
    "com.google.android.tvrecommendations",
    "com.google.android.leanbacklauncher",
    "com.google.android.leanbacklauncher.recommendations",
    "com.tcl.cyberui",
    "com.mitv.tvhome"
]

KNOWN_INSTALL_BLOCKERS = [
    "com.tcl.apkverifier", "com.tcl.security", "com.tcl.guard",
    "com.tcl.appmarket2.verifier", "com.ffalcon.apkverifier",
    "com.hisense.tv.security", "com.hisense.appverifier",
    "com.miui.guardprovider", "com.xiaomi.mitv.security",
    "com.miui.securitycenter", "com.skyworth.security",
    "com.coocaa.security", "com.konka.security",
    "com.changhong.security", "com.google.android.packageinstaller.verifier"
]

VERIFIER_REGEX = re.compile(
    r"(apkverifier|appverifier|installverifier|securityguard|tvsecurity|guardprovider|packageverifier)",
    re.IGNORECASE
)

DEFAULT_BLOATWARE = [
    "com.google.android.tungsten.setupwraith",
    "com.google.android.apps.tv.launcherx",
    "com.google.android.tvlauncher",
    "com.google.android.tvrecommendations",
    "com.google.android.leanbacklauncher",
    "com.google.android.leanbacklauncher.recommendations",
    "com.google.android.videos",
    "com.google.android.music",
    "com.google.android.youtube.tvmusic",
    "com.google.android.play.games",
    "com.google.android.feedback",
    "com.google.android.partnersetup",
    "com.google.android.syncadapters.calendar",
    "com.google.android.syncadapters.contacts",
    "com.android.dreams.basic",
    "com.android.printspooler",
    "com.android.bips",
    "com.amazon.amazonvideo.livingroom",
    "com.netflix.ninja",
    "com.disney.disneyplus",
    "tv.pluto.android",
    "com.tubitv",
    "com.apple.atve.androidtv.appletv",
    "com.sony.dtv.osat.music",
    "com.sony.dtv.youview",
    "com.sony.dtv.braviapcore",
    "com.sony.dtv.b2b.hotelmode",
    "com.sony.dtv.sonytvplayer",
    "com.sony.dtv.tvx",
    "com.sony.dtv.livingdecor",
    "com.sony.dtv.promotions",
    "com.sony.dtv.InteractiveApplicationManager",
    "com.tcl.partnercustomizer",
    "com.tcl.messagebox",
    "com.tcl.cyberui",
    "com.tcl.bi",
    "com.hisense.tv.partnercustomizer",
    "com.mitv.tvhome",
    "com.xiaomi.mitv.DSA",
    "com.xiaomi.mitv.upgrade",
    "com.xiaomi.mitv.shop",
    "org.droidtv.nettv.market"
]

CORE_WHITELIST = {
    "android", "com.android.systemui", "com.android.settings",
    "com.android.providers.settings", "com.google.android.gms",
    "com.google.android.gsf", "com.android.vending",
    "com.android.packageinstaller", "com.google.android.packageinstaller",
    "com.android.inputmethod.latin", "com.google.android.inputmethod.latin",
    "com.google.android.katniss"
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
        self.title("CleanYourTV Pro — 雙桌面引擎版 (Aerial TV + CleanYourTV)")
        self.geometry("1040x680")
        self.minsize(960, 640)
        self.configure(fg_color="#1E1E1E")

        self.cfg = load_config()
        self.device_id = None
        self.custom_apk_path = ""

        self._build_layout()
        self.log(f"系統就緒。已內嵌雙桌面引擎：Aerial TV ({AERIAL_LAUNCHER_PKG}) & CleanYourTV ({CLEAN_LAUNCHER_PKG})")
        threading.Thread(target=lambda: run_adb(["start-server"]), daemon=True).start()

    # -------------------- UI 佈局建構 --------------------
    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=235, corner_radius=0, fg_color="#252526")
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

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
            self.sidebar, text="Aerial TV / Google TV 雙引擎",
            font=ctk.CTkFont(size=12), text_color="#8E8E93"
        ).pack(anchor="w", padx=20, pady=(0, 18))

        self.nav_buttons = {}
        nav_items = [
            ("connect", "📡  設備連線與配對"),
            ("clean",   "🍎  選擇桌面與系統精簡"),
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

        log_card = ctk.CTkFrame(self.right_container, corner_radius=12, fg_color="#141414", height=180)
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

    # -------------------- 頁面 2：手動選擇桌面 (Aerial TV / CleanYourTV) + 系統精簡 --------------------
    def _create_clean_page(self):
        frame = ctk.CTkFrame(self.pages_frame, fg_color="transparent")
        frame.grid_columnconfigure((0, 1), weight=1)
        frame.grid_rowconfigure(0, weight=1)

        left_card = ctk.CTkFrame(frame, corner_radius=14, fg_color="#2C2C2E")
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=4)

        ctk.CTkLabel(left_card, text="🍎 步驟 1：選擇要安裝的 tvOS 風格桌面", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(14, 4))

        self.launcher_choice_seg = ctk.CTkSegmentedButton(
            left_card,
            values=["Aerial TV (國產電視首選)", "CleanYourTV (原生極簡)", "自訂本地 APK"],
            command=self._on_launcher_choice_changed
        )
        self.launcher_choice_seg.pack(fill="x", padx=16, pady=6)
        self.launcher_choice_seg.set("Aerial TV (國產電視首選)")

        self.launcher_desc_lbl = ctk.CTkLabel(
            left_card,
            text="🌟 pengchujin/aerial-tv：專為小米/TCL/海信等國產電視設計，\n帶必應每日桌布、Apple 航拍屏保、信號源控制中心與開機自動接管守護。",
            font=ctk.CTkFont(size=11), text_color="#30D158", justify="left"
        )
        self.launcher_desc_lbl.pack(anchor="w", padx=16, pady=(2, 8))

        # 單獨安裝桌面按鈕 (不禁用系統應用，適合喜歡 Aerial 溫和接管模式的用戶)
        ctk.CTkButton(
            left_card, text="📥 僅解鎖安裝所選桌面 + 授權開機自動接管 (不停用系統App)", height=36,
            fg_color="#30D158", text_color="#000000", hover_color="#28B84C", font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: threading.Thread(target=self.worker_install_selected_launcher_only, daemon=True).start()
        ).pack(fill="x", padx=16, pady=(2, 10))

        ctk.CTkLabel(left_card, text="🧹 步驟 2：深度精簡與強制替換原裝桌面", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(4, 4))
        ctk.CTkLabel(
            left_card,
            text="自動解除 TCL/海信/小米安裝攔截 ➔ 安裝上方所選桌面 ➔\n停用右側列出的肥大軟體 ➔ 強制停用 Google TV LauncherX / 原廠桌面。",
            font=ctk.CTkFont(size=11), text_color="#AEAEB2", justify="left"
        ).pack(anchor="w", padx=16, pady=(0, 8))

        ctk.CTkButton(
            left_card, text="✨ 一鍵全自動：解鎖 + 安裝所選桌面 + 停用右側肥大清單", height=40,
            fg_color="#0A84FF", font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: threading.Thread(target=self.worker_full_clean, daemon=True).start()
        ).pack(fill="x", padx=16, pady=(2, 8))

        sub_btn_row = ctk.CTkFrame(left_card, fg_color="transparent")
        sub_btn_row.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkButton(
            sub_btn_row, text="🔓 僅解除安裝攔截", height=32, fg_color="#FF9F0A", text_color="#000000", hover_color="#E08900",
            command=lambda: threading.Thread(target=self.worker_bypass_verification, daemon=True).start()
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(
            sub_btn_row, text="🎯 強制封鎖原裝 LauncherX", height=32, fg_color="#5E5CE6", hover_color="#4B49B8",
            command=lambda: threading.Thread(target=self.worker_force_takeover_launcher, daemon=True).start()
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))

        right_card = ctk.CTkFrame(frame, corner_radius=14, fg_color="#2C2C2E")
        right_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=4)
        right_card.grid_rowconfigure(1, weight=1)
        right_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right_card, text="📦 原方案預設禁用清單 (含 Android 14 launcherx)", font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))

        self.default_bloat_textbox = ctk.CTkTextbox(right_card, fg_color="#1C1C1E", text_color="#EBEBF5", font=ctk.CTkFont(family="Consolas", size=11))
        self.default_bloat_textbox.grid(row=1, column=0, sticky="nsew", padx=16, pady=(4, 14))
        self.default_bloat_textbox.insert("1.0", "\n".join(DEFAULT_BLOATWARE))

        return frame

    def _on_launcher_choice_changed(self, val):
        if "Aerial TV" in val:
            self.launcher_desc_lbl.configure(
                text="🌟 pengchujin/aerial-tv：專為小米/TCL/海信等國產電視設計，\n帶必應每日桌布、Apple 航拍屏保、信號源控制中心與開機自動接管守護。",
                text_color="#30D158"
            )
        elif "CleanYourTV" in val:
            self.launcher_desc_lbl.configure(
                text="🍎 Gathin23/cleanyourtv：專為海外版 Android TV / Google TV 設計，\n極簡純粹的 Apple TV 卡片網格佈局，體積極小。",
                text_color="#0A84FF"
            )
        else:
            path = filedialog.askopenfilename(title="選擇自訂 Launcher APK", filetypes=[("APK Files", "*.apk")])
            if path:
                self.custom_apk_path = path
                self.launcher_desc_lbl.configure(text=f"📂 已選擇自訂 APK:\n{os.path.basename(path)}", text_color="#FF9F0A")
            else:
                self.launcher_choice_seg.set("Aerial TV (國產電視首選)")
                self._on_launcher_choice_changed("Aerial TV (國產電視首選)")

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
        self.api_key_entry
