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

# GitHubが公式に提供するダウンロードURLを構築するための環境変数
GITHUB_RUN_ID = os.environ.get('GITHUB_RUN_ID')
GITHUB_REPOSITORY = os.environ.get('GITHUB_REPOSITORY')

if not DOWNLOAD_URL:
    print("❌ GASからのURLが引き渡されていません。")
    sys.exit(1)

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
    
    print("⏳ ダウンロード開始を待機（15秒）...")
    time.sleep(15)
    
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
        
        # 💡 動画ファイルを直接保存用フォルダ（/content/output）に隔離
        output_dir = Path("./output")
        output_dir.mkdir(exist_ok=True)
        
        print("🔓 ZIPファイルを解凍中...")
        with zipfile.ZipFile(target_zip, 'r') as zip_ref:
            for file_info in zip_ref.infolist():
                filename = os.path.basename(file_info.filename)
                if not filename:
                    continue
                dest_name = f"{folder_name}_{filename}"
                with zip_ref.open(file_info) as source, open(output_dir / dest_name, "wb") as target:
                    target.write(source.read())
                    
        # 💡 GitHub公式のダウンロードリンクを生成
        download_link = f"https://nightly.link/{GITHUB_REPOSITORY}/actions/runs/{GITHUB_RUN_ID}/videos.zip"
        
        if GAS_WEBHOOK_URL:
            payload = {
                "folder_name": folder_name,
                "download_link": download_link
            }
            requests.post(GAS_WEBHOOK_URL, json=payload)
            print(f"🌟 GASへの公式ダウンロードリンク送信完了: {download_link}")
                
        print("✨ main.py の処理が正常に終了しました。")

except Exception as e:
    print(f"❌ エラー発生: {e}")
finally:
    driver.quit()
