import getpass, json, os
from werkzeug.security import generate_password_hash

base = os.path.dirname(os.path.abspath(__file__))
while True:
    p1 = getpass.getpass("Password admin baru (min. 8 karakter): ")
    if len(p1) < 8:
        print("Terlalu pendek, coba lagi.")
        continue
    if p1 != getpass.getpass("Ulangi password: "):
        print("Password tidak sama, coba lagi.")
        continue
    break
with open(os.path.join(base, "admin.json"), "w") as f:
    json.dump({"hash": generate_password_hash(p1)}, f)
print("Password admin tersimpan. Jalankan ulang python app.py.")
