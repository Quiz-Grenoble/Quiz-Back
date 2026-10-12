"""Repository for MatchingCorrectPair model."""

from typing import List, Sequence
from sqlmodel import select

from app.db.repositories.base import BaseRepository
from app.db.models.matching_correct_pairs import MatchingCorrectPair


class MatchingCorrectPairRepository(BaseRepository[MatchingCorrectPair]):
    """CRUD MatchingCorrectPair + requêtes spécifiques."""
    model = MatchingCorrectPair

    def list_by_question(
        self,
        question_id: int,
        *,
        offset: int = 0,
        limit: int = 1000,
    ) -> Sequence[MatchingCorrectPair]:
        """Retourne toutes les paires correctes d'une question matching."""
        stmt = (
            select(self.model)
            .where(self.model.question_id == question_id)
            .offset(offset)
            .limit(limit)
        )
        return self.session.exec(stmt).all()

    def create_many(self, items: List[MatchingCorrectPair], *, commit: bool = True) -> List[MatchingCorrectPair]:
        """
        Insert en masse des paires correctes.
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
        Supprime toutes les paires correctes d'une question matching.
        Retourne le nombre de paires supprimées.
        """
        rows = self.session.exec(
            select(self.model).where(self.model.question_id == question_id)
        ).all()
        for r in rows:
            self.session.delete(r)
        if commit:
            self.session.commit()
        return len(rows)
