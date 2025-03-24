# server.py
# Python 3.x

import http.server
import socketserver
import json
import os
import subprocess
import requests
import uuid
import concurrent.futures  # 用於多線程下載
import time
import requests
import re
import os
from datetime import timedelta


DOWNLOAD_DIR = r"E:\video_tmp"
DOWNLOAD_DIR_Video = ""
FFMPEG_PATH = os.path.join("D:\\Program\\ffmpeg-7.1.1-full_build\\bin", "ffmpeg.exe")

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

class MyHandler(http.server.SimpleHTTPRequestHandler):
    global DOWNLOAD_DIR_Video

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8', errors='ignore')

        try:
            data = json.loads(post_data)
            fileName = data.get("fileName", "video").replace("線上看 ", "").replace(" 帶字幕", "").replace(" ", "").split("–愛奇藝")[0].strip()
            m3u8_content = data.get("m3u8Content")
            srtContent = data.get("srtContent")
            duration = data.get("duration")

            if not m3u8_content:
                print("[ERROR] 沒有 m3u8Content，無法解析")
                self._send_text_response("missing m3u8Content")
                return

            print("=== m3u8_content (部分) ===")
            print(m3u8_content[:300], '...\n')

            # 建立子資料夾
            global DOWNLOAD_DIR_Video
            DOWNLOAD_DIR_Video = os.path.join(DOWNLOAD_DIR, fileName + "_tmp")
            if not os.path.exists(DOWNLOAD_DIR_Video):
                os.makedirs(DOWNLOAD_DIR_Video)

            # 解析 m3u8
            # extinf_s：M3U8 預估時間(秒)
            # ts_links：所有 .ts URL
            extinf_s, ts_links = parse_m3u8(m3u8_content)
            if not ts_links:
                print("[ERROR] M3U8 內無 TS 連結")
                self._send_text_response("no ts links")
                return

            print(f"[INFO] 共有 {len(ts_links)} 個 .ts 片段，開始多線程下載 (max 15 線程)...")

            # 下載 TS，並同時計算單一檔案的時長
            download_ts_multithread(ts_links, DOWNLOAD_DIR_Video)
            print(f"[INFO] (EXTINF) 預估總時長: {extinf_s} 秒 ")
            print("[INFO] 網站傳遞影片時長 =>", duration)

            # 開始合併, 帶入 ratio
            print("[INFO] 開始合併 TS 檔案 ->", fileName + ".mp4")
            output_path = os.path.join(DOWNLOAD_DIR, fileName + ".mp4")
            merge_ts_with_ffmpeg(ts_links, output_path, DOWNLOAD_DIR_Video)
            print("[INFO] 合併完成 =>", output_path)
            print("[INFO] 輸出影片時長 =>", get_duration_time(output_path))
            process_srt(srtContent, fileName, DOWNLOAD_DIR)

        except Exception as e:
            print("[ERROR] 接收或處理失敗:", e)
            self._send_text_response(f"error: {str(e)}", 500)

    def _send_text_response(self, message, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(message.encode('utf-8'))

def process_srt(srt_content, file_name, file_directory):

    # 下載並處理 .srt 檔案
    os.makedirs(file_directory, exist_ok=True)
    srt_url = "https://meta.video.iqiyi.com" + srt_content.replace('\u0026', '&')
    response = requests.get(srt_url)
    if response.status_code == 200:
        output_path = os.path.join(file_directory, f'{file_name}.srt')
        with open(output_path, 'w', encoding='utf-8') as file:
            file.write(response.text)
        print(f"[INFO] 已成功下載字幕: {output_path}")
    else:
        print(f"[ERROR] 無法下載 .srt 檔案，狀態碼: {response.status_code}")

def parse_m3u8(m3u8_str):
    """
    從 m3u8 字串中:
    1) 計算 extinf_s (EXTINF總秒數)
    2) 抓出所有 .ts 連結
    回傳 (extinf_s, ts_links)
    """
    m3u8_str = m3u8_str.replace('\\n', '\n')

    ts_links = []
    total_duration = 0.0
    lines = m3u8_str.splitlines()

    for i, line in enumerate(lines):
        line = line.strip()
        if line.startswith('#EXTINF:'):
            try:
                duration = float(line.split(':')[1].strip().rstrip(','))
                total_duration += duration
            except ValueError:
                print(f"[WARN] 時長解析錯誤 (第 {i+1} 行): {line}")
        elif ".ts" in line:
            ts_links.append(line.replace('\\u0026', '&'))
    return (total_duration, ts_links)
    
def download_ts_multithread(ts_links, download_dir):
    """
    多線程下載每個 .ts 檔案，
    下載後用 ffprobe 計算該檔案的時長(毫秒)，
    回傳每個檔案的毫秒陣列 durations_ms
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    durations_ms = []

    with ThreadPoolExecutor(max_workers=15) as executor:
        future_map = {}
        for i, link in enumerate(ts_links):
            file_name = f"segment_{i:04d}.ts"
            file_path = os.path.join(download_dir, file_name)
            fut = executor.submit(download_and_get_duration, link, file_path)
            future_map[fut] = i

        for fut in as_completed(future_map):
            idx = future_map[fut]
            try:
                ms = fut.result()
                durations_ms.append(ms)
            except Exception as e:
                print(f"[ERROR] future {idx} 發生錯誤: {e}")
                durations_ms.append(0)

    print("[INFO] 全部 影片檔 下載完畢")
    return durations_ms


def download_and_get_duration(url, file_path):
    """
    下載單一檔案 + 透過 ffprobe 解析該檔案實際時長(毫秒)
    """
    download_file(url, file_path)
    return 0


def download_file(url, file_path):
    """
    單一檔案下載
    若檔案已存在，會先檢查檔案大小，若完整則跳過下載
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # 檢查檔案是否已存在，若存在則檢查檔案完整性
            if os.path.exists(file_path):
                print(f"[INFO] 檔案已存在: {file_path}...")
                return  # 檔案已完整，無需重複下載

            # 檔案不存在或大小不符，開始下載
            if attempt!=0:
                print(f"[DOWNLOAD] 第 {attempt + 1} 次嘗試: {file_path}")
            resp = requests.get(url, stream=True, timeout=30)
            resp.raise_for_status()

            with open(file_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            print(f"[INFO] 下載成功: {file_path}")
            return  # 下載成功後直接返回

        except Exception as e:
            print(f"[WARN] 第 {attempt + 1} 次嘗試失敗，錯誤訊息: {e}")
            time.sleep(2)  # 等待2秒後重試

    print(f"[ERROR] 無法下載 {url}，已達到最大重試次數。")


def get_duration_time(file_path):
    """
    使用 ffprobe 獲取 ts 檔案的 start_time
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        file_path.strip("file '").strip("'")
    ]
    try:
        result = subprocess.check_output(cmd).decode("utf-8")
        match = re.search(r'"duration"\s*:\s*"([0-9.]+)"', result)
        return float(match.group(1)) if match else 0.0
    except subprocess.CalledProcessError:
        print(f"[錯誤] 無法分析 {file_path}，將其設為 0.0")
        return 0.0
        
def get_start_time(file_path):
    """
    使用 ffprobe 獲取 ts 檔案的 start_time
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        file_path.strip("file '").strip("'")
    ]
    try:
        result = subprocess.check_output(cmd).decode("utf-8")
        match = re.search(r'"start_time"\s*:\s*"([0-9.]+)"', result)
        return float(match.group(1)) if match else 0.0
    except subprocess.CalledProcessError:
        print(f"[錯誤] 無法分析 {file_path}，將其設為 0.0")
        return 0.0

def ts_list_with_duration(DOWNLOAD_DIR_Video):
    list_file = os.path.join(DOWNLOAD_DIR_Video, f"ts_list.txt")
    # 讀取原始檔案
    with open(list_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip().startswith("file ")]

    # 提取每個檔案的 start_time（多線程加速）
    with concurrent.futures.ThreadPoolExecutor() as executor:
        start_times = list(executor.map(lambda line: get_start_time(line.split("file '")[1].strip("'")), lines))

    # 如果所有 start_time 都是 0，提示用戶可能是 ffprobe 無法讀取檔案
    if all(time == 0.0 for time in start_times):
        print("[警告] 所有 start_time 均為 0，請檢查 ffprobe 是否安裝或檔案是否損壞。")
        return

    # 計算 duration
    output_lines = []
    for i in range(len(lines)):
        output_lines.append(lines[i])
        if i == 0:
            duration = start_times[i + 1] # 下一片段開始時間 - 當前片段開始時間
        elif i < len(lines) - 1:
            duration = start_times[i + 1] - start_times[i]  # 下一片段開始時間 - 當前片段開始時間
        else:
            # 最後一段影片預設長度，請根據實際情況調整
            duration = 6.0
        output_lines.append(f"duration {max(duration, 0.01):.2f}")  # 防止 duration 為 0

    # 輸出新的 ts_list_with_duration.txt
    list_file_with_duration = os.path.join(DOWNLOAD_DIR_Video, f"ts_list_with_duration.txt")
    with open(list_file_with_duration, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))
    return list_file_with_duration
    
    
def merge_ts_with_ffmpeg(ts_links, output_path, DOWNLOAD_DIR_Video):
    """
    使用 ffmpeg.exe 合併 TS 檔案
    """
    list_file = os.path.join(DOWNLOAD_DIR_Video, f"ts_list.txt")
    with open(list_file, "w", encoding="utf-8") as lf:
        for i, _ in enumerate(ts_links):
            file_name = f"segment_{i:04d}.ts"
            ts_path = os.path.join(DOWNLOAD_DIR_Video, file_name)
            lf.write(f"file '{ts_path}'\n")
    
    # 生成 ts_list_with_duration.txt
    list_file_with_duration = ts_list_with_duration(DOWNLOAD_DIR_Video)
    
    cmd = [
        FFMPEG_PATH,
        # "-fflags", "+genpts",
        "-v", "quiet",
        "-f", "concat",
        "-safe", "0",
        "-i", f'"{list_file_with_duration}"',
        "-c", "copy",
        # "-y",
        # "-fflags", "+genpts",
        f'"{output_path}"'
    ]
    print("[FFMPEG] 合併指令:", " ".join(cmd))
    subprocess.run(" ".join(cmd), shell=True, check=True)
    # os.remove(list_file)


if __name__ == "__main__":
    PORT = 18888
    print(f"[INFO] 啟動伺服器，監聽 port {PORT} ...")

    with socketserver.TCPServer(("0.0.0.0", PORT), MyHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("[INFO] 伺服器已停止")
            httpd.server_close()
