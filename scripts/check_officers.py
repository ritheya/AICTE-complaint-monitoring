from backend.app.database import SessionLocal
from backend.app.models.bureau import Officer
from backend.app.auth.security import verify_password

db = SessionLocal()
for o in db.query(Officer).all():
    print(o.email, "|", o.role, "| active:", o.is_active,
          "| Demo@123 works:", verify_password("Demo@123", o.password_hash))
db.close()