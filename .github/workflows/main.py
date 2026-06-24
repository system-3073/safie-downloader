import os
import sys
import time
import zipfile
import json
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# 環境変数の読み込み
SAFIE_ID = os.environ.get('SAFIE_ID')
SAFIE_PW = os.environ.get('SAFIE_PW')
BASE_FOLDER_ID = os.environ.get('DRIVE_FOLDER_ID')
DOWNLOAD_URL = os.environ.get('DOWNLOAD_URL')
G_CREDENTIALS = os.environ.get('G_CREDENTIALS')

if not DOWNLOAD_URL:
    print("❌ GASからのURLが引き渡されていません。終了します。")
    sys.exit(1)

# Google Drive APIの認証設定
creds_dict = json.loads(G_CREDENTIALS)
creds = Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/drive'])
drive_service = build('drive', 'v3', credentials=creds)

# Chromeのセットアップ
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
    print(f"🔗 URLへアクセスします: {DOWNLOAD_URL}")
    driver.get(DOWNLOAD_URL)
    wait = WebDriverWait(driver, 15)
    
    print("⌨️ ログイン情報を入力中...")
    id_xpath = "//sf-login-page//sf-login//form/div[2]/div[2]//input"
    pw_xpath = "//sf-login-page//sf-login//form/div[2]/div[4]//input"
    
    wait.until(EC.element_to_be_clickable((By.XPATH, id_xpath))).send_keys(SAFIE_ID)
    driver.find_element(By.XPATH, pw_xpath).send_keys(SAFIE_PW)
    
    print("🔘 ログインクリック...")
    login_btn = "//sf-login-page//sf-login//form/div[2]/div[6]//sf-button-v1/div"
    driver.execute_script("arguments[0].click();", wait.until(EC.element_to_be_clickable((By.XPATH, login_btn))))
    
    print("⏳ ダウンロード開始を待機（15秒）...")
    time.sleep(15)
    
    print("⏳ ダウンロード完了を自動監視中...")
    timeout = 0
    success = False
    while timeout < 300:
        crdownloads = list(download_dir.glob("*.crdownload"))
        zip_files = list(download_dir.glob("*.zip"))
        if not crdownloads and zip_files:
            print("✅ ダウンロード完了！")
            success = True
            break
        time.sleep(3)
        timeout += 3

    if success:
        target_zip = list(download_dir.glob("*.zip"))[0]
        folder_name = target_zip.stem
        local_extract_dir = Path("./extracted") / folder_name
        local_extract_dir.mkdir(parents=True, exist_ok=True)
        
        print("🔓 解凍中...")
        with zipfile.ZipFile(target_zip, 'r') as zip_ref:
            zip_ref.extractall(local_extract_dir)
            
        print("🚀 Google Driveへ転送中...")
        for f in local_extract_dir.glob("*"):
            if f.is_file():
                dest_name = f"{folder_name}_{f.name}"
                print(f"  ➔ アップロード中: {dest_name}")
                file_metadata = {'name': dest_name, 'parents': [BASE_FOLDER_ID]}
                media = MediaFileUpload(str(f), mimetype='video/mp4', resumable=True)
                drive_service.files().create(body=file_metadata, media_body=media).execute()
        print("✨ すべての処理が大成功で完了しました！")

except Exception as e:
    print(f"❌ エラー発生: {e}")
finally:
    driver.quit()
