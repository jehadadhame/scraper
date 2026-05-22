from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import init_db


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    with testing_session() as db_session:
        yield db_session

