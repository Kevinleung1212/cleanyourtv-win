import os
import sys
import subprocess
import time

def get_resource_path(relative_path):
    """獲取資源絕對路徑，相容開發環境與 PyInstaller --onefile 封裝環境"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

ADB_BIN = get_resource_path(os.path.join("platform-tools", "adb.exe"))
LAUNCHER_APK = get_resource_path(os.path.join("assets", "launcher.apk"))

# Google TV / Android TV 常見預裝軟體與預設桌面套件清單
BLOATWARE_PACKAGES = [
    # 預設桌面與推薦服務 (停用後第三方桌面將自動接管 Home 鍵)
    "com.google.android.tvlauncher",
    "com.google.android.tungsten.setupwraith",
    "com.google.android.tvrecommendations",
    # 常見廠商與系統內建垃圾應用
    "com.google.android.videos",               # Google TV Play Movies
    "com.google.android.youtube.tv",           # 原廠 YouTube (可依需求移除)
    "com.google.android.youtube.tvmusic",      # YouTube Music
    "com.netflix.ninja",                       # 預裝 Netflix (可依需求移除)
    "com.amazon.amazonvideo.livingroom",       # Prime Video
    "com.sony.dtv.osat.music",
    "com.sony.dtv.youview",
    "com.tcl.partnercustomizer",
    "com.hisense.tv.partnercustomizer"
]

def run_adb(args):
    """執行內嵌的 ADB 指令並回傳結果"""
    cmd = [ADB_BIN] + args
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore"
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()

def connect_tv(ip_address):
    print(f"[*] 正在啟動內建 ADB 服務並連接至 {ip_address}:5555 ...")
    run_adb(["start-server"])
    code, out, err = run_adb(["connect", f"{ip_address}:5555"])
    
    if "connected to" in out.lower():
        print("[+] 連接成功！請留意電視畫面，若跳出「允許 USB 偵錯」提示，請勾選永遠允許並點擊確定。")
        time.sleep(3)
        # 驗證設備授權狀態
        _, dev_out, _ = run_adb(["devices"])
        if f"{ip_address}:5555\tdevice" in dev_out:
            return True
        elif "unauthorized" in dev_out:
            input("[!] 設備尚未授權。請在電視上點擊「允許」後，按 Enter 鍵繼續...")
            _, dev_out, _ = run_adb(["devices"])
            return f"{ip_address}:5555\tdevice" in dev_out
    print(f"[-] 連接失敗: {out} {err}")
    return False

def install_custom_launcher():
    """安裝 Apple TV 風格桌面（如 Projectivy Launcher）"""
    if not os.path.exists(LAUNCHER_APK):
        print(f"[-] 找不到桌面安裝檔: {LAUNCHER_APK}，跳過安裝步驟。")
        return False
    
    print("[*] 正在安裝替換桌面 (Launcher APK)...")
    code, out, err = run_adb(["install", "-r", LAUNCHER_APK])
    if code == 0 and "Success" in out:
        print("[+] 替換桌面安裝成功！")
        # 賦予 Projectivy Launcher 無障礙權限以支援完整攔截 (選配，視桌面套件名稱而定)
        run_adb(["shell", "settings", "put", "secure", "enabled_accessibility_services", 
                 "com.spocky.projengmenu/com.spocky.projengmenu.services.ProjectivyAccessibilityService"])
        return True
    else:
        print(f"[-] 桌面安裝失敗 (為保護系統，將中止停用原廠桌面): {out} {err}")
        return False

def debloat_and_replace_home(launcher_installed):
    """批量停用系統應用與原廠桌面"""
    print("[*] 開始執行應用精簡與桌面替換...")
    for pkg in BLOATWARE_PACKAGES:
        # 安全機制：若第三方桌面未成功安裝，禁止停用原廠桌面以免黑屏
        if not launcher_installed and pkg in ["com.google.android.tvlauncher", "com.google.android.tungsten.setupwraith"]:
            print(f"[!] 跳過停用原廠桌面 {pkg} (因第三方桌面未就緒)")
            continue
            
        code, out, err = run_adb(["shell", "pm", "disable-user", "--user", "0", pkg])
        if "disabled-user" in out:
            print(f"  [√] 已停用: {pkg}")
        else:
            print(f"  [-] 略過 (系統未安裝或已處理): {pkg}")

def main():
    print("=" * 60)
    print(" CleanYourTV - Windows 獨立運行版 (Android/Google TV 淨化工具)")
    print("=" * 60)
    print("前置條件：請確認已在電視開啟「開發者選項」->「網路偵錯 / 無線偵錯」\n")
    
    tv_ip = input("請輸入電視的區域網路 IP 位址 (例如 192.168.1.100): ").strip()
    if not tv_ip:
        print("[-] IP 位址不可為空。")
        sys.exit(1)

    if connect_tv(tv_ip):
        # 步驟 1: 先安裝新桌面（確保系統存在可用 Launcher）
        launcher_ok = install_custom_launcher()
        
        # 步驟 2: 停用預裝垃圾軟體與原廠 Google TV 桌面
        debloat_and_replace_home(launcher_ok)
        
        # 步驟 3: 觸發 Home 鍵事件，立即切換至新桌面
        print("[*] 正在重新載入桌面環境...")
        run_adb(["shell", "input", "keyevent", "KEYCODE_HOME"])
        run_adb(["disconnect"])
        print("\n[+] 所有操作已完成！電視現已切換至新桌面。")
    else:
        print("\n[-] 無法與電視建立 ADB 連線，請檢查 IP 與電視偵錯開關。")

    input("\n按 Enter 鍵退出程式...")

if __name__ == "__main__":
    main()
