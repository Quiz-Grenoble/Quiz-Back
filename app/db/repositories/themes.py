# app/db/repositories/themes.py
from typing import Optional, Sequence
from sqlmodel import select, or_, func

from app.db.repositories.base import BaseRepository
from app.db.models.themes import Theme
from app.db.models.users import User
from app.db.models.categories import Category
from app.db.models.colors import Color
from app.db.models.questions import Question
from app.db.models.comments import ThemeComment

from app.features.themes.schemas import ThemeJoinOut

class ThemeRepository(BaseRepository[Theme]):
    """CRUD Themes + requêtes spécifiques."""
    model = Theme

    # ---------- HELPERS ----------

    def _select_theme_out(self):
        """Projection SQL standardisée pour construire ThemeOut avec score moyen des commentaires."""
        stmt = (
            select(
                Theme.id,
                Theme.name,
                Theme.description,
                Theme.image_id,
                Theme.category_id,
                Category.name.label("category_name"),
                Color.hex_code.label("category_color_hex"),
                Theme.owner_id,
                User.username.label("owner_username"),
                Theme.is_public,
                Theme.is_ready,
                Theme.valid_admin,
                Theme.created_at,
                Theme.updated_at,
                func.count(func.distinct(Question.id)).label("questions_count"),
                func.avg(ThemeComment.score).label("score_avg"),
                func.count(func.distinct(ThemeComment.id)).label("score_count"),
            )
            .select_from(Theme)
            .join(User, User.id == Theme.owner_id)
            .join(Category, Category.id == Theme.category_id, isouter=True)
            .join(Color, Color.id == Category.color_id, isouter=True)
            .outerjoin(Question, Question.theme_id == Theme.id)
            .outerjoin(ThemeComment, ThemeComment.theme_id == Theme.id)
            .group_by(
                Theme.id,
                Theme.name,
                Theme.description,
                Theme.image_id,
                Theme.category_id,
                Category.name,
                Color.hex_code,
                Theme.owner_id,
                User.username,
                Theme.is_public,
                Theme.is_ready,
                Theme.valid_admin,
                Theme.created_at,
                Theme.updated_at,
            )
        )
        return stmt

    def _rows_to_theme_out(self, rows) -> list[ThemeJoinOut]:
        return [ThemeJoinOut(**dict(r._mapping)) for r in rows]

    # ---------- GETTERS SPÉCIFIQUES ----------

    def get_by_name(self, name: str, owner_id: Optional[int] = None) -> Optional[Theme]:
        """
        Retourne un thème par son nom.
        Si owner_id est fourni, restreint la recherche au propriétaire.
        """
        stmt = select(self.model).where(self.model.name == name)
        if owner_id is not None:
            stmt = stmt.where(self.model.owner_id == owner_id)
        return self.session.exec(stmt).first()

    def get_by_image(self, image_id: int) -> Optional[Theme]:
        """Retourne un thème par son image_id (FK)."""
        stmt = select(self.model).where(self.model.image_id == image_id)
        return self.session.exec(stmt).first()

    # ---------- LISTES / RECHERCHE ----------

    def list_by_owner(
        self,
        owner_id: int,
        *,
        offset: int = 0,
        limit: int = 100,
        ready_only: bool = False,
        public_only: bool = False,
        validated_only: bool = False,
        category_id: Optional[int] = None,
        q: Optional[str] = None,
        newest_first: bool = True,
    ) -> Sequence[Theme]:
        """
        Liste paginée des thèmes d'un propriétaire avec filtres optionnels.
        - ready_only     : limite aux thèmes prêts
        - public_only    : limite aux thèmes publics
        - validated_only : limite aux thèmes validés admin
        - category_id    : filtre par catégorie
        - q              : recherche insensible à la casse sur name/description
        """
        stmt = self._select_theme_out().where(Theme.owner_id == owner_id)

        if ready_only:
            stmt = stmt.where(self.model.is_ready.is_(True))
        if public_only:
            stmt = stmt.where(self.model.is_public.is_(True))
        if validated_only:
            stmt = stmt.where(self.model.valid_admin.is_(True))
        if category_id is not None:
            stmt = stmt.where(self.model.category_id == category_id)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(self.model.name.ilike(like), self.model.description.ilike(like))
            )

        if newest_first:
            # en supposant que BaseModelDB fournit created_at/id
            stmt = stmt.order_by(self.model.id.desc())
        else:
            stmt = stmt.order_by(self.model.id.asc())

        stmt = stmt.offset(offset).limit(limit)
        
        rows = self.session.exec(stmt).all()
        return self._rows_to_theme_out(rows)

    def list_public(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        ready_only: bool = True,
        validated_only: bool = False,
        category_id: Optional[int] = None,
        q: Optional[str] = None,
        newest_first: bool = True,
    ) -> Sequence[Theme]:
        """
        Liste paginée des thèmes publics avec filtres optionnels.
        - ready_only     : True par défaut pour ne montrer que les thèmes prêts
        - validated_only : si True, ne retourne que les thèmes validés admin
        - category_id    : filtre par catégorie
        - q              : recherche insensible à la casse sur name/description
        """
        stmt = self._select_theme_out().where(Theme.is_public.is_(True))

        if ready_only:
            stmt = stmt.where(self.model.is_ready.is_(True))
        if validated_only:
            stmt = stmt.where(self.model.valid_admin.is_(True))
        if category_id is not None:
            stmt = stmt.where(self.model.category_id == category_id)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(self.model.name.ilike(like), self.model.description.ilike(like))
            )

        if newest_first:
            stmt = stmt.order_by(self.model.id.desc())
        else:
            stmt = stmt.order_by(self.model.id.asc())

        stmt = stmt.offset(offset).limit(limit)

        rows = self.session.exec(stmt).all()

        rows = self.session.exec(stmt).all()
        return self._rows_to_theme_out(rows)

    def list_by_category(
        self,
        category_id: int,
        *,
        offset: int = 0,
        limit: int = 100,
        only_public: bool = False,
        only_ready: bool = False,
        newest_first: bool = True,
    ) -> Sequence[Theme]:
        """Liste des thèmes d'une catégorie, avec filtres simples."""
        stmt = self._select_theme_out().where(Theme.category_id == category_id)

        if only_public:
            stmt = stmt.where(self.model.is_public.is_(True))
        if only_ready:
            stmt = stmt.where(self.model.is_ready.is_(True))

        if newest_first:
            stmt = stmt.order_by(self.model.id.desc())
        else:
            stmt = stmt.order_by(self.model.id.asc())

        stmt = stmt.offset(offset).limit(limit)
        
        rows = self.session.exec(stmt).all()
        return self._rows_to_theme_out(rows)

    # ---------- EXISTENCE / COMPTEURS ----------

    def exists_name_for_owner(self, name: str, owner_id: int) -> bool:
        """Vérifie l'existence d'un nom de thème pour un propriétaire donné."""
        stmt = select(func.count(self.model.id)).where(
            self.model.name == name, self.model.owner_id == owner_id
        )
        return self.session.exec(stmt).one() > 0

    def count_public(self, *, ready_only: bool = True, category_id: Optional[int] = None) -> int:
        """Compte les thèmes publics (optionnellement prêts et/ou par catégorie)."""
        stmt = select(func.count(self.model.id)).where(self.model.is_public.is_(True))
        if ready_only:
            stmt = stmt.where(self.model.is_ready.is_(True))
        if category_id is not None:
            stmt = stmt.where(self.model.category_id == category_id)
        return self.session.exec(stmt).one()
    
    def image_is_publicly_exposable(self, image_id: int) -> bool:
        """
        True si l'image est liée à AU MOINS un thème public ET validé par un admin.
        """
        stmt = select(self.model.id).where(
            self.model.image_id == image_id,
            self.model.is_public.is_(True),
            self.model.valid_admin.is_(True),
        ).limit(1)
        return self.session.exec(stmt).first() is not None
    
    def get_join_by_id(self, theme_id: int) -> Optional[ThemeJoinOut]:
        stmt = self._select_theme_out().where(Theme.id == theme_id).limit(1)
        row = self.session.exec(stmt).first()
        if not row:
            return None
        return ThemeJoinOut(**dict(row._mapping))