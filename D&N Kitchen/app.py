import os, sqlite3, json, secrets, time
from werkzeug.security import check_password_hash
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, g

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))


def _secret():
    # Kunci rahasia acak, dibuat sekali dan disimpan di secret.key
    p = os.path.join(BASE, "secret.key")
    if not os.path.exists(p):
        with open(p, "w") as f:
            f.write(secrets.token_hex(32))
    return open(p).read().strip()


app.secret_key = os.environ.get("SECRET_KEY") or _secret()
PW_FILE = os.path.join(BASE, "admin.json")  # dibuat oleh set_password.py
GAGAL = {}  # ip -> (jumlah gagal, terkunci sampai)


def password_diset():
    return os.path.exists(PW_FILE) or bool(os.environ.get("ADMIN_PASSWORD"))


def cek_password(pw):
    if os.path.exists(PW_FILE):
        with open(PW_FILE) as f:
            return check_password_hash(json.load(f)["hash"], pw)
    return secrets.compare_digest(pw, os.environ.get("ADMIN_PASSWORD", ""))
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dnkitchen.db")
STATUSES = ["Baru", "Diproses", "Selesai", "Dibatalkan"]

SEED = [
    ("Samyang Roll Original", 15000, "Mie samyang di gulung dengan rice paper dengan toping keju dan nori.", "🌶️"),
    ("Samyang Roll Mentai", 20000, "Samyang Roll dengan saus mentai dengan toping keju dan nori.", "🧂"),
    ("Dimsum Original isi 4", 13000, "Dimsum ayam original isi 4 dengan toping nori.", "🥟"),
    ("Dimsum original isi 6", 18000, "Dimsum ayam original isi 6 dengan toping nori.", "🥟"),
    ("Dimsum original isi 8", 22000, "Dimsum ayam original isi 8 dengan toping nori.", "🥟"),
    ("Dimsum Mentai isi 4", 20000, "Dimsum isi daging ayam dengan saus mentai dengan toping nori.", "🥟"),
    ("Dimsum Mentai isi 6", 25000, "Dimsum isi daging ayam dengan saus mentai dengan toping nori.", "🥟"),
    ("Dimsum Mentai isi 8", 34000, "Dimsum isi daging ayam dengan saus mentai dengan toping nori.", "🥟"),
]

# Foto menu ada di static/img/
GAMBAR = {
    "Samyang Roll Original": "samyang-roll-original.jpg",
    "Samyang Roll Mentai": "samyang-roll-mentai.jpg",
    "Dimsum Original isi 4": "dimsum-original.jpg",
    "Dimsum original isi 6": "dimsum-original.jpg",
    "Dimsum original isi 8": "dimsum-original.jpg",
    "Dimsum Mentai isi 4": "dimsum-mentai.jpg",
    "Dimsum Mentai isi 6": "dimsum-mentai.jpg",
    "Dimsum Mentai isi 8": "dimsum-mentai.jpg",
}

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()

def init_db():
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS menu(id INTEGER PRIMARY KEY, nama TEXT, harga INTEGER, deskripsi TEXT, emoji TEXT);
    CREATE TABLE IF NOT EXISTS pesanan(id INTEGER PRIMARY KEY, nama TEXT, telepon TEXT, alamat TEXT,
        catatan TEXT, total INTEGER, status TEXT DEFAULT 'Baru', dibuat TEXT DEFAULT (datetime('now','localtime')));
    CREATE TABLE IF NOT EXISTS item_pesanan(id INTEGER PRIMARY KEY, pesanan_id INTEGER, nama TEXT, harga INTEGER, qty INTEGER);
    """)
    if "gambar" not in [r[1] for r in c.execute("PRAGMA table_info(menu)")]:
        c.execute("ALTER TABLE menu ADD COLUMN gambar TEXT")
    # Jika daftar menu di SEED berubah, tabel menu diperbarui (riwayat pesanan tidak terpengaruh)
    if [r[0] for r in c.execute("SELECT nama FROM menu ORDER BY id")] != [x[0] for x in SEED]:
        c.execute("DELETE FROM menu")
        c.executemany("INSERT INTO menu(nama,harga,deskripsi,emoji) VALUES(?,?,?,?)", SEED)
    for nama, file in GAMBAR.items():
        c.execute("UPDATE menu SET gambar=? WHERE nama=?", (file, nama))
    c.commit()
    c.close()

@app.template_filter("rp")
def rp(n):
    return "Rp " + f"{int(n):,}".replace(",", ".")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/menu")
def menu():
    items = get_db().execute("SELECT * FROM menu").fetchall()
    return render_template("menu.html", items=items)

@app.route("/api/pesan", methods=["POST"])
def pesan():
    d = request.get_json(silent=True) or {}
    nama, telp, alamat = (d.get(k, "").strip() for k in ("nama", "telepon", "alamat"))
    if not (nama and telp and alamat):
        return jsonify(error="Nama, telepon, dan alamat wajib diisi."), 400
    db = get_db()
    rows, total = [], 0
    for it in d.get("items", []):
        m = db.execute("SELECT * FROM menu WHERE id=?", (it.get("id"),)).fetchone()
        qty = int(it.get("qty", 0) or 0)
        if m and 0 < qty <= 99:
            rows.append((m["nama"], m["harga"], qty))
            total += m["harga"] * qty
    if not rows:
        return jsonify(error="Keranjang masih kosong."), 400
    cur = db.execute("INSERT INTO pesanan(nama,telepon,alamat,catatan,total) VALUES(?,?,?,?,?)",
                     (nama, telp, alamat, d.get("catatan", "").strip(), total))
    db.executemany("INSERT INTO item_pesanan(pesanan_id,nama,harga,qty) VALUES(?,?,?,?)",
                   [(cur.lastrowid, *r) for r in rows])
    db.commit()
    return jsonify(ok=True, id=cur.lastrowid, total=total)

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not password_diset():
        return render_template("admin.html", login=True,
                               error="Password admin belum dibuat. Jalankan: python set_password.py")
    if request.method == "POST" and "password" in request.form:
        ip = request.remote_addr
        n, sampai = GAGAL.get(ip, (0, 0))
        if time.time() < sampai:
            return render_template("admin.html", login=True,
                                   error="Terlalu banyak percobaan. Coba lagi dalam 5 menit.")
        if cek_password(request.form["password"]):
            GAGAL.pop(ip, None)
            session["admin"] = True
            return redirect(url_for("admin"))
        n += 1
        GAGAL[ip] = (0, time.time() + 300) if n >= 5 else (n, 0)
        return render_template("admin.html", login=True, error="Password salah.")
    if not session.get("admin"):
        return render_template("admin.html", login=True)
    db = get_db()
    f = request.args.get("status", "")
    q = "SELECT * FROM pesanan" + (" WHERE status=?" if f in STATUSES else "") + " ORDER BY id DESC"
    orders = []
    for o in db.execute(q, (f,) if f in STATUSES else ()).fetchall():
        o = dict(o)
        o["items"] = db.execute("SELECT * FROM item_pesanan WHERE pesanan_id=?", (o["id"],)).fetchall()
        orders.append(o)
    stats = {s: db.execute("SELECT COUNT(*) FROM pesanan WHERE status=?", (s,)).fetchone()[0] for s in STATUSES}
    return render_template("admin.html", login=False, orders=orders, stats=stats, statuses=STATUSES, f=f)

@app.route("/admin/status/<int:oid>", methods=["POST"])
def ubah_status(oid):
    if not session.get("admin"):
        return redirect(url_for("admin"))
    s = request.form.get("status")
    if s in STATUSES:
        db = get_db()
        db.execute("UPDATE pesanan SET status=? WHERE id=?", (s, oid))
        db.commit()
    return redirect(request.referrer or url_for("admin"))

@app.route("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

init_db()
if __name__ == "__main__":
    app.run(debug=True)
