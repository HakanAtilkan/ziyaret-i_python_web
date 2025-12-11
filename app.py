from flask import Flask, jsonify, request, send_from_directory
import sqlite3
from datetime import datetime
import os

app = Flask(__name__)
DB_PATH = os.path.join(app.root_path, "visitors.db")


def format_ts(val: str) -> str:
    """
    Format incoming ISO-like timestamp to DD.MM.YYYY HH:MM.
    If parsing fails, fall back to replacing 'T' with space.
    """
    if not val:
        return val
    try:
        dt = datetime.fromisoformat(val)
        return dt.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return val.replace("T", " ", 1)


def parse_ts(val: str):
    """Parse DD.MM.YYYY HH:MM; return datetime or None."""
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
    """Kalıcı silme: yalnızca silindikten sonraki 10 dakika içinde."""
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

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

if __name__ == "__main__":
    app.run(debug=False)

