from flask import Flask, jsonify, request, send_from_directory, session
import sqlite3
from datetime import datetime
import os
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.urandom(24)
DB_PATH = os.path.join(app.root_path, "visitors.db")


def format_ts(val: str) -> str:
    if not val:
        return val
    try:
        dt = datetime.fromisoformat(val)
        return dt.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return val.replace("T", " ", 1)


def parse_ts(val: str):
    if not val:
        return None
    try:
        return datetime.strptime(val, "%d.%m.%Y %H:%M")
    except ValueError:
        return None


def init_db():
    os.makedirs(app.root_path, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
            CREATE TABLE IF NOT EXISTS visitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            tc TEXT NOT NULL,
            entry TEXT NOT NULL,
            meet TEXT NOT NULL,
            host TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            exit TEXT,
            photo TEXT,
            deleted INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            created_at TEXT
              )""")
    c.execute("""
            CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT
              )""")
    c.execute("PRAGMA table_info(users)")
    u_columns = [row[1] for row in c.fetchall()]
    if "is_admin" not in u_columns:
        c.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")

    default_username = "admin"
    default_password = "13579456Asd."
    hashed = generate_password_hash(default_password)
    created = format_ts(datetime.now().isoformat(timespec="minutes"))
    c.execute("SELECT id FROM users WHERE email=?", (default_username,))
    row = c.fetchone()
    if row:
        c.execute(
            "UPDATE users SET password=?, is_admin=1 WHERE email=?",
            (hashed, default_username),
        )
    else:
        c.execute(
            "INSERT INTO users (email, password, is_admin, created_at) VALUES (?,?,1,?)",
            (default_username, hashed, created),
        )
    c.execute("PRAGMA table_info(visitors)")
    columns = [row[1] for row in c.fetchall()]
    if "host" not in columns:
        c.execute("ALTER TABLE visitors ADD COLUMN host TEXT")
    if "exit" not in columns:
        c.execute("ALTER TABLE visitors ADD COLUMN exit TEXT")
    if "photo" not in columns:
        c.execute("ALTER TABLE visitors ADD COLUMN photo TEXT")
    if "deleted" not in columns:
        c.execute("ALTER TABLE visitors ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0")
    if "deleted_at" not in columns:
        c.execute("ALTER TABLE visitors ADD COLUMN deleted_at TEXT")
    if "created_at" not in columns:
        c.execute("ALTER TABLE visitors ADD COLUMN created_at TEXT")
    conn.commit()
    conn.close()

@app.before_request
def setup():
        init_db()

@app.route("/api/visitors", methods=["POST"])
def add_visitor():
    data = request.json
    required =["name", "entry", "meet", "host"]
    if not all(k in data and data[k].strip() for k in required):
        return "Tüm alanlar doldurulmalıdır.", 400
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    tc_value = data.get("tc", "").strip()
    photo_value = data.get("photo", "").strip()
    entry_value = format_ts(data["entry"])
    created_value = format_ts(datetime.now().isoformat(timespec="minutes"))
    c.execute(
        """
        INSERT INTO visitors (name, tc, entry, meet, host, active, photo, created_at)
        VALUES (?,?,?,?,?,1,?,?)
        """,
        (data["name"], tc_value, entry_value, data["meet"], data["host"], photo_value, created_value),
    )
    conn.commit()
    new_id = c.lastrowid
    conn.close()
    return jsonify({"message": "Kayıt başarılı", "id": new_id}), 200


@app.route("/api/visitors/<int:visitor_id>/checkout", methods=["POST"])
def checkout_visitor(visitor_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = format_ts(datetime.now().isoformat(timespec="minutes"))
    c.execute("UPDATE visitors SET active=0, exit=? WHERE id=? AND active=1 AND deleted=0", (now, visitor_id))
    conn.commit()
    updated = c.rowcount
    conn.close()
    if updated == 0:
        return jsonify({"message": "Ziyaretçi bulunamadı veya zaten çıkış yapmış."}), 404
    return jsonify({"message": "Ziyaretçi çıkışı tamamlandı."})


@app.route("/api/visitors/<int:visitor_id>/delete", methods=["POST"])
def delete_visitor(visitor_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = format_ts(datetime.now().isoformat(timespec="minutes"))
    c.execute(
        "UPDATE visitors SET deleted=1, deleted_at=?, active=0 WHERE id=? AND deleted=0",
        (now, visitor_id),
    )
    conn.commit()
    updated = c.rowcount
    conn.close()
    if updated == 0:
        return jsonify({"message": "Kayıt bulunamadı veya zaten silinmiş."}), 404
    return jsonify({"message": "Kayıt silindi."})


@app.route("/api/visitors/active", methods=["GET"])
def get_active():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute ("SELECT * FROM visitors WHERE active=1 AND deleted=0")
    rows = c.fetchall()
    conn.close()
    visitors = [dict(row) for row in rows]
    return jsonify(visitors)

@app.route("/api/reports", methods=["GET"])
def get_reports():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    scope = request.args.get("scope", "all")
    search = request.args.get("q", "").strip().lower()
    year_param = request.args.get("year")
    month_param = request.args.get("month")
    deleted_flag = request.args.get("deleted", "0") == "1"

    query = "SELECT id, name, tc, entry, meet, host, COALESCE(exit, '') as exit, active, COALESCE(photo, '') as photo, deleted, COALESCE(deleted_at,'') as deleted_at FROM visitors WHERE 1=1"
    params = []

    if deleted_flag:
        query += " AND deleted=1"
    else:
        query += " AND deleted=0"

    if scope == "month":
        now = datetime.now()
        year_val = now.year
        month_val = now.month
        try:
            if year_param:
                year_val = int(year_param)
            if month_param:
                month_val = int(month_param)
        except ValueError:
            pass
        if month_val < 1 or month_val > 12:
            month_val = now.month
        ym = f"{year_val}-{str(month_val).zfill(2)}"
        query += " AND substr(entry,1,7) = ?"
        params.append(ym)

    if search:
        like = f"%{search}%"
        query += " AND (lower(name) LIKE ? OR lower(meet) LIKE ? OR lower(host) LIKE ? OR lower(COALESCE(tc,'')) LIKE ? OR lower(COALESCE(entry,'')) LIKE ? OR lower(COALESCE(exit,'')) LIKE ?)"
        params.extend([like, like, like, like, like, like])

    query += " ORDER BY id DESC"
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    visitors = []
    now = datetime.now()
    for row in rows:
        item = dict(row)
        del_at = parse_ts(item.get("deleted_at"))
        if del_at:
            diff_min = (now - del_at).total_seconds() / 60.0
            item["purge_allowed"] = diff_min <= 10
        else:
            item["purge_allowed"] = False
        visitors.append(item)
    return jsonify({"visitors": visitors})


@app.route("/api/visitors/<int:visitor_id>/purge", methods=["POST"])
def purge_visitor(visitor_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT deleted, deleted_at FROM visitors WHERE id=?", (visitor_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"message": "Kayıt bulunamadı."}), 404
    if row["deleted"] != 1:
        conn.close()
        return jsonify({"message": "Önce silinenler listesinde olmalı."}), 400
    del_at = parse_ts(row["deleted_at"])
    if not del_at:
        conn.close()
        return jsonify({"message": "Silinme zamanı okunamadı."}), 400
    diff_min = (datetime.now() - del_at).total_seconds() / 60.0
    if diff_min > 10:
        conn.close()
        return jsonify({"message": "10 dakikayı geçtiği için kalıcı silinemez."}), 400
    c.execute("DELETE FROM visitors WHERE id=?", (visitor_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Kayıt kalıcı olarak silindi."})


@app.route("/api/ping")
def ping():
    return "ok", 200


@app.route("/api/users", methods=["POST"])
def create_user():
    if "user_id" not in session:
        return jsonify({"message": "Giriş yapmalısınız."}), 401

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT is_admin FROM users WHERE id=?", (session["user_id"],))
    current = c.fetchone()
    if not current or current["is_admin"] != 1:
        conn.close()
        return jsonify({"message": "Sadece admin yeni kullanıcı ekleyebilir."}), 403

    data = request.json or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        conn.close()
        return jsonify({"message": "Kullanıcı adı ve şifre gerekli."}), 400
    if len(password) < 8:
        conn.close()
        return jsonify({"message": "Şifre en az 8 karakter olmalı."}), 400

    try:
        hashed = generate_password_hash(password)
        created = format_ts(datetime.now().isoformat(timespec="minutes"))
        c.execute(
            "INSERT INTO users (email, password, is_admin, created_at) VALUES (?,?,0,?)",
            (username, hashed, created),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"message": "Bu kullanıcı adı zaten kayıtlı."}), 409

    conn.close()
    return jsonify({"message": "Kullanıcı oluşturuldu."}), 201


@app.route("/api/users/list", methods=["GET"])
def list_users():
    if "user_id" not in session:
        return jsonify({"message": "Giriş yapmalısınız."}), 401

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT is_admin FROM users WHERE id=?", (session["user_id"],))
    current = c.fetchone()
    if not current or current["is_admin"] != 1:
        conn.close()
        return jsonify({"message": "Sadece admin kullanıcıları görebilir."}), 403

    c.execute(
        "SELECT id, email, is_admin, created_at FROM users WHERE is_admin=0 ORDER BY email ASC"
    )
    users = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify({"users": users}), 200


@app.route("/api/users/delete", methods=["POST"])
def delete_user():
    if "user_id" not in session:
        return jsonify({"message": "Giriş yapmalısınız."}), 401

    data = request.json or {}
    user_id = data.get("user_id")
    username = (data.get("username") or "").strip()
    admin_password = (data.get("admin_password") or "").strip()
    if (not user_id and not username) or not admin_password:
        return jsonify({"message": "Silinecek kullanıcı ve admin şifresi gerekli."}), 400

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT * FROM users WHERE id=?", (session["user_id"],))
    current = c.fetchone()
    if not current or current["is_admin"] != 1:
        conn.close()
        return jsonify({"message": "Bu işlem için admin yetkisi gerekli."}), 403
    if not check_password_hash(current["password"], admin_password):
        conn.close()
        return jsonify({"message": "Admin şifresi hatalı."}), 401

    if user_id:
        c.execute("SELECT * FROM users WHERE id=?", (user_id,))
    else:
        c.execute("SELECT * FROM users WHERE email=?", (username,))
    user = c.fetchone()
    if not user:
        conn.close()
        return jsonify({"message": "Kullanıcı bulunamadı."}), 404

    if user["is_admin"] == 1:
        conn.close()
        return jsonify({"message": "Admin hesapları silinemez."}), 400

    c.execute("DELETE FROM users WHERE id=?", (user["id"],))
    conn.commit()
    conn.close()
    return jsonify({"message": "Kullanıcı kalıcı olarak silindi."}), 200


@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"message": "Kullanıcı adı ve şifre gerekli."}), 400
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email=?", (username,))
    user = c.fetchone()
    conn.close()
    if not user or not check_password_hash(user["password"], password):
        return jsonify({"message": "Kullanıcı adı veya şifre hatalı."}), 401
    is_admin = bool(user["is_admin"]) if "is_admin" in user.keys() else False
    session["user_id"] = user["id"]
    session["email"] = user["email"]
    session["is_admin"] = is_admin
    return jsonify(
        {
            "message": "Giriş başarılı.",
            "username": user["email"],
            "is_admin": is_admin,
        }
    ), 200


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Çıkış yapıldı."}), 200


@app.route("/api/me")
def me():
    if "user_id" not in session:
        return jsonify({"logged_in": False}), 200
    return jsonify(
        {
            "logged_in": True,
            "username": session.get("email"),
            "is_admin": bool(session.get("is_admin", False)),
        }
    ), 200

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

if __name__ == "__main__":
    app.run(debug=False)

