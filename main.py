import os
import sys
import re
import time
import imaplib
import email
import zipfile
import requests
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

GMAIL_USER = os.environ.get('GMAIL_USER')
GMAIL_PASS = os.environ.get('GMAIL_PASS')
SAFIE_ID = os.environ.get('SAFIE_ID')
SAFIE_PW = os.environ.get('SAFIE_PW')
CHAT_WEBHOOK_URL = os.environ.get('CHAT_WEBHOOK_URL')

DRIVE_TARGET_PATH = Path("/home/runner/upload_staging")
ROOT_FOLDER_ID = "17lDpuOIqM7iLQPLm_1EVOHqBxEQ7195K"

# ログを即座に画面へ出力させる（遅延防止）
sys.stdout.reconfigure(line_buffering=True)

# ==============================================================================
# Google Chatへリプライ（返信）を送る関数
# ==============================================================================
def send_google_chat_reply(text, case_no):
    if not CHAT_WEBHOOK_URL:
        print("⚠️ CHAT_WEBHOOK_URL が設定されていないため、通知をスキップします。")
        return
        
    url = CHAT_WEBHOOK_URL + "&messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
    payload = {
        "text": text,
        "thread": {
            "threadKey": f"yoom_case_{case_no}"
        }
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print(f"💬 案件No.{case_no} のメッセージへ正常にリプライを送信しました。")
        else:
            print(f"❌ Google Chat通知エラー ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"❌ Google Chat通信エラー: {e}")

import json

# ==============================================================================
# 🔗 店舗用フォルダの共有URL取得（lsjsonによる確実取得版）
# ==============================================================================
def get_drive_folder_url(parent_folder_name):
    try:
        print(f"🔎 Googleドライブの店舗フォルダIDを検索中... (`{parent_folder_name}`)")
        
        # rclone lsjson を使って大元フォルダ直下のサブフォルダ一覧をJSON形式で取得
        result = subprocess.run(
            ["rclone", "lsjson", "drive:", "--dirs-only"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15
        )
        
        if result.stdout:
            folders = json.loads(result.stdout)
            for item in folders:
                # フォルダ名が一致するものを探す
                if item.get("Path") == parent_folder_name or item.get("Name") == parent_folder_name:
                    folder_id = item.get("ID")
                    if folder_id:
                        print(f"🎯 店舗フォルダの固有IDを100%特定しました: {folder_id}")
                        return f"https://drive.google.com/drive/folders/{folder_id}"
                        
    except subprocess.TimeoutExpired:
        print("⚠️ フォルダID検索が10秒を超過したため、大元URLを使用します。")
    except Exception as e:
        print(f"⚠️ フォルダURL取得エラー: {e}")
    
    print("⚠️ 店舗フォルダが見つからなかったため、親フォルダのURLを返します。")
    return f"https://drive.google.com/drive/folders/{ROOT_FOLDER_ID}"
    
# ==============================================================================
# Gmail解析（高速接続 ＆ TO指定）
# ==============================================================================
def fetch_all_download_urls():
    urls_with_ids = []
    mail = None
    
    for attempt in range(1, 3):
        try:
            print(f"🔓 Gmailサーバーへ接続中... (試行 {attempt}/2)")
            import socket
            socket.setdefaulttimeout(15)
            
            mail = imaplib.IMAP4_SSL("imap.gmail.com", timeout=15)
            mail.login(GMAIL_USER, GMAIL_PASS)
            mail.select("inbox")
            
            search_criterion = f'(UNSEEN FROM "noreply@safie.jp" TO "{GMAIL_USER}")'
            status, messages = mail.search(None, search_criterion)
            
            if not messages[0]:
                print("📭 新しい未読通知メールはありませんでした。")
                try: mail.logout()
                except: pass
                return []
                
            mail_ids = messages[0].split()
            print(f"📩 未読メールを {len(mail_ids)} 通検知しました。解析中...")
            
            for m_id in mail_ids:
                status, data = mail.fetch(m_id, "(RFC822)")
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
                    url = url_match.group(0)
                    urls_with_ids.append({"url": url, "id": m_id})
                    
            try: mail.logout()
            except: pass
            return urls_with_ids

        except Exception as e:
            print(f"⚠️ Gmail接続一時エラー ({e})。再接続します...")
            if mail:
                try: mail.logout()
                except: pass
            time.sleep(2)
            
    return []

# ==============================================================================
# メール既読化関数
# ==============================================================================
def mark_email_as_read(email_id):
    try:
        m = imaplib.IMAP4_SSL("imap.gmail.com", timeout=15)
        m.login(GMAIL_USER, GMAIL_PASS)
        m.select("inbox")
        m.store(email_id, '+FLAGS', '\\Seen')
        m.logout()
        return True
    except Exception as e:
        print(f"⚠️ 既読スキップ: {e}")
        return False

# ==============================================================================
# Safieログイン ＆ ダウンロード
# ==============================================================================
def login_and_download(download_url):
    download_dir = Path("./downloads")
    if download_dir.exists():
        for f in download_dir.glob("*"): 
            try: f.unlink()
            except: pass
    download_dir.mkdir(exist_ok=True)

    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-gpu')
    
    prefs = {"download.default_directory": str(download_dir.resolve()), "download.prompt_for_download": False}
    options.add_experimental_option("prefs", prefs)
    
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(15)
    is_success = False
    
    try:
        print(f"🔗 Safieアクセス中: {download_url}")
        driver.get(download_url)
        wait = WebDriverWait(driver, 10)
        
        id_xpath = "//sf-login-page//sf-login//form/div[2]/div[2]//input"
        pw_xpath = "//sf-login-page//sf-login//form/div[2]/div[4]//input"
        
        wait.until(EC.element_to_be_clickable((By.XPATH, id_xpath))).send_keys(SAFIE_ID)
        driver.find_element(By.XPATH, pw_xpath).send_keys(SAFIE_PW)
        
        login_btn = "//sf-login-page//sf-login//form/div[2]/div[6]//sf-button-v1/div"
        driver.execute_script("arguments[0].click();", wait.until(EC.element_to_be_clickable((By.XPATH, login_btn))))
        
        timeout = 0
        while timeout < 120:
            crdownloads = list(download_dir.glob("*.crdownload"))
            zip_files = list(download_dir.glob("*.zip"))
            if not crdownloads and zip_files:
                is_success = True
                print("✅ ZIPダウンロード完了")
                break
            time.sleep(2)
            timeout += 2
    except Exception as e:
        print(f"❌ ブラウザエラー: {e}")
    finally:
        try: driver.quit()
        except: pass
    return is_success

# ==============================================================================
# ローカル解凍 ＆ フォルダ展開
# ==============================================================================
def save_to_dest_folder():
    download_dir = Path("./downloads")
    zip_files = list(download_dir.glob("*.zip"))
    if not zip_files: 
        print("❌ ZIPが見つかりません")
        return False
        
    target_zip = zip_files[0]
    zip_name = target_zip.stem
    
    case_no = "unknown"
    parent_folder_name = zip_name
    date_folder_name = "unknown_date"
    time_str = ""
    
    match = re.match(r'^(\d+)_(.+)_(\d{4}-\d{2}-\d{2})', zip_name)
    if match:
        case_no = match.group(1)
        shop_name = match.group(2)
        date_folder_name = match.group(3)
        parent_folder_name = f"{case_no}_{shop_name}"
    else:
        case_match = re.match(r'^(\d+)', zip_name)
        if case_match:
            case_no = case_match.group(1)
            
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', zip_name)
        if date_match:
            date_folder_name = date_match.group(1)
            parent_folder_name = zip_name.replace(f"_{date_folder_name}", "")

    with zipfile.ZipFile(target_zip, 'r') as zip_ref:
        for file_info in zip_ref.infolist():
            filename = os.path.basename(file_info.filename)
            if not filename or filename.startswith('.') or '__MACOSX' in file_info.filename:
                continue
                
            if not time_str and filename.endswith('.mp4'):
                time_match = re.search(r'(\d{2})-(\d{2})-(\d{2})', filename)
                if time_match:
                    time_str = f" {time_match.group(1)}:{time_match.group(2)}〜"
                
            output_folder = DRIVE_TARGET_PATH / parent_folder_name / date_folder_name
            output_folder.mkdir(parents=True, exist_ok=True)
            
            final_path = output_folder / filename
            print(f"🚀 解凍中: {final_path.name}")
            file_data = zip_ref.read(file_info.filename)
            with open(final_path, 'wb') as f:
                f.write(file_data)
                
    full_target_datetime = f"{date_folder_name}{time_str}"
    return {"case_no": case_no, "parent": parent_folder_name, "date": full_target_datetime}

# ==============================================================================
# メイン処理
# ==============================================================================
if __name__ == "__main__":
    DRIVE_TARGET_PATH.mkdir(parents=True, exist_ok=True)

    print("🔍 Gmailスキャン開始...")
    target_emails = fetch_all_download_urls()
    
    if target_emails:
        print(f"🎯 対象件数: {len(target_emails)} 件")
        result_info_list = []
        
        for idx, email_item in enumerate(target_emails, 1):
            print(f"\n--- ［{idx} / {len(target_emails)} 件目］ ---")
            if login_and_download(email_item['url']):
                info = save_to_dest_folder()
                if info:
                    result_info_list.append(info)
                    mark_email_as_read(email_item['id'])
            time.sleep(1)
            
        print("\n✨ 動画のローカル展開完了")
        
        jst = timezone(timedelta(hours=9))
        now_jst = datetime.now(jst).strftime("%Y-%m-%d %H:%M")
        
        for res_item in result_info_list:
            folder_url = get_drive_folder_url(res_item["parent"])
            
            reply_text = (
                f"└ ✅ *自動保存完了*\n"
                f"📂 ドライブへの同期アップロードが正常に完了しました。\n"
                f"🏢 対象店舗: `{res_item['parent']}`\n"
                f"📅 対象日時: `{res_item['date']}`\n"
                f"🔗 <{folder_url}|【共有URL】この案件の固定フォルダはこちら>\n"
                f"⏳ 完了時刻: {now_jst}"
            )
            send_google_chat_reply(reply_text, res_item["case_no"])
    else:
        print("📭 新着の対象メールはありませんでした。")
