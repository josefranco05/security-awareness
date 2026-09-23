from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import create_engine


engine = create_engine(
    "sqlite:///database.db",
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine) 


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as db:
        yield db