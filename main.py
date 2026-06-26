import os
import sys
import re
import time
import imaplib
import email
import zipfile
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

# 💡 安全な一時ローカルフォルダに保存させます
DRIVE_TARGET_PATH = Path("/home/runner/upload_staging")

def fetch_all_download_urls():
    urls_with_ids = []
    mail = None
    try:
        print("🔓 Gmailサーバーへ接続を試みています...")
        import socket
        socket.setdefaulttimeout(15)
        
        mail = imaplib.IMAP4_SSL("imap.gmail.com", timeout=15)
        mail.login(GMAIL_USER, GMAIL_PASS)
        mail.select("inbox")
        
        status, messages = mail.search(None, '(UNSEEN FROM "noreply@safie.jp")')
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
                media_id = "unknown"
                media_id_match = re.search(r'mediaid=(\d+)', url)
                if media_id_match:
                    media_id = media_id_match.group(1)
                
                urls_with_ids.append({"url": url, "id": m_id, "media_id": media_id})
                
        try: mail.logout()
        except: pass
        return urls_with_ids
    except Exception as e:
        print(f"❌ Gmail処理で例外が発生しました: {e}")
        if mail:
            try: mail.logout()
            except: pass
        return []

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
        print(f"🔗 SafieダウンロードURLへアクセス中: {download_url}")
        driver.get(download_url)
        wait = WebDriverWait(driver, 10)
        
        id_xpath = "//sf-login-page//sf-login//form/div[2]/div[2]//input"
        pw_xpath = "//sf-login-page//sf-login//form/div[2]/div[4]//input"
        
        wait.until(EC.element_to_be_clickable((By.XPATH, id_xpath))).send_keys(SAFIE_ID)
        driver.find_element(By.XPATH, pw_xpath).send_keys(SAFIE_PW)
        
        login_btn = "//sf-login-page//sf-login//form/div[2]/div[6]//sf-button-v1/div"
        driver.execute_script("arguments[0].click();", wait.until(EC.element_to_be_clickable((By.XPATH, login_btn))))
        
        timeout = 0
        while timeout < 180:
            crdownloads = list(download_dir.glob("*.crdownload"))
            zip_files = list(download_dir.glob("*.zip"))
            if not crdownloads and zip_files:
                is_success = True
                print("✅ SafieからのZIPダウンロードが100%完了しました。")
                break
            time.sleep(3)
            timeout += 3
    except Exception as e:
        print(f"❌ ブラウザ自動操作エラー: {e}")
    finally:
        try: driver.quit()
        except: pass
    return is_success

def save_to_mounted_drive(media_id):
    download_dir = Path("./downloads")
    zip_files = list(download_dir.glob("*.zip"))
    if not zip_files: 
        print("❌ 対象のZIPファイルが見つかりません。")
        return False
        
    target_zip = zip_files[0]
    folder_name = f"{target_zip.stem}_{media_id}"
    output_folder = DRIVE_TARGET_PATH / folder_name
    output_folder.mkdir(parents=True, exist_ok=True)
    print(f"📂 一時ローカルフォルダ内に動画展開先を作成しました: {output_folder}")
    
    with zipfile.ZipFile(target_zip, 'r') as zip_ref:
        for file_info in zip_ref.infolist():
            filename = os.path.basename(file_info.filename)
            if not filename or filename.startswith('.') or '__MACOSX' in file_info.filename:
                continue
                
            final_path = output_folder / filename
            print(f"🚀 ローカルステージングへ解凍中: {final_path.name}")
            file_data = zip_ref.read(file_info.filename)
            with open(final_path, 'wb') as f:
                f.write(file_data)
    return True

if __name__ == "__main__":
    DRIVE_TARGET_PATH.mkdir(parents=True, exist_ok=True)

    print("🔍 Gmailの未読通知メールをスキャン中...")
    target_emails = fetch_all_download_urls()
    
    if target_emails:
        print(f"🎯 合計 {len(target_emails)} 通の新着動画通知を発見しました。順次処理を開始します。")
        
        mail_client = None
        try:
            mail_client = imaplib.IMAP4_SSL("imap.gmail.com", timeout=15)
            mail_client.login(GMAIL_USER, GMAIL_PASS)
            mail_client.select("inbox")
            
            for idx, email_item in enumerate(target_emails, 1):
                print(f"\n--- ［{idx} / {len(target_emails)} 通目］の処理を開始 ---")
                if login_and_download(email_item['url']):
                    if save_to_mounted_drive(email_item['media_id']):
                        mail_client.store(email_item['id'], '+FLAGS', '\\Seen')
                        print(f"✅ {idx} 通目の処理が正常に完了し、既読にしました。")
                time.sleep(3)
                
            mail_client.logout()
            print("\n✨ 【すべての新着動画】のローカル展開が完了しました！")
        except Exception as loop_err:
            print(f"❌ 一括処理ループ全体でエラーが発生しました: {loop_err}")
            if mail_client:
                try: mail_client.logout()
                except: pass
    else:
        pass
