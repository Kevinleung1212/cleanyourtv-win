import os
import sys
import json
import time
import subprocess
import urllib.request
import urllib.error
import webbrowser

def get_resource_path(relative_path):
    """獲取內嵌資源絕對路徑，相容 PyInstaller --onefile"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

ADB_BIN = get_resource_path(os.path.join("platform-tools", "adb.exe"))
LAUNCHER_APK = get_resource_path(os.path.join("assets", "launcher.apk"))
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__)), "ai_config.json")

# 預設安全停用名單 (基礎名單)
DEFAULT_BLOATWARE = [
    "com.google.android.tvlauncher",
    "com.google.android.tungsten.setupwraith",
    "com.google.android.tvrecommendations",
    "com.google.android.videos",
    "com.google.android.youtube.tvmusic",
    "com.amazon.amazonvideo.livingroom",
    "com.sony.dtv.osat.music",
    "com.tcl.partnercustomizer",
    "com.hisense.tv.partnercustomizer"
]

# 絕對不可停用的核心系統名單 (防呆保護白名單)
CORE_WHITELIST = {
    "android", "com.android.systemui", "com.android.settings",
    "com.android.providers.settings", "com.google.android.gms",
    "com.google.android.gsf", "com.android.vending",
    "com.spocky.projengmenu" # Projectivy Launcher
}

def run_adb(args):
    cmd = [ADB_BIN] + args
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore")
    return result.returncode, result.stdout.strip(), result.stderr.strip()

def copy_to_clipboard(text):
    """使用 Windows 內建 clip 指令複製文字到剪貼簿"""
    process = subprocess.Popen('clip', stdin=subprocess.PIPE, shell=True)
    process.communicate(input=text.encode('utf-16-le'))

# ==================== AI 登入與配置管理 ====================

def load_or_setup_ai_config():
    """讀取或設定豆包 / WorkBuddy 登入與 API 資訊"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            print(f"\n[已載入配置] 平台: {cfg.get('platform_name')} | 模式: {cfg.get('mode')}")
            reconfig = input("是否重新設定豆包/WorkBuddy登入位置？(y/N，預設 N): ").strip().lower()
            if reconfig != 'y':
                return cfg
        except Exception:
            pass

    print("\n" + "=" * 55)
    print(" 設定 豆包 (Doubao) / WorkBuddy 登入與分析方式")
    print("=" * 55)
    print(" 1. [網頁登入連動模式] 免 API Key，直接打開瀏覽器登入豆包/WorkBuddy 網頁分析")
    print(" 2. [API Key 直連模式] 透過火山方舟(豆包) 或 WorkBuddy OpenAI 兼容接口全自動分析")
    mode_choice = input("\n請選擇模式 (1 或 2，預設 1): ").strip()

    cfg = {}
    if mode_choice == "2":
        cfg["mode"] = "api"
        print("\n--- API 端點預設選項 ---")
        print(" [A] 豆包 (字節跳動火山方舟): https://ark.cn-beijing.volces.com/api/v3/chat/completions")
        print(" [B] 自訂 WorkBuddy / OpenAI 兼容接口地址")
        p_choice = input("請選擇平台 (A/B，預設 A): ").strip().upper()
        if p_choice == "B":
            cfg["platform_name"] = "WorkBuddy / Custom API"
            cfg["api_url"] = input("請輸入完整 API URL (需以 /chat/completions 結尾): ").strip()
            cfg["model"] = input("請輸入模型名稱 (Model ID): ").strip()
        else:
            cfg["platform_name"] = "豆包 (火山方舟 API)"
            cfg["api_url"] = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
            cfg["model"] = input("請輸入豆包推理接入點 ID (如 ep-2026xxxx-xxxx 或 doubao-pro-32k): ").strip()
        
        cfg["api_key"] = input("請輸入 API Key (Bearer Token): ").strip()
    else:
        cfg["mode"] = "web"
        print("\n--- 網頁登入位置設定 ---")
        print(" [A] 豆包網頁版 (https://www.doubao.com/chat/)")
        print(" [B] WorkBuddy 網頁端 (自訂企業/個人登入網址)")
        w_choice = input("請選擇登入平台 (A/B，預設 A): ").strip().upper()
        if w_choice == "B":
            cfg["platform_name"] = "WorkBuddy Web"
            cfg["web_url"] = input("請輸入 WorkBuddy 網頁登入網址 (如 https://...): ").strip()
        else:
            cfg["platform_name"] = "豆包網頁版"
            cfg["web_url"] = "https://www.doubao.com/chat/"

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print(f"[+] 設定已保存至 {CONFIG_FILE}")
    return cfg

# ==================== 電視套件擷取與 AI 分析 ====================

def get_tv_installed_packages():
    """從電視擷取目前已啟用的系統與第三方套件清單"""
    print("[*] 正在讀取電視上的已安裝套件清單...")
    code, out, _ = run_adb(["shell", "pm", "list", "packages", "-e"])
    if code != 0 or not out:
        return []
    packages = []
    for line in out.splitlines():
        pkg = line.replace("package:", "").strip()
        if pkg and pkg not in CORE_WHITELIST:
            packages.append(pkg)
    return sorted(packages)

def build_analysis_prompt(packages):
    """建構發送給豆包 / WorkBuddy 的精確分析提示詞"""
    pkg_text = "\n".join(packages)
    return (
        "你是一位資深 Android TV / Google TV 系統精簡專家。以下是從我電視上導出的所有已啟用套件名稱（Package Name）。\n"
        "請分析哪些屬於『預裝垃圾軟體、廣告推送、廠商定制推播、非必要影音應用』且可以安全停用（不會導致系統崩潰、藍牙遙控器失靈、Wi-Fi斷線或輸入法消失）。\n\n"
        "請嚴格按照以下兩個部分輸出：\n"
        "第一部分：用表格列出建議停用的包名、應用名稱、停用影響說明。\n"
        "第二部分：在回答的最末尾，將所有『100%安全可停用』的包名用純文字每行一個列在 [SAFE_DISABLE_START] 與 [SAFE_DISABLE_END] 標籤之間，格式如下：\n"
        "[SAFE_DISABLE_START]\n"
        "com.example.bloatware1\n"
        "com.example.bloatware2\n"
        "[SAFE_DISABLE_END]\n\n"
        f"待分析電視套件清單（共 {len(packages)} 個）：\n{pkg_text}"
    )

def analyze_via_api(cfg, packages):
    """透過豆包 / WorkBuddy API 自動分析"""
    print(f"[*] 正在將 {len(packages)} 個套件發送至 {cfg['platform_name']} 進行安全評估...")
    prompt = build_analysis_prompt(packages)
    
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": "你是嚴謹的 Android TV 系統固件工程師，只給出準確、安全的精簡建議。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1
    }
    
    req = urllib.request.Request(
        cfg["api_url"],
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}"
        },
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            reply = res_data["choices"][0]["message"]["content"]
            print("\n================ AI 分析報告 ================\n")
            print(reply)
            print("\n=============================================\n")
            return parse_ai_safe_list(reply)
    except Exception as e:
        print(f"[-] API 呼叫失敗: {e}")
        return []

def analyze_via_web(cfg, packages):
    """透過網頁端登入豆包 / WorkBuddy 進行分析"""
    prompt = build_analysis_prompt(packages)
    copy_to_clipboard(prompt)
    print("\n" + "=" * 60)
    print(f"[+] 已將電視的 {len(packages)} 個套件與分析指令複製到系統剪貼簿！")
    print(f"[*] 正在為您打開 {cfg['platform_name']} 登入頁面: {cfg['web_url']}")
    print("=" * 60)
    webbrowser.open(cfg["web_url"])
    
    print("\n請按照以下 3 步操作：")
    print(" 1. 在打開的瀏覽器中完成登入（若已登入則直接進入對話框）。")
    print(" 2. 在對話框按 Ctrl + V 貼上並發送。")
    print(" 3. 將 AI 回覆最後面 [SAFE_DISABLE_START] 到 [SAFE_DISABLE_END] 之間的包名複製下來。")
    print("\n請在下方貼上 AI 建議停用的包名清單（每行一個，貼完後輸入 END 並按 Enter 結束）：")
    
    user_lines = []
    while True:
        line = input().strip()
        if line.upper() == "END":
            break
        if line and not line.startswith("["):
            user_lines.append(line)
    
    return [pkg for pkg in user_lines if pkg in packages]

def parse_ai_safe_list(text):
    """從 AI 回覆中提取 [SAFE_DISABLE_START] 區塊內的套件名"""
    if "[SAFE_DISABLE_START]" in text and "[SAFE_DISABLE_END]" in text:
        block = text.split("[SAFE_DISABLE_START]")[1].split("[SAFE_DISABLE_END]")[0]
        return [line.strip() for line in block.splitlines() if line.strip() and "." in line.strip()]
    return []

# ==================== 核心連接與停用執行 ====================

def connect_tv(ip_address):
    print(f"[*] 正在啟動內建 ADB 並連接至 {ip_address}:5555 ...")
    run_adb(["start-server"])
    _, out, err = run_adb(["connect", f"{ip_address}:5555"])
    if "connected to" in out.lower():
        time.sleep(2)
        _, dev_out, _ = run_adb(["devices"])
        if f"{ip_address}:5555\tdevice" in dev_out:
            return True
        elif "unauthorized" in dev_out:
            input("[!] 請在電視畫面上勾選「永遠允許」並點擊確定後，按 Enter 繼續...")
            _, dev_out, _ = run_adb(["devices"])
            return f"{ip_address}:5555\tdevice" in dev_out
    print(f"[-] 連接失敗: {out} {err}")
    return False

def install_custom_launcher():
    if not os.path.exists(LAUNCHER_APK):
        print("[-] 找不到內嵌桌面 APK，跳過桌面安裝。")
        return False
    print("[*] 正在安裝替換桌面 (Projectivy Launcher)...")
    code, out, err = run_adb(["install", "-r", LAUNCHER_APK])
    if code == 0 and "Success" in out:
        print("[+] 替換桌面安裝成功！")
        run_adb(["shell", "settings", "put", "secure", "enabled_accessibility_services", 
                 "com.spocky.projengmenu/com.spocky.projengmenu.services.ProjectivyAccessibilityService"])
        return True
    print(f"[-] 桌面安裝失敗: {out} {err}")
    return False

def disable_packages(pkg_list, launcher_installed):
    print(f"\n[*] 準備執行停用程序（共 {len(pkg_list)} 個目標套件）...")
    for pkg in pkg_list:
        if pkg in CORE_WHITELIST:
            print(f"  [!] 攔截保護：跳過核心系統套件 {pkg}")
            continue
        if not launcher_installed and pkg in ["com.google.android.tvlauncher", "com.google.android.tungsten.setupwraith"]:
            print(f"  [!] 跳過原廠桌面 {pkg} (第三方桌面尚未就緒)")
            continue
        _, out, _ = run_adb(["shell", "pm", "disable-user", "--user", "0", pkg])
        if "disabled-user" in out:
            print(f"  [√] 已成功停用: {pkg}")
        else:
            print(f"  [-] 略過 (未安裝或無權限): {pkg}")

def restore_all_disabled():
    """一鍵還原所有被停用的應用"""
    print("[*] 正在掃描所有已被停用的套件...")
    _, out, _ = run_adb(["shell", "pm", "list", "packages", "-d"])
    disabled_pkgs = [line.replace("package:", "").strip() for line in out.splitlines() if line.strip()]
    if not disabled_pkgs:
        print("[+] 目前沒有任何被停用的套件。")
        return
    for pkg in disabled_pkgs:
        run_adb(["shell", "pm", "enable", pkg])
        print(f"  [√] 已重新啟用: {pkg}")

def main():
    print("=" * 65)
    print(" CleanYourTV AI 增強版 (支援 豆包 / WorkBuddy 智能分析停用)")
    print("=" * 65)
    
    tv_ip = input("請輸入電視的區域網路 IP 位址 (例如 192.168.1.100): ").strip()
    if not tv_ip or not connect_tv(tv_ip):
        input("\n按 Enter 鍵退出...")
        sys.exit(1)

    while True:
        print("\n" + "-" * 50)
        print(" 請選擇操作模式：")
        print(" 1. [預設一鍵淨化] 安裝 Apple TV 風格桌面 + 停用基礎預裝軟體")
        print(" 2. [AI 智能深度分析] 登入 豆包 / WorkBuddy 分析電視所有 App 並選擇性停用")
        print(" 3. [一鍵救磚還原] 重新啟用所有被停用的系統與原廠桌面 App")
        print(" 0. 斷開連線並退出")
        print("-" * 50)
        choice = input("請輸入選項編號 (0-3): ").strip()

        if choice == "1":
            launcher_ok = install_custom_launcher()
            disable_packages(DEFAULT_BLOATWARE, launcher_ok)
            run_adb(["shell", "input", "keyevent", "KEYCODE_HOME"])
            print("[+] 預設淨化與桌面替換完成！")

        elif choice == "2":
            cfg = load_or_setup_ai_config()
            pkgs = get_tv_installed_packages()
            if not pkgs:
                print("[-] 無法取得電視套件清單。")
                continue
            
            if cfg.get("mode") == "api":
                ai_suggested = analyze_via_api(cfg, pkgs)
            else:
                ai_suggested = analyze_via_web(cfg, pkgs)

            if ai_suggested:
                print(f"\n[+] AI 共識別出 {len(ai_suggested)} 個可安全停用的套件：")
                for i, p in enumerate(ai_suggested, 1):
                    print(f"  {i}. {p}")
                confirm = input("\n是否立即停用上述 AI 建議的套件？(y/N): ").strip().lower()
                if confirm == 'y':
                    # 確保在停用原廠桌面前先檢查是否已安裝第三方桌面
                    launcher_ok = install_custom_launcher()
                    disable_packages(ai_suggested, launcher_ok)
            else:
                print("[-] 未收到有效的停用清單，取消操作。")

        elif choice == "3":
            restore_all_disabled()

        elif choice == "0":
            run_adb(["disconnect"])
            break

if __name__ == "__main__":
    main()
