"""Repository for MatchingElement model."""

from typing import List, Sequence
from sqlmodel import select

from app.db.repositories.base import BaseRepository
from app.db.models.matching_elements import MatchingElement


class MatchingElementRepository(BaseRepository[MatchingElement]):
    """CRUD MatchingElement + requêtes spécifiques."""
    model = MatchingElement

    def list_by_question(
        self,
        question_id: int,
        *,
        offset: int = 0,
        limit: int = 1000,
    ) -> Sequence[MatchingElement]:
        """Retourne tous les éléments d'une question matching, triés par list_index puis position."""
        stmt = (
            select(self.model)
            .where(self.model.question_id == question_id)
            .order_by(self.model.list_index, self.model.position)
            .offset(offset)
            .limit(limit)
        )
        return self.session.exec(stmt).all()

    def create_many(self, items: List[MatchingElement], *, commit: bool = True) -> List[MatchingElement]:
        """
        Insert en masse des éléments matching.
        Si commit=False, l'appelant doit commit() lui-même (transaction globale).
        """
        self.session.add_all(items)
        if commit:
            self.session.commit()
            for item in items:
                self.session.refresh(item)
        return items

    def delete_by_question(self, question_id: int, *, commit: bool = True) -> int:
        """
        Supprime tous les éléments d'une question matching.
        Retourne le nombre d'éléments supprimés.
        """
        rows = self.session.exec(
            select(self.model).where(self.model.question_id == question_id)
        ).all()
        for r in rows:
            self.session.delete(r)
        if commit:
            self.session.commit()
        return len(rows)
