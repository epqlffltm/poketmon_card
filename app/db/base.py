# app/db/base.py

'''
모든 SQLAlchemy 모델이 상속할 Declarative Base.
Alembic이 target_metadata로 참조하는 지점이기도 하다.
'''

from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass