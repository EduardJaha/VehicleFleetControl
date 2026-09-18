from sqlalchemy import Column, ForeignKey, Integer, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, declared_attr, sessionmaker, with_loader_criteria
from app.core.config import get_settings

settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {"connect_timeout": 5, "options": "-c statement_timeout=120000"}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)


class TenantSession(Session):
    """A request/session boundary carrying the currently selected company."""


SessionLocal = sessionmaker(class_=TenantSession, autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class TenantMixin:
    """Marker and required key for data owned by a customer company."""

    @declared_attr
    def company_id(cls):
        # The Python default preserves compatibility for isolated model tests.
        # Authenticated requests always replace it from TenantSession.info.
        return Column(
            "CompanyId",
            Integer,
            ForeignKey("Companies.Id", ondelete="RESTRICT"),
            nullable=False,
            default=1,
            server_default="1",
            index=True,
        )


def set_tenant_context(db: Session, company_id: int) -> None:
    if company_id <= 0:
        raise ValueError("company_id must be a positive integer")
    db.info["company_id"] = company_id


def clear_tenant_context(db: Session) -> None:
    db.info.pop("company_id", None)


@event.listens_for(TenantSession, "do_orm_execute")
def _scope_tenant_queries(execute_state) -> None:
    company_id = execute_state.session.info.get("company_id")
    if company_id is None or execute_state.execution_options.get("skip_tenant_scope"):
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantMixin,
            lambda entity: entity.company_id == company_id,
            include_aliases=True,
        )
    )


@event.listens_for(TenantSession, "before_flush")
def _enforce_tenant_writes(session: Session, _flush_context, _instances) -> None:
    company_id = session.info.get("company_id")
    if company_id is None:
        return
    for row in session.new:
        if isinstance(row, TenantMixin):
            if row.company_id is None:
                row.company_id = company_id
            elif row.company_id != company_id:
                raise ValueError("Cannot create a record for another company.")
    for row in session.dirty:
        is_current_user = row.__class__.__name__ == "User" and row.id == session.info.get("user_id")
        if isinstance(row, TenantMixin) and row.company_id != company_id and not is_current_user:
            raise ValueError("Cannot modify a record for another company.")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Lazy imports avoid model/service cycles; every writer uses the same outbox hooks.
@event.listens_for(Session, "after_flush")
def _capture_integration_events(db, context):
    from app.services.integration_events import capture_events
    capture_events(db, context)


@event.listens_for(Session, "after_flush_postexec")
def _persist_integration_events(db, context):
    from app.services.integration_events import persist_events
    persist_events(db, context)


@event.listens_for(Session, "after_rollback")
def _clear_integration_events(db):
    db.info.pop("integration_events", None)
