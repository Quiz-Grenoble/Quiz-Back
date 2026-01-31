from typing import Any, Optional, Sequence

from sqlmodel import select

from app.db.repositories.base import BaseRepository

from app.db.models.games import Game
from app.db.models.players import Player
from app.db.models.colors import Color
from app.db.models.themes import Theme

class GameRepository(BaseRepository[Game]):
    model = Game

    def get_by_url(self, url: str) -> Optional[Game]:
        stmt = select(Game).where(Game.url == url)
        return self.session.exec(stmt).first()

    def list_by_owner(self, owner_id: int, offset: int = 0, limit: int = 100) -> Sequence[Game]:
        stmt = (
            select(Game)
            .where(Game.owner_id == owner_id)
            .order_by(Game.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return self.session.exec(stmt).all()

    def list_by_owner_with_players_color_theme(self, owner_id: int) -> Sequence[Any]:
        """
        Retourne des lignes "plates" (Game + Player + Color.hex_code + Theme).
        Le service remap en structure hiérarchique.
        """
        stmt = (
            select(
                Game.id.label("game_id"),
                Game.url.label("game_url"),
                Game.seed,
                Game.rows_number,
                Game.columns_number,
                Game.finished,
                Game.with_pawns,
                Player.id.label("player_id"),
                Player.name.label("player_name"),
                Player.order.label("player_order"),
                Color.id.label("color_id"),
                Color.hex_code.label("color_hex_code"),
                Theme.id.label("theme_id"),
                Theme.name.label("theme_name"),
            )
            .join(Player, Player.game_id == Game.id, isouter=True)
            .join(Color, Color.id == Player.color_id, isouter=True)
            .join(Theme, Theme.id == Player.theme_id, isouter=True)
            .where(Game.owner_id == owner_id)
            .order_by(Game.created_at.desc(), Player.order.asc())
        )
        return self.session.exec(stmt).all()