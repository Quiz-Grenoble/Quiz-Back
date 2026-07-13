from typing import Optional, List
from sqlmodel import Field, Relationship
from sqlalchemy import Column, ForeignKey, Integer

from .base import BaseModelDB


class Question(BaseModelDB, table=True):
    """
    Questions associées à un thème.
    Les médias (image/audio/video) sont optionnels et séparés par table.
    Pour les questions de type 'matching', utilise les relations matching_elements et matching_correct_pairs.
    """

    question: str = Field(description="Intitulé de la question")
    answer: str = Field(description="Réponse attendue (utilisé uniquement pour type 'classic')")

    question_type: str = Field(
        default="classic",
        description="Type de question: 'classic' (texte simple) ou 'matching' (association d'éléments)"
    )

    points: int = Field(default=1, ge=0, description="Points attribués à la question")

    # FK obligatoire vers Theme
    theme_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("theme.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        description="Thème associé",
    )

    # Images optionnelles
    question_image_id: Optional[int] = Field(default=None, foreign_key="image.id")
    answer_image_id: Optional[int] = Field(default=None, foreign_key="image.id")

    # Audios optionnels
    question_audio_id: Optional[int] = Field(default=None, foreign_key="audio.id")
    answer_audio_id: Optional[int] = Field(default=None, foreign_key="audio.id")

    # Videos optionnelles
    question_video_id: Optional[int] = Field(default=None, foreign_key="video.id")
    answer_video_id: Optional[int] = Field(default=None, foreign_key="video.id")

    # Relations pour questions de type matching
    matching_elements: List["MatchingElement"] = Relationship(
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    matching_correct_pairs: List["MatchingCorrectPair"] = Relationship(
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
