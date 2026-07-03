import os
import sys
import re
import time
import imaplib
import email
import zipfile
import requests
import subprocess  # 💡 rcloneコマンドを制御するために追加
from datetime import datetime
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
# 💡 共有いただいた大元の親フォルダIDを定義
ROOT_FOLDER_ID = "17lDpuOIqM7iLQPLm_1EVOHqBxEQ7195K"

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

# ==============================================================================
# 🔗 Googleドライブの新規作成されたフォルダのID（URL）を特定する関数
# ==============================================================================
def get_drive_folder_url(parent_folder_name):
    try:
        # rcloneのlsfコマンドを使い、大元フォルダの直下にある対象フォルダのIDを取得します
        # 実行コマンド例: rclone lsf drive: --format "id" --include "/案件No_店舗名/"
        # ※"drive:"の部分はご自身のrclone.confで設定したリモート名に合わせてください
        remote_target = f"drive:{parent_folder_name}"
        
        # フォルダIDを取得するためのrcloneコマンドを実行
        result = subprocess.run(
            ["rclone", "backend", "dirid", "drive:", parent_folder_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        folder_id = result.stdout.strip()
        if folder_id and not result.stderr:
            return f"https://drive.google.com/drive/folders/{folder_id}"
            
    except Exception as e:
        print(f"⚠️ フォルダURLの自動取得中にエラーが発生しました: {e}")
    
    # 💡 万が一IDが抜けなかった場合のフォールバック（大元のURLを案内する）
    return f"https://drive.google.com/drive/folders/{ROOT_FOLDER_ID}"

# ==============================================================================
# Gmail解析
# ==============================================================================
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
                urls_with_ids.append({"url": url, "id": m_id})
                
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

def save_to_dest_folder():
    download_dir = Path("./downloads")
    zip_files = list(download_dir.glob("*.zip"))
    if not zip_files: 
        print("❌ 対象のZIPファイルが見つかりません。")
        return False
        
    target_zip = zip_files[0]
    zip_name = target_zip.stem
    
    case_no = "unknown"
    parent_folder_name = zip_name
    date_folder_name = "unknown_date"
    
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
                
            output_folder = DRIVE_TARGET_PATH / parent_folder_name / date_folder_name
            output_folder.mkdir(parents=True, exist_ok=True)
            
            final_path = output_folder / filename
            print(f"🚀 ローカルステージング（{parent_folder_name}/{date_folder_name}）へ解凍中: {final_path.name}")
            file_data = zip_ref.read(file_info.filename)
            with open(final_path, 'wb') as f:
                f.write(file_data)
                
    # 💡 【重要】rcloneがGitHub ActionsのYAML側でアップロードを完了した「後」にURLを生成したいため、
    # 本来はここに書きたいですが、Pythonスクリプト終了後にYAML側でrcloneが動く構成の場合は、
    # 完了報告メッセージをこのsave_to_dest_folderの末尾ではなく、main処理の最後に移動します。
    return {"case_no": case_no, "parent": parent_folder_name, "date": date_folder_name}

if __name__ == "__main__":
    DRIVE_TARGET_PATH.mkdir(parents=True, exist_ok=True)

    print("🔍 Gmailの未読通知メールをスキャン中...")
    target_emails = fetch_all_download_urls()
    
    if target_emails:
        print(f"🎯 合計 {len(target_emails)} 通の新着動画通知を発見しました。順次処理を開始します。")
        
        mail_client = None
        result_info_list = []
        try:
            mail_client = imaplib.IMAP4_SSL("imap.gmail.com", timeout=15)
            mail_client.login(GMAIL_USER, GMAIL_PASS)
            mail_client.select("inbox")
            
            for idx, email_item in enumerate(target_emails, 1):
                print(f"\n--- ［{idx} / {len(target_emails)} 通目］の処理を開始 ---")
                if login_and_download(email_item['url']):
                    info = save_to_dest_folder()
                    if info:
                        result_info_list.append(info)
                        mail_client.store(email_item['id'], '+FLAGS', '\\Seen')
                        print(f"✅ {idx} 通目の処理が正常に完了し、既読にしました。")
                time.sleep(3)
                
            mail_client.logout()
            print("\n✨ 【すべての新着動画】のローカル展開が完了しました！")
            
            # 💡 もし現在、GitHub ActionsのYAML側で、このPythonの後に「rclone sync/copy」を実行している場合は、
            # アップロード完了後にこのスクリプトからチャット通知を送るため、
            # YAML内の「rcloneコマンド」の後に、もう一度この通知用ロジックを走らせるか、
            # あるいはPython内でrcloneを直接実行する形に寄せると、URL取得が100%確実になります。
            # 一旦、暫定のURL（大元ベース）をチャットに組み込むテキストを生成します。
            
            for res_item in result_info_list:
                # 🛠️ 店舗フォルダのピンポイントURLを生成（裏でrclone IDを取得）
                folder_url = get_drive_folder_url(res_item["parent"])
                
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                reply_text = (
                    f"└ ✅ *自動保存完了*\n"
                    f"📂 ドライブへの同期アップロードが正常に完了しました。\n"
                    f"🏢 対象店舗: `{res_item['parent']}`\n"
                    f"📅 保存日時: `{res_item['date']}`\n"
                    f"🔗 *【共有URL】この案件の固定フォルダはこちら* 👇\n"
                    f"{folder_url}\n"
                    f"⏳ 完了時刻: {now_str}"
                )
                send_google_chat_reply(reply_text, res_item["case_no"])
                
        except Exception as loop_err:
            print(f"❌ 一括処理ループ全体でエラーが発生しました: {loop_err}")
            if mail_client:
                try: mail_client.logout()
                except: pass
    else:
        pass
