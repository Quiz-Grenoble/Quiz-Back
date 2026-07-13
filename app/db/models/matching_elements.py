"""
Model for matching question elements.
Each element belongs to a specific list (list_index) and has a position within that list.
Elements can be either text or media (image/audio/video), but not both.
"""

from typing import Optional
from sqlmodel import Field
from sqlalchemy import Column, ForeignKey, Integer, CheckConstraint

from .base import BaseModelDB


class MatchingElement(BaseModelDB, table=True):
    """
    Éléments d'une question de type matching.
    Chaque élément appartient à une liste (list_index) et a une position dans cette liste.
    Le contenu est soit du texte, soit un média (mutuellement exclusif).
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

    list_index: int = Field(
        ge=0,
        description="Index de la liste à laquelle appartient cet élément (0-based)",
    )

    position: int = Field(
        ge=0,
        description="Position de l'élément dans sa liste (0-based)",
    )

    # Contenu de l'élément (text OU media, mutuellement exclusif)
    text: Optional[str] = Field(
        default=None,
        description="Contenu texte de l'élément (exclusif avec media)",
    )

    media_id: Optional[int] = Field(
        default=None,
        description="ID du média (Image/Audio/Video)",
    )

    media_type: Optional[str] = Field(
        default=None,
        description="Type de média: 'image', 'audio', ou 'video'",
    )

    __table_args__ = (
        CheckConstraint(
            "(text IS NOT NULL AND media_id IS NULL AND media_type IS NULL) OR "
            "(text IS NULL AND media_id IS NOT NULL AND media_type IS NOT NULL)",
            name="check_text_or_media",
        ),
        CheckConstraint(
            "media_type IS NULL OR media_type IN ('image', 'audio', 'video')",
            name="check_media_type_valid",
        ),
    )
