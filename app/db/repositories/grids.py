from typing import Any, Sequence, Optional

from sqlmodel import select, func

from app.db.repositories.base import BaseRepository

from app.db.models.grids import Grid
from app.db.models.questions import Question
from app.db.models.themes import Theme
from app.db.models.games import Game

class GridRepository(BaseRepository[Grid]):
    model = Grid

    def list_grid_questions_with_theme_and_points(self, game_id: int) -> Sequence[Any]:
        """
        Récupère toutes les cases de grille avec la question + theme + points.
        """
        stmt = (
            select(
                Grid.id.label("grid_id"),
                Grid.row,
                Grid.column,
                Grid.round_id,
                Grid.correct_answer,
                Grid.skip_answer,
                Grid.question_id,
                Question.points.label("question_points"),
                Question.theme_id.label("question_theme_id"),
                Theme.name.label("question_theme_name"),
            )
            .join(Question, Question.id == Grid.question_id)
            .join(Theme, Theme.id == Question.theme_id)
            .where(Grid.game_id == game_id)
            .order_by(Grid.row.asc(), Grid.column.asc())
        )
        return self.session.exec(stmt).all()

    def list_answered_cells_for_scoring(self, game_id: int) -> Sequence[Any]:
        """
        Retourne uniquement les cases jouées (round_id non nul) avec points & theme_id.
        (Le calcul des points est fait dans le service.)
        """
        stmt = (
            select(
                Grid.id,
                Grid.round_id,
                Grid.correct_answer,
                Grid.skip_answer,
                Question.points.label("question_points"),
                Question.theme_id.label("question_theme_id"),
            )
            .join(Question, Question.id == Grid.question_id)
            .where(
                Grid.game_id == game_id,
                Grid.round_id.is_not(None),
                Grid.round_id > 0,
            )
        )
        return self.session.exec(stmt).all()
    
    def count_total_for_game(self, game_id: int) -> int:
        stmt = select(func.count(Grid.id)).where(Grid.game_id == game_id)
        return int(self.session.exec(stmt).one())

    def count_unanswered_for_game(self, game_id: int) -> int:
        stmt = select(func.count(Grid.id)).where(Grid.game_id == game_id, Grid.round_id.is_(None))
        return int(self.session.exec(stmt).one())

    def count_stats_for_question(self, question_id: int) -> dict:
        """Retourne le nombre de réponses positives, négatives et annulées pour une question.

        - positive: `correct_answer is True` and was played (round_id not null)
        - cancelled: `skip_answer is True` and was played
        - negative: played and not correct and not skipped
        """
        # positives (only from finished games)
        stmt_pos = (
            select(func.count(Grid.id))
            .select_from(Grid)
            .join(Game, Game.id == Grid.game_id)
            .where(
                Grid.question_id == question_id,
                Grid.round_id.is_not(None),
                Grid.correct_answer.is_(True),
                Game.finished.is_(True),
            )
        )
        pos = int(self.session.exec(stmt_pos).one())

        # cancelled (only from finished games)
        stmt_cancel = (
            select(func.count(Grid.id))
            .select_from(Grid)
            .join(Game, Game.id == Grid.game_id)
            .where(
                Grid.question_id == question_id,
                Grid.round_id.is_not(None),
                Grid.skip_answer.is_(True),
                Game.finished.is_(True),
            )
        )
        cancelled = int(self.session.exec(stmt_cancel).one())

        # negative: played, not skipped, not correct (only from finished games)
        stmt_neg = (
            select(func.count(Grid.id))
            .select_from(Grid)
            .join(Game, Game.id == Grid.game_id)
            .where(
                Grid.question_id == question_id,
                Grid.round_id.is_not(None),
                Grid.skip_answer.is_(False),
                Grid.correct_answer.is_(False),
                Game.finished.is_(True),
            )
        )
        neg = int(self.session.exec(stmt_neg).one())

        return {
            "positive": pos,
            "negative": neg,
            "cancelled": cancelled,
        }
    def list_by_game(self, game_id: int) -> Sequence[Grid]:
        stmt = select(Grid).where(Grid.game_id == game_id)
        return self.session.exec(stmt).all()

    def get_question_points(self, grid_id: int) -> Optional[int]:
        stmt = (
            select(Question.points)
            .join(Grid, Grid.question_id == Question.id)
            .where(Grid.id == grid_id)
        )
        result = self.session.exec(stmt).first()
        return int(result) if result is not None else None
