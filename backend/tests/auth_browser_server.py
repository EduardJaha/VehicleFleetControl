"""Ephemeral API for the cookie browser test; never opens a business database."""
import socket

import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.authorization import seed_authorization_defaults
from app.core.security import hash_password
from app.db.session import Base, TenantSession, get_db
from app.main import app
from app.models import Company, CompanySettings, CompanyUser, User


def main():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=TenantSession)
    with factory() as db:
        db.add(Company(id=1, name="Cookie Test Fleet", slug="cookie-test"))
        db.add(CompanySettings(company_id=1))
        user = User(company_id=1, email="browser@test.local", full_name="Browser Admin", role="admin",
                    hashed_password=hash_password("test-only browser passphrase"))
        db.add(user)
        db.flush()
        db.add(CompanyUser(company_id=1, user_id=user.id, role="admin", is_default=True))
        db.commit()
        seed_authorization_defaults(db)

    def isolated_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    print(f"AUTH_TEST_PORT={sock.getsockname()[1]}", flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="error")).run(sockets=[sock])


if __name__ == "__main__":
    main()
