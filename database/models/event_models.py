from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Time, func
from sqlalchemy.orm import relationship

from database.session import Base


class DbEvent(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    description = Column(String(), nullable=False, comment="Описание события")
    emoji = Column(String(length=8), nullable=True, comment="Эмодзи события")
    start_time = Column(Time, nullable=False, comment="Время начала события в UTC")

    start_at = Column(DateTime(timezone=True), nullable=False, comment="Время начала события в UTC")
    stop_at = Column(DateTime(timezone=True), nullable=True, comment="Время окончания события в UTC")

    single_event = Column(Boolean, nullable=True, comment="Флаг если событие одиночное")
    daily = Column(Boolean, nullable=True, comment="Флаг, если событие ежедневное")
    weekly = Column(Integer, nullable=True, comment="Номер недели, если событие еженедельное, UTC")
    monthly = Column(Integer, nullable=True, comment="День, если событие ежемесячное, UTC")
    annual_day = Column(Integer, nullable=True, comment="День, если событие ежегодное, UTC")
    annual_month = Column(Integer, nullable=True, comment="Месяц, если событие ежегодное, UTC")

    tg_id = Column(BigInteger, nullable=True, comment="Юзер тг id, кому принадлежит событие")
    max_id = Column(BigInteger, nullable=True, comment="MAX user id")
    creator_tg_id = Column(BigInteger, nullable=True, comment="Creator tg id")
    creator_max_id = Column(BigInteger, nullable=True, comment="Creator max id")
    canceled_events = relationship("CanceledEvent", back_populates="event", lazy="selectin", uselist=True, cascade="all, delete-orphan")
    participants = relationship("EventParticipant", back_populates="event", lazy="selectin", uselist=True, cascade="all, delete-orphan")

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CanceledEvent(Base):
    __tablename__ = "canceled_events"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    cancel_date = Column(Date, nullable=False, comment="Дата отмены события")
    event_id = Column(Integer, ForeignKey(DbEvent.id, ondelete="CASCADE"))

    event = relationship(DbEvent, back_populates="canceled_events")


class EventParticipant(Base):
    __tablename__ = "event_participants"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey(DbEvent.id, ondelete="CASCADE"))
    participant_tg_id = Column(BigInteger, nullable=True, comment="ID участника")
    participant_max_id = Column(BigInteger, nullable=True, comment="MAX participant id")

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    event = relationship(DbEvent, back_populates="participants")
