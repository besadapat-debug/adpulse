"""Command line: python -m app.cli [sync|seed|evaluate|create-user EMAIL PASSWORD]"""
import sys

from . import db
from .security import hash_password


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "sync":
        from .services.sync import sync_all
        sync_all()
        print("Sync complete")
    elif cmd == "seed":
        from .seed import seed
        seed()
        print("Seeded demo data (login demo@agency.test / demo1234)")
    elif cmd == "evaluate":
        from .services.alerts import evaluate_client
        for c in db.rows("SELECT id, name FROM clients"):
            print(c["name"], len(evaluate_client(c["id"])), "new alerts")
    elif cmd == "create-user" and len(sys.argv) >= 4:
        role = sys.argv[4] if len(sys.argv) > 4 else "owner"
        db.execute("INSERT INTO users (email, password_hash, role) VALUES (?,?,?)", (sys.argv[2].lower(), hash_password(sys.argv[3]), role))
        print("User created")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
