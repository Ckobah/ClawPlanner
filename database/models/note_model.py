from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text, func

from database.session import Base


class DbNote(Base):
    __tablename__ = "tg_note"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("tg_users.id", ondelete="CASCADE"), nullable=False, index=True, comment="Владелец заметки")
    note_text = Column(Text, nullable=False, comment="Текст заметки")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
