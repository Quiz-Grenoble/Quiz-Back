"""
➡️ But : Configurer la base SQLite et gérer les sessions de base de données.

engine : connexion à la base SQLite (sqlite:///app.db).

init_db() : crée les tables à partir des modèles SQLModel.

get_session() : dépendance FastAPI qui ouvre une session, la fournit aux routes, puis la ferme proprement.

🔹 Avantages :

Un seul endroit pour gérer les connexions DB.

Réutilisable par injection (Depends(get_session)).
"""

from typing import Dict, Any
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.engine import Engine

# Import all models for creating all tables
from app.db.models.users import User
from app.db.models.images import Image
from app.db.models.audios import Audio
from app.db.models.videos import Video
from app.db.models.colors import Color
from app.db.models.categories import Category
from app.db.models.refresh_tokens import RefreshToken
from app.db.models.themes import Theme
from app.db.models.questions import Question
from app.db.models.matching_elements import MatchingElement
from app.db.models.matching_correct_pairs import MatchingCorrectPair
from app.db.models.comments import ThemeComment

from app.db.models.games import Game
from app.db.models.players import Player
from app.db.models.rounds import Round
from app.db.models.grids import Grid
from app.db.models.jokers import Joker
from app.db.models.jokers_in_games import JokerInGame
from app.db.models.jokers_used_in_games import JokerUsedInGame
from app.db.models.bonus import Bonus
from app.db.models.bonus_in_games import BonusInGame

from app.core.config import settings

def _build_engine() -> Engine:
    url = settings.DATABASE_URL
    assert url, "DATABASE_URL must be set"

    is_sqlite = url.startswith("sqlite:")

    connect_args: Dict[str, Any] = {}
    if is_sqlite:
        # Requis pour SQLite quand utilisé dans un app serveur (multi-threads)
        connect_args["check_same_thread"] = False

    # echo seulement en dev pour ne pas polluer les logs en prod
    engine = create_engine(
        url,
        echo=(settings.ENV == "dev"),
        connect_args=connect_args,
        pool_pre_ping=not is_sqlite,  # ping utile pour Postgres/MySQL ; inutile pour SQLite
    )
    return engine

engine: Engine = _build_engine()

def init_db() -> None:
    """
    Crée les tables si elles n'existent pas (usage dev/demo).
    En prod avec Alembic, préfère des migrations.
    """
    SQLModel.metadata.create_all(engine)


def get_session():
    """
    Dépendance FastAPI : fournit une session par requête.
    Utilisation :
        def route(..., session: Session = Depends(get_session)):
            ...
    """
    with Session(engine) as session:
        yield session