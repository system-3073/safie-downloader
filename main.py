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

# Googleドライブ上の保存先パス（マウント先）
DRIVE_TARGET_PATH = Path("/home/runner/googledrive")

# ==============================================================================
# 1. Gmailから「すべての未読通知メール」のURLをリストで取得する関数
# ==============================================================================
def fetch_all_download_urls():
    urls_with_ids = []
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_PASS)
        mail.select("inbox")
        
        # Safieからの未読メールをすべて検索
        status, messages = mail.search(None, '(UNSEEN FROM "noreply@safie.jp")')
        if not messages[0]:
            mail.logout()
            return urls_with_ids
            
        mail_ids = messages[0].split()
        
        # 見つかった未読メールを1通ずつ解析
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
                # 後で既読化するために、URLとメールIDをセットで記録
                urls_with_ids.append({"url": url_match.group(0), "id": m_id, "client": mail})
                
        # 💡 メールセッションは維持したまま一度リストを返します
        return urls_with_ids
    except Exception as e:
        print(f"❌ Gmail処理エラー: {e}")
        return []

# ==============================================================================
# 2. Seleniumで自動ログインしてダウンロードを開始する関数
# ==============================================================================
def login_and_download(download_url):
    # 毎回保存先を綺麗にするため、前回の残骸があれば削除して再作成
    download_dir = Path("./downloads")
    if download_dir.exists():
        for f in download_dir.glob("*"): f.unlink()
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
                print("✅ SafieからのZIPダウンロードが100%完了しました。")
                break
            time.sleep(3)
            timeout += 3
    except Exception as e:
        print(f"❌ ブラウザ自動操作エラー: {e}")
    finally:
        driver.quit()
    return is_success

# ==============================================================================
# 3. マウントされたGoogleドライブフォルダへ保存する関数
# ==============================================================================
def save_to_mounted_drive():
    download_dir = Path("./downloads")
    zip_files = list(download_dir.glob("*.zip"))
    if not zip_files: 
        print("❌ 対象のZIPファイルが見つかりません。")
        return False
        
    target_zip = zip_files[0]
    folder_name = target_zip.stem
    output_folder = DRIVE_TARGET_PATH / folder_name
    output_folder.mkdir(parents=True, exist_ok=True)
    print(f"🔓 指定フォルダ内に動画保存用フォルダを作成しました: {output_folder}")
    
    with zipfile.ZipFile(target_zip, 'r') as zip_ref:
        for file_info in zip_ref.infolist():
            filename = os.path.basename(file_info.filename)
            if not filename or filename.startswith('.') or '__MACOSX' in file_info.filename:
                continue
            
            print(f"🚀 マウント経由で指定フォルダへ直接転送中: {filename}")
            file_data = zip_ref.read(file_info.filename)
            with open(output_folder / filename, 'wb') as f:
                f.write(file_data)
    return True

# ==============================================================================
# メイン実行ルーチン（一括ループ処理）
# ==============================================================================
if __name__ == "__main__":
    if not DRIVE_TARGET_PATH.exists():
        print(f"❌ Googleドライブフォルダが正常にマウントされていません: {DRIVE_TARGET_PATH}")
        sys.exit(1)

    print("🔍 Gmailの未読通知メールをスキャン中...")
    target_emails = fetch_all_download_urls()
    
    if target_emails:
        print(f"🎯 合計 {len(target_emails)} 通の新着動画通知を発見しました。順次処理を開始します。")
        
        # 💡 見つかった未読メールの数だけループを回して連続処理します
        for idx, email_item in enumerate(target_emails, 1):
            print(f"\n--- ［{idx} / {len(target_emails)} 通目］の処理を開始 ---")
            print(f"🔗 URL: {email_item['url']}")
            
            if login_and_download(email_item['url']):
                if save_to_mounted_drive():
                    # ドライブへの転送が成功したメールだけをピンポイントで「既読」にする
                    email_item['client'].store(email_item['id'], '+FLAGS', '\\Seen')
                    print(f"✅ {idx} 通目の処理が正常に完了し、既読にしました。")
            
            # 連続アクセスによるSafie側のブロックを防ぐため、少し休憩
            time.sleep(5)
            
        # 最後に一括してGmailをログアウト
        target_emails[0]['client'].logout()
        print("\n✨ 【すべての新着動画】の一括転送処理が完了しました！")
    else:
        print("📭 新しい未読通知メールはありませんでした。")
