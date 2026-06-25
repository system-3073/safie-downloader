import os
import sys
import re
import time
import imaplib
import email
import zipfile
import io
from pathlib import Path
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Google API 関連
import json
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

GMAIL_USER = os.environ.get('GMAIL_USER')
GMAIL_PASS = os.environ.get('GMAIL_PASS')
SAFIE_ID = os.environ.get('SAFIE_ID')
SAFIE_PW = os.environ.get('SAFIE_PW')
DRIVE_CREDENTIALS = os.environ.get('DRIVE_CREDENTIALS')

# 山下さんのGoogleドライブ保存先フォルダID
DRIVE_FOLDER_ID = "17lDpuOIqM7iLQPLm_1EVOHqBxEQ7195K"

# Googleドライブ接続の初期化
def get_drive_service():
    creds_json = json.loads(DRIVE_CREDENTIALS)
    creds = Credentials.from_authorized_user_info(creds_json)
    return build('drive', 'v3', credentials=creds)

def fetch_download_url():
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_PASS)
        mail.select("inbox")
        status, messages = mail.search(None, '(UNSEEN FROM "noreply@safie.jp")')
        if not messages[0]:
            mail.logout()
            return None
        mail_ids = messages[0].split()
        latest_id = mail_ids[-1]
        status, data = mail.fetch(latest_id, "(RFC822)")
        raw_email = data[0][1]
        msg = email.message_from_bytes(raw_email)
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() in ["text/html", "text/plain"]:
                    body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    if "download/media" in body: break
        else:
            body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
        url_match = re.search(r'https://next-cloudview\.safie\.link/download/media\?mediaid=[^\s"\'><]+', body)
        if url_match:
            download_url = url_match.group(0)
            mail.store(latest_id, '+FLAGS', '\\Seen')
            mail.logout()
            return download_url
        mail.logout()
        return None
    except Exception as e:
        print(f"❌ Gmail処理エラー: {e}")
        return None

def login_and_download(download_url):
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-gpu')
    download_dir = Path("./downloads")
    download_dir.mkdir(exist_ok=True)
    prefs = {"download.default_directory": str(download_dir.resolve()), "download.prompt_for_download": False}
    options.add_experimental_option("prefs", prefs)
    driver = webdriver.Chrome(options=options)
    is_success = False
    try:
        driver.get(download_url)
        wait = WebDriverWait(driver, 15)
        id_xpath = "//sf-login-page//sf-login//form/div[2]/div[2]//input"
        pw_xpath = "//sf-login-page//sf-login//form/div[2]/div[4]//input"
        wait.until(EC.element_to_be_clickable((By.XPATH, id_xpath))).send_keys(SAFIE_ID)
        driver.find_element(By.XPATH, pw_xpath).send_keys(SAFIE_PW)
        login_btn = "//sf-login-page//sf-login//form/div[2]/div[6]//sf-button-v1/div"
        driver.execute_script("arguments[0].click();", wait.until(EC.element_to_be_clickable((By.XPATH, login_btn))))
        time.sleep(15)
        timeout = 0
        while timeout < 300:
            crdownloads = list(download_dir.glob("*.crdownload"))
            zip_files = list(download_dir.glob("*.zip"))
            if not crdownloads and zip_files:
                is_success = True
                break
            time.sleep(3)
            timeout += 3
    except Exception as e:
        print(f"❌ ブラウザエラー: {e}")
    finally:
        driver.quit()
    return is_success

def upload_to_drive():
    download_dir = Path("./downloads")
    zip_files = list(download_dir.glob("*.zip"))
    if not zip_files: return
    target_zip = zip_files[0]
    folder_name = target_zip.stem
    
    drive_service = get_drive_service()
    
    # 💡 Googleドライブ上に動画名で新規フォルダを作成
    file_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [DRIVE_FOLDER_ID]
    }
    target_folder = drive_service.files().create(body=file_metadata, fields='id').execute()
    target_folder_id = target_folder.get('id')
    
    print(f"🔓 Googleドライブ直下にフォルダを作成しました: {folder_name}")
    
    # ZIPをメモリ上で解凍しながら、Googleドライブへ動画を直接ダイレクト転送！
    with zipfile.ZipFile(target_zip, 'r') as zip_ref:
        for file_info in zip_ref.infolist():
            filename = os.path.basename(file_info.filename)
            if not filename or filename.startswith('.') or '__MACOSX' in file_info.filename:
                continue
            
            print(f"🚀 ドライブへ直接アップロード中: {filename}")
            file_data = zip_ref.read(file_info.filename)
            media = MediaIoBaseUpload(io.BytesIO(file_data), mime_type='video/mp4', resumable=True)
            
            video_metadata = {
                'name': filename,
                'parents': [target_folder_id]
            }
            drive_service.files().create(body=video_metadata, media_body=media, fields='id').execute()
            
    print("✨ 【大成功】すべての動画がGoogleドライブへ直接書き込まれました！")

if __name__ == "__main__":
    print("🔍 Gmailの未読通知メールをスキャン中...")
    target_url = fetch_download_url()
    if target_url:
        print(f"🎯 新着動画通知を発見しました。URL: {target_url}")
        if login_and_download(target_url):
            upload_to_drive()
    else:
        print("📭 新しい未読通知メールはありませんでした。")
