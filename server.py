# -*- coding: utf-8 -*-
"""
門板等比例貼圖與測量模擬器 - 本地輕量伺服器
支援：
1. 自動在資料夾中儲存上傳圖檔
2. 手動刪除、修改、重新命名資料夾中的圖檔（包括已存在的預設素材）
3. 自動同步 images_data.js 與 materials_library.json
4. 畫布進度自動存檔至本機 canvas_state.json
5. 提供 Web API 供模擬器前端即時互動
"""

import os
import sys
import json
import base64
import urllib.parse
import mimetypes
import webbrowser
import re
from http.server import HTTPServer, SimpleHTTPRequestHandler

PORT = 8000
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))

# 確保 MIME 類型齊全
mimetypes.add_type('image/png', '.png')
mimetypes.add_type('image/jpeg', '.jpg')
mimetypes.add_type('image/jpeg', '.jpeg')
mimetypes.add_type('image/jpeg', '.jfif')
mimetypes.add_type('image/webp', '.webp')
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/html', '.html')
mimetypes.add_type('application/json', '.json')

def sanitize_filename(filename):
    """清理檔名，保留中文與安全字元"""
    filename = os.path.basename(filename)
    filename = re.sub(r'[\\/*?:"<>|]', '_', filename)
    if not filename.strip():
        filename = "uploaded_image.png"
    return filename

def update_images_data_js(filename, data_url):
    """將新圖片加入 images_data.js 中，確保雙向同步"""
    js_path = os.path.join(WORKSPACE_DIR, 'images_data.js')
    try:
        content = ""
        if os.path.exists(js_path):
            with open(js_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        
        entry = f'  "{filename}": "{data_url}",\n'
        
        if 'window.LOCAL_IMAGE_DATA = {' in content:
            pattern = re.compile(rf'"{re.escape(filename)}":\s*"[^"]*",?\n?')
            content = pattern.sub('', content)
            idx = content.find('window.LOCAL_IMAGE_DATA = {') + len('window.LOCAL_IMAGE_DATA = {')
            new_content = content[:idx] + "\n" + entry + content[idx:]
        else:
            new_content = f"window.LOCAL_IMAGE_DATA = {{\n{entry}}};\n"
            
        with open(js_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"[*] 已同步更新 images_data.js -> {filename}")
    except Exception as e:
        print(f"[!] 更新 images_data.js 失敗: {e}")

def remove_from_images_data_js(filename):
    """從 images_data.js 移除圖片項目"""
    js_path = os.path.join(WORKSPACE_DIR, 'images_data.js')
    if not os.path.exists(js_path):
        return
    try:
        with open(js_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        pattern = re.compile(rf'\s*"{re.escape(filename)}":\s*"[^"]*",?\n?')
        new_content = pattern.sub('', content)
        with open(js_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"[-] 已自 images_data.js 移除 -> {filename}")
    except Exception as e:
        print(f"[!] 移除 images_data.js 項目失敗: {e}")

class DoorSimulatorHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WORKSPACE_DIR, **kwargs)

    def end_headers(self):
        # 允許跨來源請求 (CORS)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == '/api/status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            data = {
                "status": "ok",
                "folder": WORKSPACE_DIR,
                "server": "DoorSimulator-LocalServer"
            }
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            return

        if path == '/api/images':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            
            image_extensions = ('.png', '.jpg', '.jpeg', '.jfif', '.webp')
            images = []
            for fname in os.listdir(WORKSPACE_DIR):
                if fname.lower().endswith(image_extensions):
                    fpath = os.path.join(WORKSPACE_DIR, fname)
                    stat = os.stat(fpath)
                    label = os.path.splitext(fname)[0]
                    images.append({
                        "file": fname,
                        "label": label,
                        "size": stat.st_size,
                        "mtime": stat.st_mtime
                    })
            images.sort(key=lambda x: x['mtime'], reverse=True)
            self.wfile.write(json.dumps(images, ensure_ascii=False).encode('utf-8'))
            return

        if path == '/api/materials':
            materials_file = os.path.join(WORKSPACE_DIR, 'materials_library.json')
            if os.path.exists(materials_file):
                try:
                    with open(materials_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
                    return
                except Exception as e:
                    print(f"[!] 讀取素材庫失敗: {e}")

            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({"empty": True}).encode('utf-8'))
            return

        if path == '/api/load-state':
            state_file = os.path.join(WORKSPACE_DIR, 'canvas_state.json')
            if os.path.exists(state_file):
                try:
                    with open(state_file, 'r', encoding='utf-8') as f:
                        state_data = json.load(f)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(json.dumps(state_data, ensure_ascii=False).encode('utf-8'))
                    return
                except Exception as e:
                    print(f"[!] 讀取狀態檔案失敗: {e}")

            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({"empty": True}).encode('utf-8'))
            return

        # 靜態文件處理
        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get('Content-Length', 0))
        post_body = self.rfile.read(content_length)

        if path == '/api/upload':
            try:
                data = json.loads(post_body.decode('utf-8'))
                raw_filename = data.get('fileName', 'upload.png')
                data_url = data.get('dataUrl', '')
                label = data.get('label') or os.path.splitext(raw_filename)[0]

                if not data_url or not data_url.startswith('data:'):
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Invalid dataUrl"}).encode('utf-8'))
                    return

                # 解析 base64
                header, encoded = data_url.split(',', 1)
                file_bytes = base64.b64decode(encoded)

                # 決定副檔名
                ext = '.png'
                if 'image/jpeg' in header:
                    ext = '.jpg'
                elif 'image/webp' in header:
                    ext = '.webp'
                
                safe_name = sanitize_filename(raw_filename)
                base_name, file_ext = os.path.splitext(safe_name)
                if not file_ext:
                    file_ext = ext
                    safe_name = base_name + file_ext

                target_path = os.path.join(WORKSPACE_DIR, safe_name)
                counter = 1
                while os.path.exists(target_path):
                    if os.path.getsize(target_path) == len(file_bytes):
                        break
                    safe_name = f"{base_name}_{counter}{file_ext}"
                    target_path = os.path.join(WORKSPACE_DIR, safe_name)
                    counter += 1

                # 寫入實體檔案到資料夾
                with open(target_path, 'wb') as f:
                    f.write(file_bytes)

                print(f"[+] 成功在資料夾新增檔案: {safe_name} ({len(file_bytes)} bytes)")

                # 同步更新 images_data.js
                update_images_data_js(safe_name, data_url)

                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                res = {
                    "success": True,
                    "fileName": safe_name,
                    "label": label,
                    "fileUrl": f"./{safe_name}",
                    "size": len(file_bytes)
                }
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
                return
            except Exception as e:
                print(f"[!] 上傳失敗: {e}")
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
                return

        if path == '/api/materials':
            try:
                materials_data = json.loads(post_body.decode('utf-8'))
                materials_file = os.path.join(WORKSPACE_DIR, 'materials_library.json')
                with open(materials_file, 'w', encoding='utf-8') as f:
                    json.dump(materials_data, f, ensure_ascii=False, indent=2)

                print(f"[*] 側邊欄素材清單已同步更新至 materials_library.json")
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
                return
            except Exception as e:
                print(f"[!] 儲存素材庫失敗: {e}")
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
                return

        if path == '/api/materials/rename':
            try:
                data = json.loads(post_body.decode('utf-8'))
                old_filename = sanitize_filename(data.get('oldFileName', ''))
                new_filename = sanitize_filename(data.get('newFileName', ''))
                
                if old_filename and new_filename and old_filename != new_filename:
                    old_path = os.path.join(WORKSPACE_DIR, old_filename)
                    new_path = os.path.join(WORKSPACE_DIR, new_filename)
                    if os.path.exists(old_path) and not os.path.exists(new_path):
                        os.rename(old_path, new_path)
                        print(f"[*] 檔案已重命名: {old_filename} -> {new_filename}")

                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
                return
            except Exception as e:
                print(f"[!] 重命名失敗: {e}")
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
                return

        if path == '/api/save-state':
            try:
                state_data = json.loads(post_body.decode('utf-8'))
                state_file = os.path.join(WORKSPACE_DIR, 'canvas_state.json')
                with open(state_file, 'w', encoding='utf-8') as f:
                    json.dump(state_data, f, ensure_ascii=False, indent=2)
                
                print(f"[*] 畫布進度已自動儲存至 canvas_state.json ({len(state_data.get('layers', []))} 個圖層)")

                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
                return
            except Exception as e:
                print(f"[!] 儲存狀態失敗: {e}")
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
                return

        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith('/api/images/'):
            filename = urllib.parse.unquote(path[len('/api/images/'):])
            safe_name = sanitize_filename(filename)
            target_path = os.path.join(WORKSPACE_DIR, safe_name)

            # 允許刪除任何指定的圖片檔案 (包括既有圖片，完全尊重使用者整理需求)
            if os.path.exists(target_path):
                try:
                    os.remove(target_path)
                    print(f"[-] 成功刪除檔案: {safe_name}")
                    remove_from_images_data_js(safe_name)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "deleted": safe_name}).encode('utf-8'))
                    return
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
                    return
            else:
                # 即使檔案實體不存在，也嘗試從 images_data.js 移除
                remove_from_images_data_js(safe_name)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "note": "file not found on disk, cleaned js cache"}).encode('utf-8'))
                return

            self.send_response(404)
            self.end_headers()
            return

def start_server():
    global PORT
    while PORT < 8050:
        try:
            server = HTTPServer(('127.0.0.1', PORT), DoorSimulatorHandler)
            break
        except OSError:
            PORT += 1

    url = f"http://localhost:{PORT}/index.html"
    print("=" * 65)
    print("  🚀 門板等比例貼圖與測量模擬器 本機伺服器已啟動！")
    print(f"  🌐 瀏覽器網址: {url}")
    print(f"  📂 檔案存放目錄: {WORKSPACE_DIR}")
    print("  💡 上傳的圖片將自動儲存為實體檔案於此資料夾中")
    print("  ✏️ 側邊欄圖片支援手動修改名稱與刪除，隨心整理素材清單")
    print("  💾 編輯進度將自動儲存至 canvas_state.json，下次開啟無縫繼續")
    print("=" * 65)

    try:
        webbrowser.open(url)
    except Exception:
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n伺服器已停止。")
        server.server_close()

if __name__ == '__main__':
    start_server()
