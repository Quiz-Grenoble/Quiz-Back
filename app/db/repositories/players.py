from typing import Optional, Sequence

from sqlmodel import select

from app.db.repositories.base import BaseRepository

from app.db.models.players import Player

class PlayerRepository(BaseRepository[Player]):
    model = Player

    def list_by_game(self, game_id: int) -> Sequence[Player]:
        stmt = select(Player).where(Player.game_id == game_id).order_by(Player.order.asc())
        return self.session.exec(stmt).all()

    def get_by_game_and_order(self, game_id: int, order: int) -> Optional[Player]:
        stmt = select(Player).where(Player.game_id == game_id, Player.order == order)
        return self.session.exec(stmt).first()
    
    def get_next_player_in_game(self, game_id: int, current_order: int) -> Optional[Player]:
        """
        Retourne le prochain joueur selon l'ordre (circulaire).
        - cherche d'abord order > current_order
        - sinon le plus petit order
        """
        stmt_next = (
            select(Player)
            .where(Player.game_id == game_id, Player.order > current_order)
            .order_by(Player.order.asc())
            .limit(1)
        )
        nxt = self.session.exec(stmt_next).first()
        if nxt:
            return nxt

        stmt_first = (
            select(Player)
            .where(Player.game_id == game_id)
            .order_by(Player.order.asc())
            .limit(1)
        )
        return self.session.exec(stmt_first).first()

    def update_pawn_position(
        self, player: Player, row: Optional[int], col: Optional[int], *, commit: bool = True
    ) -> Player:
        player.pawn_row = row
        player.pawn_col = col
        self.session.add(player)
        if commit:
            self.session.commit()
            self.session.refresh(player)
        return player

    def update_allowed_steps(
        self, player: Player, allowed_steps: int, *, commit: bool = True
    ) -> Player:
        player.allowed_steps = allowed_steps
        self.session.add(player)
        if commit:
            self.session.commit()
            self.session.refresh(player)
        return player