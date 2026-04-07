import sys
import subprocess

def _install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

try:
    import backgroundremover
except ImportError:
    print("⏳ Đang cài backgroundremover...")
    _install("backgroundremover")
    print("✔ Đã cài backgroundremover")

import requests
import subprocess
import json
import urllib.parse
import os
from io import BytesIO
from PIL import Image, ImageDraw
from zlapi.models import Message, MultiMsgStyle, MessageStyle
from zlapi._threads import ThreadType
import time
import random

des = {
    'version': "2.1.0",
    'credits': "Hoàng Vĩnh Phúc",
    'description': "Tạo sticker từ ảnh, GIF, video. Hỗ trợ xoá phông.",
    'power': "Thành viên"
}

def check_ffmpeg_webp_support():
    try:
        result = subprocess.run(["ffmpeg", "-codecs"], capture_output=True, text=True, check=True)
        return "libwebp_anim" in result.stdout or "libwebp" in result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def get_file_type(url):
    try:
        response = requests.head(url, allow_redirects=True, timeout=5)
        content_type = response.headers.get("Content-Type", "").lower()
        if "image" in content_type:
            return "image"
        elif "video" in content_type:
            return "video"
        return "unknown"
    except requests.RequestException:
        return "unknown"

def upload_to_uguu(file_path):
    try:
        with open(file_path, 'rb') as file:
            response = requests.post("https://uguu.se/upload", files={'files[]': file})
            return response.json().get('files')[0].get('url')
    except:
        return None

def remove_background(input_path, output_path):
    """Xoá phông bằng backgroundremover (local AI, không cần key)"""
    try:
        import backgroundremover.bg as bg_remover
        with open(input_path, "rb") as f:
            data = f.read()
        result = bg_remover.remove(data)
        with open(output_path, "wb") as f:
            f.write(result)
        return True
    except Exception as e:
        raise Exception(f"Lỗi xoá phông: {e}")

def convert_media_and_upload(media_url, file_type, unique_id, client, remove_bg=False):
    script_dir = os.path.dirname(__file__)
    temp_dir = os.path.join(script_dir, 'cache', 'temp')
    
    os.makedirs(temp_dir, exist_ok=True)

    temp_input = os.path.join(temp_dir, f"pro_input_{unique_id}")
    temp_nobg = os.path.join(temp_dir, f"nobg_{unique_id}.png")
    temp_webp = os.path.join(temp_dir, f"tranquan_{unique_id}.webp")
    
    files_to_cleanup = [temp_input, temp_nobg, temp_webp]

    try:
        response = requests.get(media_url, stream=True, timeout=15)
        response.raise_for_status()
        
        with open(temp_input, "wb") as f:
            for chunk in response.iter_content(8192):
                f.write(chunk)

        if file_type == "image":
            # Xoá phông nếu được yêu cầu
            if remove_bg:
                remove_background(temp_input, temp_nobg)
                source_path = temp_nobg
            else:
                source_path = temp_input

            with Image.open(source_path).convert("RGBA") as img:
                img.thumbnail((512, 512), Image.Resampling.LANCZOS)
                
                width, height = img.size
                mask = Image.new("L", (width, height), 0)
                draw = ImageDraw.Draw(mask)
                draw.rounded_rectangle((0, 0, width, height), radius=50, fill=255)
                img.putalpha(mask)
                img.save(temp_webp, format="WEBP", quality=80, lossless=False)
        else:
            subprocess.run([
                "ffmpeg", "-y", "-i", temp_input,
                "-vf", "scale=512:-2",
                "-c:v", "libwebp_anim",
                "-loop", "0",
                "-r", "15",
                "-an",
                "-lossless", "0",
                "-q:v", "80",
                "-loglevel", "error",
                temp_webp
            ], check=True, capture_output=True, text=True)

        return upload_to_uguu(temp_webp)

    except subprocess.CalledProcessError as e:
        print(f"Lỗi FFmpeg: {e.stderr}")
        raise Exception(f"Lỗi FFmpeg: {e.stderr}")
    except Exception as e:
        print(f"Lỗi khi chuyển đổi media: {e}")
        raise e
    finally:
        for f in files_to_cleanup:
            if os.path.exists(f):
                os.remove(f)

def get_media_url_from_attach(attach_data):
    """Lấy URL media từ attach, hỗ trợ cả ảnh thường lẫn sticker (webp)"""
    # Ưu tiên hdUrl, href
    url = attach_data.get('hdUrl') or attach_data.get('href')
    
    # Nếu là sticker (có params.webp.url)
    if not url:
        params = attach_data.get('params', {})
        webp = params.get('webp', {})
        url = webp.get('url')
    
    return url

def _handle_command(message, message_object, thread_id, thread_type, author_id, client, remove_bg=False):
    if not check_ffmpeg_webp_support():
        client.replyMessage(
            Message(text="➜ Lỗi: FFmpeg không hỗ trợ codec libwebp/libwebp_anim."),
            message_object, thread_id, thread_type, ttl=60000
        )
        return

    if not message_object.quote or not message_object.quote.attach:
        label = "xoá phông và tạo sticker" if remove_bg else "tạo sticker"
        client.replyMessage(
            Message(text=f"➜ Vui lòng reply vào ảnh, GIF hoặc video để {label}."),
            message_object, thread_id, thread_type, ttl=60000
        )
        return

    try:
        attach_data = json.loads(message_object.quote.attach)
    except (json.JSONDecodeError, TypeError):
        client.replyMessage(Message(text="➜ Dữ liệu đính kèm không hợp lệ."), message_object, thread_id, thread_type, ttl=60000)
        return

    media_url = get_media_url_from_attach(attach_data)
    if not media_url:
        client.replyMessage(Message(text="➜ Không tìm thấy URL của media."), message_object, thread_id, thread_type, ttl=60000)
        return

    media_url = urllib.parse.unquote(media_url.replace("\\/", "/"))

    if "jxl" in media_url:
        media_url = media_url.replace("jxl", "jpg")

    file_type = get_file_type(media_url)
    if file_type not in ["image", "video"]:
        client.replyMessage(Message(text="➜ Loại file không được hỗ trợ."), message_object, thread_id, thread_type, ttl=60000)
        return

    if remove_bg and file_type == "video":
        client.replyMessage(Message(text="➜ Xoá phông chỉ hỗ trợ ảnh, không hỗ trợ video/GIF."), message_object, thread_id, thread_type, ttl=60000)
        return

    status_text = "➜ ⏳ Đang xoá phông và tạo sticker, vui lòng chờ..." if remove_bg else "➜ ⏳ Đang xử lý, vui lòng chờ..."
    client.replyMessage(Message(text=status_text), message_object, thread_id, thread_type, ttl=120000)

    try:
        unique_id = f"{thread_id}_{int(time.time())}_{random.randint(1000, 9999)}"
        webp_url = convert_media_and_upload(media_url, file_type, unique_id, client, remove_bg=remove_bg)
        
        if not webp_url:
            raise Exception("Không thể tạo hoặc tải lên sticker.")

        client.sendCustomSticker(
            animationImgUrl=webp_url,
            staticImgUrl=webp_url,
            thread_id=thread_id,
            thread_type=thread_type,
            width=512,
            height=512
        )
        
    except Exception as e:
        client.replyMessage(
            Message(text=f"➜ Lỗi: {e}"),
            message_object, thread_id, thread_type, ttl=30000
        )

def handle_stk_command(message, message_object, thread_id, thread_type, author_id, client):
    _handle_command(message, message_object, thread_id, thread_type, author_id, client, remove_bg=False)

def handle_stkxp_command(message, message_object, thread_id, thread_type, author_id, client):
    _handle_command(message, message_object, thread_id, thread_type, author_id, client, remove_bg=True)

def get_mitaizl():
    return {
        'stk': handle_stk_command,
        'stkxp': handle_stkxp_command
    }
