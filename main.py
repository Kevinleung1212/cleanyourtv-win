import os
import sys
import re
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
BASE_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
CONFIG_FILE = os.path.join(BASE_DIR, "ai_config.json")

# 預設安全停用名單
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

# 絕對不可停用的核心系統保護白名單
CORE_WHITELIST = {
    "android", "com.android.systemui", "com.android.settings",
    "com.android.providers.settings", "com.google.android.gms",
    "com.google.android.gsf", "com.android.vending",
    "com.spocky.projengmenu"
}

def run_adb(args, timeout=25):
    cmd = [ADB_BIN] + args
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="ignore", timeout=timeout
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"

def copy_to_clipboard(text):
    process = subprocess.Popen('clip', stdin=subprocess.PIPE, shell=True)
    process.communicate(input=text.encode('utf-16-le'))

def load_json_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_json_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

# ==================== Android 11~14 無線調試與智能連線模組 ====================

def scan_mdns_devices():
    """利用 ADB mDNS 自動搜尋區網內開啟無線調試的 Android 11~14 設備與隨機埠"""
    _, out, _ = run_adb(["mdns", "services"])
    connect_targets = []
    pair_targets = []
    for line in out.splitlines():
        # 匹配 IP:Port 格式
        match = re.search(r'(\d+\.\d+\.\d+\.\d+:\d+)', line)
        if match:
            addr = match.group(1)
            if "_adb-tls-connect._tcp" in line and addr not in connect_targets:
                connect_targets.append(addr)
            elif "_adb-tls-pairing._tcp" in line and addr not in pair_targets:
                pair_targets.append(addr)
    return connect_targets, pair_targets

def check_device_online(target_addr):
    """確認指定 IP:Port 是否已處於 device 授權連線狀態"""
    _, dev_out, _ = run_adb(["devices"])
    for line in dev_out.splitlines():
        if target_addr in line and "\tdevice" in line:
            return "online"
        if target_addr in line and "unauthorized" in line:
            return "unauthorized"
    return "offline"

def lock_to_port_5555(current_addr):
    """連上隨機高位埠後，可選自動開啟固定 5555 埠，免除後續每次查看隨機埠"""
    ip = current_addr.split(":")[0]
    port = current_addr.split(":")[1] if ":" in current_addr else "5555"
    if port != "5555":
        print(f"[*] 檢測到當前使用動態隨機埠 ({port})，正在為電視開啟固定 5555 埠以便日後免查埠直連...")
        code, out, _ = run_adb(["-s", current_addr, "tcpip", "5555"])
        if code == 0 or "restarting in TCP mode" in out:
            time.sleep(2)
            run_adb(["connect", f"{ip}:5555"])
            if check_device_online(f"{ip}:5555") == "online":
                print(f"[+] 已成功將連線固化切換至 {ip}:5555 (電視重啟前均固定有效)")
                return f"{ip}:5555"
    return current_addr

def pair_wireless_adb(default_ip=""):
    """執行 Android 11~14 配對碼 (Pairing Code) 驗證流程"""
    print("\n" + "=" * 60)
    print(" [Android 11 ~ 14 無線調試配對引導]")
    print(" 1. 請在電視進入「開發者選項」->「無線調試 (Wireless Debugging)」")
    print(" 2. 點擊「使用配對碼配對設備 (Pair device with pairing code)」")
    print(" 3. 畫面會顯示【6位數配對碼】與【IP位址和配對埠 (注意：配對埠與外層連接埠不同)】")
    print("=" * 60)

    # 嘗試透過 mDNS 自動抓取正在等待配對的電視
    _, pair_targets = scan_mdns_devices()
    if pair_targets:
        print(f"[+] 自動掃描到正在等待配對的設備: {', '.join(pair_targets)}")
        default_pair_addr = pair_targets[0]
    else:
        default_pair_addr = ""

    if default_pair_addr:
        pair_addr = input(f"請輸入配對 IP:Port (直接按 Enter 使用 {default_pair_addr}): ").strip() or default_pair_addr
    elif default_ip:
        pair_port = input(f"電視 IP 為 {default_ip}，請輸入畫面上的【配對埠號】(例如 37891，或輸入完整 IP:Port): ").strip()
        pair_addr = pair_port if ":" in pair_port else f"{default_ip}:{pair_port}"
    else:
        pair_addr = input("請輸入電視畫面上的【配對 IP:Port】(例如 192.168.1.100:37891): ").strip()

    pair_code = input("請輸入電視畫面上的【6 位數配對碼】(例如 123456): ").strip()
    if not pair_addr or not pair_code:
        print("[-] 配對資訊不完整，取消配對。")
        return False

    print(f"[*] 正在與 {pair_addr} 進行配對驗證...")
    code, out, err = run_adb(["pair", pair_addr, pair_code])
    combined = f"{out} {err}".lower()
    if "successfully paired" in combined:
        print("[+] 配對成功！電腦已獲得電視信任。")
        return True
    else:
        print(f"[-] 配對失敗: {out} {err}")
        return False

def smart_connect_tv():
    """支援舊版 5555、新版隨機埠、mDNS 自動探索與配對碼的四合一連線器"""
    print("[*] 正在初始化內建 ADB 服務並掃描區域網路設備...")
    run_adb(["start-server"])
    
    cfg = load_json_config()
    last_ip = cfg.get("last_tv_ip", "")

    # 1. 嘗試透過 mDNS 掃描已開啟無線調試的設備
    connect_targets, _ = scan_mdns_devices()

    while True:
        print("\n" + "-" * 60)
        print(" 請選擇電視連接方式 (支援 Android 9~14)：")
        if connect_targets:
            print(f" [A] 一鍵自動連接掃描到的無線調試設備: {connect_targets[0]}")
        print(" [1] 直接輸入 IP 或 IP:隨機埠 (如 192.168.1.100 或 192.168.1.100:41235)")
        print(" [2] 首次配對 Android 11~14 無線調試 (輸入 6 位數配對碼)")
        print(" [0] 退出程式")
        print("-" * 60)

        default_opt = "A" if connect_targets else "1"
        opt = input(f"請選擇 (預設 {default_opt}): ").strip().upper() or default_opt

        if opt == "0":
            return None

        if opt == "2":
            pair_wireless_adb(last_ip)
            # 配對完成後重新掃描 mDNS 取得連接埠
            connect_targets, _ = scan_mdns_devices()
            continue

        if opt == "A" and connect_targets:
            target = connect_targets[0]
        else:
            prompt_hint = f" (上次使用 {last_ip}，直接按 Enter 可沿用)" if last_ip else ""
            user_in = input(f"請輸入電視 IP 或 IP:Port{prompt_hint}: ").strip()
            if not user_in and last_ip:
                user_in = last_ip
            if not user_in:
                print("[-] 輸入不可為空。")
                continue

            # 若只輸入純 IP，先檢查 mDNS 是否有對應隨機埠，否則預設嘗試 :5555
            if ":" not in user_in:
                matched_mdns = [t for t in connect_targets if t.startswith(user_in + ":")]
                if matched_mdns:
                    print(f"[+] 自動匹配到 {user_in} 的無線調試隨機埠: {matched_mdns[0]}")
                    target = matched_mdns[0]
                else:
                    target = f"{user_in}:5555"
            else:
                target = user_in

        # 儲存純 IP 供下次記憶使用
        pure_ip = target.split(":")[0]
        cfg["last_tv_ip"] = pure_ip
        save_json_config(cfg)

        print(f"[*] 正在連接至 {target} ...")
        _, out, err = run_adb(["connect", target])
        combined = f"{out} {err}".lower()

        if "connected to" in combined:
            time.sleep(1.5)
            status = check_device_online(target)
            if status == "unauthorized":
                input("[!] 請留意電視畫面，勾選「永遠允許來自此電腦的調試」並點擊確定後，按 Enter 繼續...")
                status = check_device_online(target)

            if status == "online":
                print(f"[+] 成功連接至電視 ({target})！")
                # 自動將隨機埠轉為固定 5555 埠（方便後續使用）
                final_target = lock_to_port_5555(target)
                return final_target

        # 若連接 5555 或隨機埠被拒絕，引導進入 Android 11~14 隨機埠與配對流程
        print(f"[-] 無法直接連上 {target} (原因: {out} {err})")
        print("\n[提示] 若您的電視為 Android 11 / 12 / 13 / 14：")
        print("  • 每次開啟「無線調試」時，連接埠號都是隨機生成的（例如 37000~49999），並非固定 5555。")
        print("  • 若從未與此電腦配對過，必須先執行【配對碼配對】。")
        
        sub = input("\n請選擇下一步：[1] 輸入電視上的隨機連接埠  [2] 先進行 6 位數配對碼配對  [N] 返回重試: ").strip()
        if sub == "2":
            if pair_wireless_adb(pure_ip):
                connect_targets, _ = scan_mdns_devices()
                matched = [t for t in connect_targets if t.startswith(pure_ip + ":")]
                if matched:
                    conn_port_addr = matched[0]
                else:
                    c_port = input(f"配對完成！請輸入「無線調試」主頁面上顯示的【連接埠號】(IP {pure_ip} 後面的數字): ").strip()
                    conn_port_addr = c_port if ":" in c_port else f"{pure_ip}:{c_port}"
                
                print(f"[*] 正在連接至 {conn_port_addr} ...")
                run_adb(["connect", conn_port_addr])
                time.sleep(1)
                if check_device_online(conn_port_addr) == "online":
                    print(f"[+] 成功連接至電視 ({conn_port_addr})！")
                    return lock_to_port_5555(conn_port_addr)
        elif sub == "1":
            c_port = input(f"請輸入 {pure_ip} 目前在「無線調試」主頁面顯示的【隨機埠號】(例如 41235): ").strip()
            if c_port:
                conn_port_addr = c_port if ":" in c_port else f"{pure_ip}:{c_port}"
                run_adb(["connect", conn_port_addr])
                time.sleep(1)
                if check_device_online(conn_port_addr) == "online":
                    print(f"[+] 成功連接至電視 ({conn_port_addr})！")
                    return lock_to_port_5555(conn_port_addr)

# ==================== AI 登入與配置管理 ====================

def load_or_setup_ai_config():
    cfg = load_json_config()
    if cfg.get("mode"):
        print(f"\n[已載入 AI 配置] 平台: {cfg.get('platform_name')} | 模式: {cfg.get('mode')}")
        reconfig = input("是否重新設定豆包/WorkBuddy登入位置？(y/N，預設 N): ").strip().lower()
        if reconfig != 'y':
            return cfg

    print("\n" + "=" * 55)
    print(" 設定 豆包 (Doubao) / WorkBuddy 登入與分析方式")
    print("=" * 55)
    print(" 1. [網頁登入連動模式] 免 API Key，直接打開瀏覽器登入豆包/WorkBuddy 網頁分析")
    print(" 2. [API Key 直連模式] 透過火山方舟(豆包) 或 WorkBuddy OpenAI 兼容接口全自動分析")
    mode_choice = input("\n請選擇模式 (1 或 2，預設 1): ").strip()

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

    save_json_config(cfg)
    print(f"[+] 設定已保存至 {CONFIG_FILE}")
    return cfg

# ==================== 電視套件擷取與 AI 分析 ====================

def get_tv_installed_packages(device_id):
    print("[*] 正在讀取電視上的已安裝套件清單...")
    code, out, _ = run_adb(["-s", device_id, "shell", "pm", "list", "packages", "-e"])
    if code != 0 or not out:
        return []
    packages = []
    for line in out.splitlines():
        pkg = line.replace("package:", "").strip()
        if pkg and pkg not in CORE_WHITELIST:
            packages.append(pkg)
    return sorted(packages)

def build_analysis_prompt(packages):
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

def parse_ai_safe_list(text):
    if "[SAFE_DISABLE_START]" in text and "[SAFE_DISABLE_END]" in text:
        block = text.split("[SAFE_DISABLE_START]")[1].split("[SAFE_DISABLE_END]")[0]
        return [line.strip() for line in block.splitlines() if line.strip() and "." in line.strip()]
    return []

def analyze_via_api(cfg, packages):
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

# ==================== 桌面替換與停用/還原執行 ====================

def install_custom_launcher(device_id):
    if not os.path.exists(LAUNCHER_APK) or os.path.getsize(LAUNCHER_APK) < 1024:
        print("[-] 找不到有效的內嵌桌面 APK，跳過桌面安裝。")
        return False
    print("[*] 正在安裝替換桌面 (Projectivy Launcher)...")
    code, out, err = run_adb(["-s", device_id, "install", "-r", LAUNCHER_APK], timeout=90)
    if code == 0 and "Success" in out:
        print("[+] 替換桌面安裝成功！")
        run_adb(["-s", device_id, "shell", "settings", "put", "secure", "enabled_accessibility_services", 
                 "com.spocky.projengmenu/com.spocky.projengmenu.services.ProjectivyAccessibilityService"])
        return True
    print(f"[-] 桌面安裝失敗: {out} {err}")
    return False

def disable_packages(device_id, pkg_list, launcher_installed):
    print(f"\n[*] 準備執行停用程序（共 {len(pkg_list)} 個目標套件）...")
    for pkg in pkg_list:
        if pkg in CORE_WHITELIST:
            print(f"  [!] 攔截保護：跳過核心系統套件 {pkg}")
            continue
        if not launcher_installed and pkg in ["com.google.android.tvlauncher", "com.google.android.tungsten.setupwraith"]:
            print(f"  [!] 跳過原廠桌面 {pkg} (第三方桌面尚未就緒)")
            continue
        _, out, _ = run_adb(["-s", device_id, "shell", "pm", "disable-user", "--user", "0", pkg])
        if "disabled-user" in out:
            print(f"  [√] 已成功停用: {pkg}")
        else:
            print(f"  [-] 略過 (未安裝或無權限): {pkg}")

def restore_all_disabled(device_id):
    print("[*] 正在掃描所有已被停用的套件...")
    _, out, _ = run_adb(["-s", device_id, "shell", "pm", "list", "packages", "-d"])
    disabled_pkgs = [line.replace("package:", "").strip() for line in out.splitlines() if line.strip()]
    if not disabled_pkgs:
        print("[+] 目前沒有任何被停用的套件。")
        return
    for pkg in disabled_pkgs:
        run_adb(["-s", device_id, "shell", "pm", "enable", pkg])
        print(f"  [√] 已重新啟用: {pkg}")

def main():
    print("=" * 68)
    print(" CleanYourTV AI 增強版 (全面支援 Android 11~14 隨機埠與配對碼機制)")
    print("=" * 68)
    
    device_id = smart_connect_tv()
    if not device_id:
        input("\n已取消連線，按 Enter 鍵退出...")
        sys.exit(0)

    while True:
        print("\n" + "-" * 55)
        print(f" 當前連接電視: [{device_id}] | 請選擇操作模式：")
        print(" 1. [預設一鍵淨化] 安裝 Apple TV 風格桌面 + 停用基礎預裝軟體")
        print(" 2. [AI 智能深度分析] 登入 豆包 / WorkBuddy 分析電視所有 App 並選擇性停用")
        print(" 3. [一鍵救磚還原] 重新啟用所有被停用的系統與原廠桌面 App")
        print(" 4. [切換/重連設備] 重新配對或更換連接的電視 IP:Port")
        print(" 0. 斷開連線並退出")
        print("-" * 55)
        choice = input("請輸入選項編號 (0-4): ").strip()

        if choice == "1":
            launcher_ok = install_custom_launcher(device_id)
            disable_packages(device_id, DEFAULT_BLOATWARE, launcher_ok)
            run_adb(["-s", device_id, "shell", "input", "keyevent", "KEYCODE_HOME"])
            print("[+] 預設淨化與桌面替換完成！")

        elif choice == "2":
            cfg = load_or_setup_ai_config()
            pkgs = get_tv_installed_packages(device_id)
            if not pkgs:
                print("[-] 無法取得電視套件清單，請確認連線是否中斷。")
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
                    launcher_ok = install_custom_launcher(device_id)
                    disable_packages(device_id, ai_suggested, launcher_ok)
            else:
                print("[-] 未收到有效的停用清單，取消操作。")

        elif choice == "3":
            restore_all_disabled(device_id)

        elif choice == "4":
            new_dev = smart_connect_tv()
            if new_dev:
                device_id = new_dev

        elif choice == "0":
            run_adb(["disconnect"])
            break

if __name__ == "__main__":
    main()
