from typing import Optional, Sequence, Tuple, List
from sqlmodel import select

from app.db.repositories.themes import ThemeRepository
from app.db.repositories.images import ImageRepository
from app.db.repositories.categories import CategoryRepository
from app.db.repositories.questions import QuestionRepository
from app.db.repositories.grids import GridRepository
from app.db.repositories.players import PlayerRepository

from app.db.models.themes import Theme
from app.db.models.categories import Category
from app.db.models.questions import Question

from app.features.themes.schemas import (
    ThemeCreateIn, ThemeUpdateWithQuestionsIn, 
    CategoryPublic, CategoryPublicList, 
    ThemeJoinWithSignedUrlOut, ThemeDetailJoinWithSignedUrlOut,
    ThemePreviewOut, QuestionStatOut
)
from app.features.questions.schemas import QuestionJoinWithSignedUrlOut
from app.features.comments.schemas import ThemeCommentListOut

from app.features.media.services import ImageService, AudioService, VideoService
from app.features.comments.services import CommentService

class PermissionError(Exception):
    pass

class ThemeService:
    """
    Logique métier / contrôles d'accès pour Theme.
    - Public : lecture des thèmes publics.
    - Owner : CRUD sur ses thèmes.
    - Admin : CRUD sur tous les thèmes, lecture de tout.
    - Vérifie que l'image existe et appartient à l'user (sauf admin) avant create/update.
    - Peut retourner une URL signée optionnelle pour l'image liée.
    """

    def __init__(
        self, 
        repo: ThemeRepository,
        image_repo: ImageRepository,
        image_svc: ImageService,
        audio_svc: AudioService,
        video_svc: VideoService,
        question_repo: QuestionRepository,
        grid_repo: GridRepository,
        player_repo: PlayerRepository,
        comment_service: Optional[CommentService] = None,
    ):
        self.repo = repo
        self.image_repo = image_repo
        self.image_svc = image_svc
        self.audio_svc = audio_svc
        self.video_svc = video_svc
        
        self.question_repo = question_repo
        self.grid_repo = grid_repo
        self.player_repo = player_repo
        self.comment_service = comment_service

    # -------- Helpers permissions --------

    @staticmethod
    def _is_owner(user_id: int, theme: Theme) -> bool:
        return theme.owner_id == user_id

    @staticmethod
    def _is_admin(is_admin: bool) -> bool:
        return bool(is_admin)

    def _assert_can_view(self, user_ctx: Optional[Tuple[int, bool]], theme: Theme) -> None:
        """
        user_ctx: (user_id, is_admin) ou None (public).
        Règles : public ok; owner ok; admin ok; sinon interdit.
        """
        if theme.is_public:
            return
        if user_ctx is None:
            raise PermissionError("Not allowed.")
        user_id, is_admin = user_ctx
        if self._is_admin(is_admin) or self._is_owner(user_id, theme):
            return
        raise PermissionError("Not allowed.")

    def _assert_can_edit(self, user_id: int, is_admin: bool, theme: Theme) -> None:
        if self._is_admin(is_admin) or self._is_owner(user_id, theme):
            return
        raise PermissionError("Not allowed.")

    # -------- vérifs images --------
    def _can_publicly_expose_image(self, image_id: Optional[int]) -> bool:
        if not image_id:
            return False
        return self.repo.image_is_publicly_exposable(image_id)
    
    # -------- vérifs media d'un thème --------
    def _can_sign_media_for_theme(self, theme: Theme, user_ctx: Optional[Tuple[int, bool]]) -> bool:
        """
        Même règle que pour l'image du thème :
        - public + valid_admin => OK sans auth
        - sinon => owner ou admin requis
        """
        if theme.is_public and theme.valid_admin:
            return True
        if user_ctx is None:
            return False
        user_id, is_admin = user_ctx
        return bool(is_admin) or theme.owner_id == user_id
    
    # --- URL signée contrôlée ---
    def _signed_url_for_theme(
        self,
        theme: Theme,
        user_ctx: Optional[Tuple[int, bool]],
    ) -> Optional[dict]:
        """
        Retourne {'url','expires_in'} si autorisé, sinon None.
        Règles:
          - Si (theme.is_public AND theme.valid_admin) => OK sans auth.
          - Sinon: il faut user_ctx ET (admin OU owner du theme).
        """
        if not theme.image_id:
            return None

        if theme.is_public and theme.valid_admin:
            data = self.image_svc.signed_get(str(theme.image_id))
            return {"url": data["url"], "expires_in": data["expires_in"]}

        # sinon auth requise (owner ou admin)
        if user_ctx is None:
            return None
        user_id, is_admin = user_ctx
        if is_admin or theme.owner_id == user_id:
            data = self.image_svc.signed_get(str(theme.image_id))
            return {"url": data["url"], "expires_in": data["expires_in"]}
        return None

    # -------- Reads --------

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
        return self.repo.list_public(
            offset=offset,
            limit=limit,
            ready_only=ready_only,
            validated_only=validated_only,
            category_id=category_id,
            q=q,
            newest_first=newest_first,
        )

    def list_mine(
        self,
        user_id: int,
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
        return self.repo.list_by_owner(
            owner_id=user_id,
            offset=offset,
            limit=limit,
            ready_only=ready_only,
            public_only=public_only,
            validated_only=validated_only,
            category_id=category_id,
            q=q,
            newest_first=newest_first,
        )

    def list_all_as_admin(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        category_id: Optional[int] = None,
        q: Optional[str] = None,
        newest_first: bool = True,
    ) -> Sequence[Theme]:
        # admin: tout voir (simple stratégie = pas de filtre public/ready)
        # fallback SQLModel natif :
        statement = select(Theme)
        if category_id is not None:
            statement = statement.where(Theme.category_id == category_id)
        if q:
            like = f"%{q}%"
            statement = statement.where(Theme.name.ilike(like) | Theme.description.ilike(like))
        if newest_first:
            statement = statement.order_by(Theme.id.desc())
        else:
            statement = statement.order_by(Theme.id.asc())
        statement = statement.offset(offset).limit(limit)
        return self.repo.session.exec(statement).all()

    def get_one(self, theme_id: int, user_ctx: Optional[Tuple[int, bool]]) -> Theme:
        theme = self.repo.get(theme_id)
        if not theme:
            raise LookupError("Theme not found.")
        self._assert_can_view(user_ctx, theme)
        return theme

    # -------- Writes --------

    def create(self, payload: ThemeCreateIn, *, user_id: int, is_admin: bool) -> Theme:
        """
        Crée un thème ET crée 9 questions associées dans la table question.
        Le tout dans une seule transaction (commit unique).

        Admin peut forcer owner_id & valid_admin; owner normal ne peut pas
        """
        owner_id = payload.owner_id if is_admin and payload.owner_id else user_id
        # valid_admin = bool(payload.valid_admin) if is_admin and payload.valid_admin is not None else False
        valid_admin = True # en local

        session = self.repo.session

        try:
            # 1) créer le thème sans commit (flush pour obtenir l'ID)
            created = self.repo.create(
                name=payload.name,
                description=payload.description,
                image_id=payload.image_id,
                category_id=payload.category_id,
                is_public=payload.is_public,
                is_ready=payload.is_ready,
                valid_admin=valid_admin,
                owner_id=owner_id,
                commit=False
            )

            # 2) créer 9 questions associées (valeurs par défaut)
            questions: List[Question] = [
                Question(
                    theme_id=created.id,
                    question=f"Question pour {points} points : Lorem ipsum dolor sit amet, consectetuer adipiscing elit. Maecenas porttitor congue massa ?",
                    answer="Fusce posuere, magna sed pulvinar ultricies.",
                    points=points,
                    question_image_id=None,
                    answer_image_id=None,
                    question_audio_id=None,
                    answer_audio_id=None,
                    question_video_id=None,
                    answer_video_id=None,
                )
                for points in range(2, 11)
            ]
            self.question_repo.create_many(questions, commit=False)

            # 3) commit unique
            session.commit()
            session.refresh(created)

            return created

        except Exception:
            session.rollback()
            raise

    def update(self, theme_id: int, payload: ThemeUpdateWithQuestionsIn, *, user_id: int, is_admin: bool) -> ThemeDetailJoinWithSignedUrlOut:
        theme = self.repo.get(theme_id)
        if not theme:
            raise LookupError("Theme not found.")
        self._assert_can_edit(user_id, is_admin, theme)

        session = self.repo.session

        # --- 1) préparer les changements thème (sans la clé questions) ---
        changes = payload.model_dump(exclude_unset=True)
        questions_in = changes.pop("questions", None)

        # questions obligatoire (selon ton besoin). Si tu veux optionnel, gère None différemment.
        if questions_in is None:
            raise ValueError("Field 'questions' is required.")

        # filtrer champs réservés admin si non-admin
        if not is_admin:
            changes.pop("valid_admin", None)
            changes.pop("owner_id", None)

        # si admin veut changer le owner
        if is_admin and "owner_id" in changes and changes["owner_id"] is None:
            changes.pop("owner_id")

        # --- 2) construire les nouvelles entités Question ---
        new_questions: List[Question] = []
        for idx, q_in in enumerate(payload.questions):
            # q_in est un QuestionUpdateIn (tous champs optionnels) => on impose des minima
            if not q_in.question or not q_in.answer:
                raise ValueError(
                    f"Each question must provide 'question' and 'answer'. Invalid item at index {idx}."
                )

            new_questions.append(
                Question(
                    theme_id=theme_id,
                    question=q_in.question,
                    answer=q_in.answer,
                    points=(q_in.points if q_in.points is not None else 1),
                    question_image_id=q_in.question_image_id,
                    answer_image_id=q_in.answer_image_id,
                    question_audio_id=q_in.question_audio_id,
                    answer_audio_id=q_in.answer_audio_id,
                    question_video_id=q_in.question_video_id,
                    answer_video_id=q_in.answer_video_id,
                )
            )

        # --- 3) transaction globale ---
        try:
            # 3.1 supprimer toutes les questions existantes
            self.question_repo.delete_by_theme(theme_id, commit=False)

            # 3.2 insérer les nouvelles questions
            if new_questions:
                self.question_repo.create_many(new_questions, commit=False)

            # 3.3 update du thème
            self.repo.update(theme, commit=False, **changes)

            # 3.4 commit unique
            session.commit()
            session.refresh(theme)
            return self.get_one_detail(theme_id, user_ctx=(user_id, is_admin), with_signed_url=True)

        except Exception:
            session.rollback()
            raise

    def delete(self, theme_id: int, *, user_id: int, is_admin: bool) -> None:
        theme = self.repo.get(theme_id)
        if not theme:
            return
        self._assert_can_edit(user_id, is_admin, theme)
        self.repo.delete(theme)

    def get_one_detail(
        self,
        theme_id: int,
        user_ctx: Optional[Tuple[int, bool]],
        *,
        with_signed_url: bool,
    ) -> ThemeDetailJoinWithSignedUrlOut:
        # 1) Theme ORM pour permissions
        theme = self.repo.get(theme_id)
        if not theme:
            raise LookupError("Theme not found.")
        self._assert_can_view(user_ctx, theme)

        # 2) projection join (category/color/owner)
        join = self.repo.get_join_by_id(theme_id)
        if not join:
            raise LookupError("Theme not found.")

        # 3) questions
        questions = self.question_repo.list_by_theme(theme_id, offset=0, limit=500, newest_first=False)

        # 4) autorisation de signer
        allow_sign = with_signed_url and self._can_sign_media_for_theme(theme, user_ctx) # probablement overkill mais au cas où on re-vérifie

        # 5) signed url thème image (si demandé et autorisé)
        theme_signed_url = None
        theme_signed_expires = None
        if allow_sign and theme.image_id:
            data = self.image_svc.signed_get(str(theme.image_id))
            theme_signed_url = data.get("url")
            theme_signed_expires = data.get("expires_in")

        # 6) enrichir questions
        q_out: List[QuestionJoinWithSignedUrlOut] = []
        for q in questions:
            # images
            qi_url = qi_exp = ai_url = ai_exp = None
            if allow_sign and q.question_image_id:
                d = self.image_svc.signed_get(str(q.question_image_id))
                qi_url, qi_exp = d.get("url"), d.get("expires_in")
            if allow_sign and q.answer_image_id:
                d = self.image_svc.signed_get(str(q.answer_image_id))
                ai_url, ai_exp = d.get("url"), d.get("expires_in")

            # audios
            qa_url = qa_exp = aa_url = aa_exp = None
            if allow_sign and q.question_audio_id:
                d = self.audio_svc.signed_get(str(q.question_audio_id))
                qa_url, qa_exp = d.get("url"), d.get("expires_in")
            if allow_sign and q.answer_audio_id:
                d = self.audio_svc.signed_get(str(q.answer_audio_id))
                aa_url, aa_exp = d.get("url"), d.get("expires_in")

            # videos
            qv_url = qv_exp = av_url = av_exp = None
            if allow_sign and q.question_video_id:
                d = self.video_svc.signed_get(str(q.question_video_id))
                qv_url, qv_exp = d.get("url"), d.get("expires_in")
            if allow_sign and q.answer_video_id:
                d = self.video_svc.signed_get(str(q.answer_video_id))
                av_url, av_exp = d.get("url"), d.get("expires_in")

            # stats
            pos = neg = cancelled = 0
            if self.grid_repo:
                try:
                    stats = self.grid_repo.count_stats_for_question(q.id)
                    pos = int(stats.get("positive", 0))
                    neg = int(stats.get("negative", 0))
                    cancelled = int(stats.get("cancelled", 0))
                except Exception:
                    # ne doit pas empêcher la réponse principale
                    pos = neg = cancelled = 0

            q_out.append(
                QuestionJoinWithSignedUrlOut(
                    id=q.id,
                    theme_id=q.theme_id,
                    question=q.question,
                    answer=q.answer,
                    points=q.points,
                    question_image_id=q.question_image_id,
                    answer_image_id=q.answer_image_id,
                    question_audio_id=q.question_audio_id,
                    answer_audio_id=q.answer_audio_id,
                    question_video_id=q.question_video_id,
                    answer_video_id=q.answer_video_id,

                    question_image_signed_url=qi_url,
                    question_image_signed_expires_in=qi_exp,
                    answer_image_signed_url=ai_url,
                    answer_image_signed_expires_in=ai_exp,

                    question_audio_signed_url=qa_url,
                    question_audio_signed_expires_in=qa_exp,
                    answer_audio_signed_url=aa_url,
                    answer_audio_signed_expires_in=aa_exp,

                    question_video_signed_url=qv_url,
                    question_video_signed_expires_in=qv_exp,
                    answer_video_signed_url=av_url,
                    answer_video_signed_expires_in=av_exp,

                    created_at=getattr(q, "created_at", None),
                    updated_at=getattr(q, "updated_at", None),
                    positive_answers_count=pos,
                    negative_answers_count=neg,
                    cancelled_answers_count=cancelled,
                )
            )

        # 7) construire retour ThemeJoinWithSignedUrlOut + questions
        base = ThemeJoinWithSignedUrlOut(
            **join.model_dump(),  # type: ignore
            image_signed_url=theme_signed_url,
            image_signed_expires_in=theme_signed_expires,
        )

        return ThemeDetailJoinWithSignedUrlOut(
            **base.model_dump(),  # type: ignore
            questions=q_out,
        )

    def get_preview(
        self,
        theme_id: int,
        *,
        with_signed_url: bool,
        comments_offset: int = 0,
        comments_limit: int = 100,
    ) -> "ThemePreviewOut":
        """Retourne les informations de preview publiques d'un thème :
        - métadonnées (owner, category, dates)
        - URL signée de la couverture si autorisé (public + valid_admin)
        - nombre de parties où le thème a été joué
        - statistiques par question (counts) **sans** renvoyer le contenu des questions
        """
        # 1) Theme ORM pour permissions / existence
        theme = self.repo.get(theme_id)
        if not theme:
            raise LookupError("Theme not found.")

        # Seules les thèmes publics sont exposés par cette route publique
        if not getattr(theme, "is_public", False):
            raise PermissionError("Not allowed.")

        # 2) projection join (category/color/owner)
        join = self.repo.get_join_by_id(theme_id)
        if not join:
            raise LookupError("Theme not found.")

        # 3) signed url (public route -> only allowed if theme.is_public and valid_admin)
        image_signed = self._signed_url_for_theme(theme, None) if with_signed_url else None
        image_signed_url = image_signed["url"] if image_signed else None
        image_signed_expires = image_signed["expires_in"] if image_signed else None

        # 4) plays count (distinct games where a question of the theme was played)
        plays = 0
        if self.player_repo:
            try:
                plays = int(self.player_repo.count_plays_for_theme(theme_id))
            except Exception:
                plays = 0

        # 5) question stats (id + counts) — sans contenu
        q_rows = self.question_repo.list_by_theme(theme_id, offset=0, limit=500, newest_first=False)
        q_stats = []
        for q in q_rows:
            pos = neg = cancelled = 0
            if self.grid_repo:
                try:
                    stats = self.grid_repo.count_stats_for_question(q.id)
                    pos = int(stats.get("positive", 0))
                    neg = int(stats.get("negative", 0))
                    cancelled = int(stats.get("cancelled", 0))
                except Exception:
                    pos = neg = cancelled = 0

            q_stats.append(
                {
                    "question_id": q.id,
                    "points": int(getattr(q, "points", 0)),
                    "positive_answers_count": pos,
                    "negative_answers_count": neg,
                    "cancelled_answers_count": cancelled,
                }
            )

        # 6) commentaires + stats agrégées
        comments_out = None
        if self.comment_service:
            try:
                comments_out, _, _ = self.comment_service.list_for_theme_with_stats(
                    theme_id,
                    offset=comments_offset,
                    limit=comments_limit,
                )
            except Exception:
                comments_out = None

        # 7) construire sortie
        # On met à jour plays_count avec la valeur calculée
        join_data = join.model_dump()
        join_data["plays_count"] = plays
        
        base = ThemePreviewOut(
            **join_data,  # type: ignore
            image_signed_url=image_signed_url,
            image_signed_expires_in=image_signed_expires,
            question_stats=[QuestionStatOut(**qs) for qs in q_stats],
            comments=(comments_out if comments_out else None)
            or ThemeCommentListOut(items=[], total=0),
        )

        return base

class CategoryService:
    """
    Service métier pour Category.
    - Ne fait PAS d'accès DB direct : passe par CategoryRepository.
    - Fournit les helpers nécessaires aux autres services (ex: ThemeService).
    """

    def __init__(self, repo: CategoryRepository):
        self.repo = repo

    def get_one(self, category_id: int) -> Optional[Category]:
        return self.repo.get(category_id)

    def assert_exists(self, category_id: Optional[int]) -> None:
        if category_id is None:
            return
        if not self.get_one(category_id):
            raise LookupError("Category not found.")
        
    def list_public(self) -> CategoryPublicList:
        """
        Retourne la liste des catégories avec la couleur normalisée en hexa (#RRGGBB).
        """
        rows = self.repo.list_with_colors(order_by_name=True)

        items = []
        for category_id, category_name, hex_code in rows:
            items.append(
                CategoryPublic(
                    id=category_id,
                    name=category_name,
                    color=hex_code,
                )
            )

        return CategoryPublicList(items=items)