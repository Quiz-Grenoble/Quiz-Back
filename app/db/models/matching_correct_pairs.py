"""
Model for matching question correct pairs.
Stores the correct associations between elements in matching questions.
"""

from sqlmodel import Field
from sqlalchemy import Column, ForeignKey, Integer

from .base import BaseModelDB


class MatchingCorrectPair(BaseModelDB, table=True):
    """
    Paires correctes pour une question de type matching.
    Définit les associations attendues entre éléments de différentes listes.
    """

    question_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("question.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        description="Question associée",
    )

    list_index_1: int = Field(
        ge=0,
        description="Index de la liste du premier élément",
    )

    element_position_1: int = Field(
        ge=0,
        description="Position du premier élément dans sa liste",
    )

    list_index_2: int = Field(
        ge=0,
        description="Index de la liste du second élément",
    )

    element_position_2: int = Field(
        ge=0,
        description="Position du second élément dans sa liste",
    )
