from sqlmodel import Field

from app.db.models.base import BaseModelDB


class Game(BaseModelDB, table=True):
    owner_id: int = Field(foreign_key="user.id", index=True)

    seed: int = Field(nullable=False)
    # string utilisé dans les URLs front (identifiant)
    url: str = Field(index=True, nullable=False, unique=True)

    rows_number: int = Field(nullable=False)
    columns_number: int = Field(nullable=False)
    finished: bool = Field(default=False, nullable=False)

    with_pawns: bool = Field(default=False, nullable=False)