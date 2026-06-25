import os
import sys
import time
import zipfile
import requests
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

SAFIE_ID = os.environ.get('SAFIE_ID')
SAFIE_PW = os.environ.get('SAFIE_PW')
DOWNLOAD_URL = os.environ.get('DOWNLOAD_URL')
GAS_WEBHOOK_URL = os.environ.get('GAS_WEBHOOK_URL')

if not DOWNLOAD_URL:
    print("❌ GASからのURLが引き渡されていません。")
    sys.exit(1)

options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--window-size=1920,1080')
options.add_argument('--disable-gpu')

download_dir = Path("./downloads")
download_dir.mkdir(exist_ok=True)

prefs = {
    "download.default_directory": str(download_dir.resolve()),
    "download.prompt_for_download": False,
    "safebrowsing.enabled": True
}
options.add_experimental_option("prefs", prefs)
driver = webdriver.Chrome(options=options)

try:
    print(f"🔗 SafieダウンロードURLへアクセスします...")
    driver.get(DOWNLOAD_URL)
    wait = WebDriverWait(driver, 15)
    
    print("⌨️ ログイン情報を入力中...")
    id_xpath = "//sf-login-page//sf-login//form/div[2]/div[2]//input"
    pw_xpath = "//sf-login-page//sf-login//form/div[2]/div[4]//input"
    
    wait.until(EC.element_to_be_clickable((By.XPATH, id_xpath))).send_keys(SAFIE_ID)
    driver.find_element(By.XPATH, pw_xpath).send_keys(SAFIE_PW)
    
    print("🔘 ログインボタンをクリック...")
    login_btn = "//sf-login-page//sf-login//form/div[2]/div[6]//sf-button-v1/div"
    driver.execute_script("arguments[0].click();", wait.until(EC.element_to_be_clickable((By.XPATH, login_btn))))
    
    print("⏳ ダウンロード完了を自動監視中...")
    timeout = 0
    success = False
    while timeout < 300:
        crdownloads = list(download_dir.glob("*.crdownload"))
        zip_files = list(download_dir.glob("*.zip"))
        if not crdownloads and zip_files:
            print("✅ サイトからのダウンロードが完了しました！")
            success = True
            break
        time.sleep(3)
        timeout += 3

    if success:
        target_zip = list(download_dir.glob("*.zip"))[0]
        folder_name = target_zip.stem
        local_extract_dir = Path("./extracted") / folder_name
        local_extract_dir.mkdir(parents=True, exist_ok=True)
        
        print("🔓 ZIPファイルを解凍中...")
        with zipfile.ZipFile(target_zip, 'r') as zip_ref:
            zip_ref.extractall(local_extract_dir)
            
        print("🚀 GASへ動画データをダイレクト転送中...")
        for f in local_extract_dir.glob("*"):
            if f.is_file() and f.suffix == '.mp4':
                dest_name = f"{folder_name}_{f.name}"
                print(f"  ➔ 送信中: {dest_name}")
                
                # 💡 動画ファイルをバイナリデータとして直接GASにポストします
                with open(f, 'rb') as file_data:
                    # カスタムヘッダーでファイル名とフォルダ名を伝達
                    headers = {
                        "X-Folder-Name": folder_name.encode('utf-8').decode('latin-1'),
                        "X-File-Name": dest_name.encode('utf-8').decode('latin-1')
                    }
                    res = requests.post(GAS_WEBHOOK_URL, data=file_data, headers=headers)
                    print(f"    🌟 送信結果: {res.status_code}")
                
        print("✨ すべての動画のダイレクト転送が完了しました！")

except Exception as e:
    print(f"❌ エラー発生: {e}")
finally:
    driver.quit()
