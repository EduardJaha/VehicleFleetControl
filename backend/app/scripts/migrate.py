"""Single deployment migration job, serialized across release runners."""
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from app.db.session import engine


def main():
    from app.core.deployment import validate_deployment
    validate_deployment()
    with engine.connect() as connection:
        if engine.dialect.name == 'postgresql':
            connection.execute(text('SELECT pg_advisory_lock(719304201)'))
            connection.commit()
        try:
            config = Config('alembic.ini')
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
        finally:
            connection.rollback()
            if engine.dialect.name == 'postgresql':
                connection.execute(text('SELECT pg_advisory_unlock(719304201)'))
                connection.commit()


if __name__ == '__main__':
    main()
