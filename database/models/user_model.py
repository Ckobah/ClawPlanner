from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, false, func, true

from database.session import Base


class User(Base):
    __tablename__ = "tg_users"

    id = Column(Integer, primary_key=True, index=True)
    tg_id = Column(BigInteger, index=True, nullable=True, unique=True)
    max_id = Column(BigInteger, index=True, nullable=True, unique=True)
    is_active = Column(Boolean, server_default=true(), comment="Признак, писал ли пользователь боту")

    username = Column(String(), nullable=True)
    first_name = Column(String(), nullable=True)
    last_name = Column(String(), nullable=True)
    time_shift = Column(Integer, nullable=True)
    time_zone = Column(String(50), nullable=True)
    language_code = Column(String(5), nullable=True)

    is_chat = Column(Boolean, server_default=false(), comment="Признак пользователя или чата")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UserRelation(Base):
    __tablename__ = "user_relations"

    user_id = Column(Integer, ForeignKey(User.id, ondelete="CASCADE"), primary_key=True)
    related_user_id = Column(Integer, ForeignKey(User.id, ondelete="CASCADE"), primary_key=True)
