from typing import Optional
from sqlmodel import Field
from sqlalchemy import UniqueConstraint

from app.db.models.base import BaseModelDB

class Player(BaseModelDB, table=True):
    __table_args__ = (
        UniqueConstraint("game_id", "order", name="uq_players_game_order"),
    )

    game_id: int = Field(foreign_key="game.id", index=True)
    color_id: int = Field(foreign_key="color.id", index=True)
    theme_id: int = Field(foreign_key="theme.id", index=True)

    name: str = Field(nullable=False)
    order: int = Field(nullable=False)

    pawn_row: Optional[int] = Field(default=None, nullable=True)
    pawn_col: Optional[int] = Field(default=None, nullable=True)
    allowed_steps: int = Field(default=1, nullable=False)