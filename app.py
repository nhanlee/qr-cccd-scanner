import os
import base64
from datetime import datetime
from PIL import Image
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for, session
import mysql.connector
from dotenv import load_dotenv
import logging
import numpy as np
import cv2

# --- Load env ---
load_dotenv()

DB_HOST = os.getenv("DB_HOST", "yamanote.proxy.rlwy.net")
DB_PORT = int(os.getenv("DB_PORT", 22131))
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "wIGaLEezXhTLlSShztFWktORKCeSaEGO")
DB_NAME = os.getenv("DB_NAME", "railway")
IMAGES_DIR = os.getenv("IMAGES_DIR", "images")
YOLO_MODEL_PATH = os.getenv("YOLO_MODEL_PATH", "models/yolov8m-face.pt")

os.makedirs(IMAGES_DIR, exist_ok=True)

# Tạo Flask app với cấu hình đúng
app = Flask(__name__, 
            template_folder='templates',
            static_folder='static')
app.logger.setLevel(logging.INFO)
app.secret_key = os.getenv("SECRET_KEY", "your-secret-key-here")

# Bật debug mode để dễ tìm lỗi
app.config['DEBUG'] = True

# -------------------------
# DATABASE
# -------------------------
def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host=DB_HOST, 
            port=DB_PORT, 
            user=DB_USER, 
            password=DB_PASS, 
            database=DB_NAME,
            autocommit=True,
            connect_timeout=10
        )
        return conn
    except mysql.connector.Error as err:
        app.logger.error(f"Database connection error: {err}")
        return None

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
    cursor.execute(f"USE `{DB_NAME}`;")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS `users` (
        `id` INT AUTO_INCREMENT PRIMARY KEY,
        `username` VARCHAR(100) UNIQUE NOT NULL,
        `fullname` VARCHAR(255),
        `role` VARCHAR(50) DEFAULT 'user',
        `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS `cccd_records` (
        `id` INT AUTO_INCREMENT PRIMARY KEY,
        `cccd_moi` VARCHAR(50) UNIQUE NOT NULL,
        `cmnd_cu` VARCHAR(50),
        `name` VARCHAR(255),
        `dob` DATE,
        `gender` VARCHAR(20),
        `address` TEXT,
        `issue_date` DATE,
        `phone` VARCHAR(20),
        `user` VARCHAR(100),
        `front_image` VARCHAR(255),
        `back_image` VARCHAR(255),
        `face_cropped` VARCHAR(255),
        `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)
    
    cursor.close()
    conn.close()

init_db()

# -------------------------
# YOLO FACE DETECTOR
# -------------------------
yolo_detector = None
use_yolo = False
try:
    from ultralytics import YOLO
    if os.path.exists(YOLO_MODEL_PATH):
        yolo_detector = YOLO(YOLO_MODEL_PATH)
        use_yolo = True
        app.logger.info(f"Loaded YOLO model from {YOLO_MODEL_PATH}")
    else:
        app.logger.warning(f"YOLO model not found at {YOLO_MODEL_PATH}. Face crop disabled.")
except Exception as e:
    app.logger.warning(f"Ultralytics not available or failed to load: {e}. Face crop disabled.")

def crop_face_using_yolo(img_path, save_path):
    """Crop face using YOLO, save to save_path"""
    if not use_yolo or not yolo_detector:
        return False

    try:
        results = yolo_detector(img_path)
        if len(results) == 0 or len(results[0].boxes) == 0:
            return False

        box = results[0].boxes.xyxy[0].cpu().numpy()  # xmin, ymin, xmax, ymax
        img = Image.open(img_path)
        face = img.crop((box[0], box[1], box[2], box[3]))
        face.save(save_path)
        return True
    except Exception as e:
        app.logger.error(f"Face crop error: {e}")
        return False

# -------------------------
# HELPERS: PARSE QR
# -------------------------
def parse_qr_text(qr_text: str):
    if not qr_text:
        return None
        
    parts = qr_text.strip().split("|")
    if len(parts) < 7:
        return None
        
    cccd_moi = parts[0].strip() if len(parts) > 0 else ""
    cmnd_cu = parts[1].strip() if len(parts) > 1 else ""
    name = parts[2].strip() if len(parts) > 2 else ""
    dob_str = parts[3].strip() if len(parts) > 3 else ""
    gender = parts[4].strip() if len(parts) > 4 else ""
    address = parts[5].strip() if len(parts) > 5 else ""
    issue_date_str = parts[6].strip() if len(parts) > 6 else ""

    def parse_date(s):
        if not s:
            return None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except:
                continue
        return None

    dob = parse_date(dob_str)
    issue_date = parse_date(issue_date_str)

    return {
        "cccd_moi": cccd_moi,
        "cmnd_cu": cmnd_cu,
        "name": name,
        "dob": dob.isoformat() if dob else "",
        "gender": gender,
        "address": address,
        "issue_date": issue_date.isoformat() if issue_date else ""
    }

# -------------------------
# ROUTES
# -------------------------
@app.route("/")
def index():
    if 'user' in session:
        return render_template("main.html", username=session['user'])
    return redirect(url_for('login'))

@app.route("/login", methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template("login.html")
    
    try:
        data = request.json
        username = data.get("username", "").strip()
        
        if not username:
            return jsonify({"ok": False, "msg": "Vui lòng nhập username"}), 400
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Kiểm tra user có tồn tại không
        cur.execute("SELECT id, username, fullname FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        
        # Nếu user không tồn tại, tạo mới
        if not user:
            cur.execute("INSERT INTO users (username, fullname) VALUES (%s, %s)", 
                       (username, username))
            conn.commit()
            
            # Lấy lại thông tin user vừa tạo
            cur.execute("SELECT id, username, fullname FROM users WHERE username = %s", (username,))
            user = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if user:
            session['user'] = username
            session['user_id'] = user[0]
            session['fullname'] = user[2]
            return jsonify({
                "ok": True, 
                "msg": "Đăng nhập thành công",
                "user": {
                    "id": user[0],
                    "username": user[1],
                    "fullname": user[2]
                }
            })
        else:
            return jsonify({"ok": False, "msg": "Lỗi hệ thống"}), 500
            
    except Exception as e:
        app.logger.error(f"Login error: {str(e)}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('login'))

# 2) QUÉT QR
@app.route("/scan_qr_image", methods=["POST"])
def scan_qr_image():
    try:
        data = request.json
        img_data = data.get("image", "")
        qr_text = data.get("qr_text", "")
        
        # Ưu tiên sử dụng qr_text trực tiếp từ scanner
        parsed = None
        if qr_text:
            parsed = parse_qr_text(qr_text)
        
        # Nếu không có qr_text hoặc parse thất bại, thử decode từ ảnh
        if not parsed and img_data:
            encoded = img_data.split(",")[1] if "," in img_data else img_data
            img_bytes = base64.b64decode(encoded)

            img_array = np.frombuffer(img_bytes, np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            qr = cv2.QRCodeDetector()
            text, pts, _ = qr.detectAndDecode(img)
            
            if text:
                parsed = parse_qr_text(text)

        if not parsed:
            return jsonify({"ok": False, "msg": "Không đọc được QR hoặc QR sai định dạng"}), 400

        # Check duplicate
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM cccd_records WHERE cccd_moi = %s", (parsed["cccd_moi"],))
        exists = cur.fetchone()
        cur.close()
        conn.close()

        return jsonify({
            "ok": True, 
            "data": parsed, 
            "duplicate": bool(exists),
            "msg": "Đọc QR thành công"
        })

    except Exception as e:
        app.logger.error(f"QR scan error: {str(e)}")
        return jsonify({"ok": False, "error": str(e), "msg": "Lỗi xử lý QR"}), 500

# 3) SAVE FRONT IMAGE + CROP
@app.route("/save_front_image", methods=["POST"])
def save_front_image():
    try:
        cccd = request.form.get("cccd", "").strip()
        img64 = request.form.get("image", "")
        
        if not cccd or not img64:
            return jsonify({"ok": False, "error": "Thiếu dữ liệu"}), 400

        # Decode base64
        if "," in img64:
            img64 = img64.split(",")[1]
        
        raw = base64.b64decode(img64)

        front_name = f"cccd_front_{cccd}.jpg"
        front_path = os.path.join(IMAGES_DIR, front_name)
        with open(front_path, "wb") as f:
            f.write(raw)

        # YOLO face crop
        face_path = None
        if use_yolo:
            face_name = f"cccd_face_{cccd}.jpg"
            face_fullpath = os.path.join(IMAGES_DIR, face_name)
            success = crop_face_using_yolo(front_path, face_fullpath)
            if success:
                face_path = face_name

        return jsonify({
            "ok": True, 
            "front": front_name, 
            "face": face_path,
            "msg": "Lưu ảnh mặt trước thành công"
        })

    except Exception as e:
        app.logger.error(f"Save front image error: {str(e)}")
        return jsonify({"ok": False, "error": str(e), "msg": "Lỗi lưu ảnh mặt trước"}), 500

# 4) SAVE BACK IMAGE
@app.route("/save_back_image", methods=["POST"])
def save_back_image():
    try:
        cccd = request.form.get("cccd", "").strip()
        img64 = request.form.get("image", "")
        
        if not cccd or not img64:
            return jsonify({"ok": False, "error": "Thiếu dữ liệu"}), 400

        # Decode base64
        if "," in img64:
            img64 = img64.split(",")[1]
        
        raw = base64.b64decode(img64)

        back_name = f"cccd_back_{cccd}.jpg"
        back_path = os.path.join(IMAGES_DIR, back_name)
        with open(back_path, "wb") as f:
            f.write(raw)

        return jsonify({
            "ok": True, 
            "back": back_name,
            "msg": "Lưu ảnh mặt sau thành công"
        })

    except Exception as e:
        app.logger.error(f"Save back image error: {str(e)}")
        return jsonify({"ok": False, "error": str(e), "msg": "Lỗi lưu ảnh mặt sau"}), 500

# 5) SAVE RECORD TO DB
@app.route("/save_cccd_record", methods=["POST"])
def save_cccd_record():
    try:
        data = request.json
        cccd = data.get("cccd_moi", "").strip()
        
        if not cccd:
            return jsonify({"ok": False, "error": "Thiếu số CCCD"}), 400

        front_file = f"cccd_front_{cccd}.jpg"
        back_file = f"cccd_back_{cccd}.jpg"
        face_file = f"cccd_face_{cccd}.jpg"
        
        # Kiểm tra file tồn tại
        front_exists = os.path.exists(os.path.join(IMAGES_DIR, front_file))
        back_exists = os.path.exists(os.path.join(IMAGES_DIR, back_file))
        face_exists = os.path.exists(os.path.join(IMAGES_DIR, face_file))
        
        if not front_exists or not back_exists:
            return jsonify({"ok": False, "error": "Ảnh CCCD chưa được upload"}), 400

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO cccd_records
            (cccd_moi, cmnd_cu, name, dob, gender, address, issue_date, phone, user,
             front_image, back_image, face_cropped)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            data.get("cccd_moi", ""),
            data.get("cmnd_cu", ""),
            data.get("name", ""),
            data.get("dob") if data.get("dob") else None,
            data.get("gender", ""),
            data.get("address", ""),
            data.get("issue_date") if data.get("issue_date") else None,
            data.get("phone", ""),
            data.get("user", ""),
            front_file if front_exists else None,
            back_file if back_exists else None,
            face_file if face_exists else None,
        ))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"ok": True, "msg": "Lưu thông tin CCCD thành công"})

    except mysql.connector.Error as err:
        app.logger.error(f"Database error: {err}")
        if err.errno == 1062:  # Duplicate entry
            return jsonify({"ok": False, "error": "CCCD đã tồn tại trong hệ thống"}), 400
        return jsonify({"ok": False, "error": f"Database error: {err}"}), 500
    except Exception as e:
        app.logger.error(f"Save record error: {str(e)}")
        return jsonify({"ok": False, "error": str(e), "msg": "Lỗi lưu thông tin"}), 500

# 6) GET RECORDS BY USER
@app.route("/records/<username>", methods=["GET"])
def get_records_by_user(username):
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        
        cur.execute("""
            SELECT cccd_moi, name, dob, phone, front_image, back_image, face_cropped, created_at 
            FROM cccd_records 
            WHERE user = %s 
            ORDER BY created_at DESC
            LIMIT 50
        """, (username,))
        
        records = cur.fetchall()
        
        # Chuyển đổi date objects thành string
        for record in records:
            if record['dob']:
                record['dob'] = record['dob'].isoformat()
            if record['created_at']:
                record['created_at'] = record['created_at'].isoformat()
        
        cur.close()
        conn.close()
        
        return jsonify({
            "ok": True, 
            "records": records,
            "count": len(records),
            "msg": f"Tìm thấy {len(records)} bản ghi"
        })
        
    except Exception as e:
        app.logger.error(f"Get records error: {str(e)}")
        return jsonify({"ok": False, "error": str(e), "msg": "Lỗi lấy dữ liệu"}), 500

# 7) SERVE IMAGES
@app.route("/images/<filename>")
def serve_image(filename):
    try:
        return send_from_directory(IMAGES_DIR, filename)
    except Exception as e:
        app.logger.error(f"Serve image error: {str(e)}")
        return jsonify({"ok": False, "error": "Không tìm thấy ảnh"}), 404

# -------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)