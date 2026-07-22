from typing import Optional, Sequence, Tuple, Any, Dict

from app.db.repositories.questions import QuestionRepository
from app.db.repositories.themes import ThemeRepository
from app.db.repositories.grids import GridRepository
from app.db.repositories.games import GameRepository
from app.db.repositories.matching_elements import MatchingElementRepository
from app.db.repositories.matching_correct_pairs import MatchingCorrectPairRepository

from app.db.models.questions import Question
from app.db.models.matching_elements import MatchingElement
from app.db.models.matching_correct_pairs import MatchingCorrectPair

from app.features.questions.schemas import (
    QuestionCreateIn,
    QuestionUpdateIn,
    QuestionJoinWithSignedUrlOut,
    MatchingElementWithSignedUrlOut,
)

from app.features.media.services import ImageService, AudioService, VideoService


class QuestionService:
    """
    Service métier Questions.
    """

    def __init__(
        self,
        repo: QuestionRepository,
        theme_repo: ThemeRepository,
        image_svc: ImageService,
        audio_svc: AudioService,
        video_svc: VideoService,
        grid_repo: GridRepository,
        game_repo: GameRepository,
        matching_element_repo: MatchingElementRepository,
        matching_correct_pair_repo: MatchingCorrectPairRepository,
    ):
        self.repo = repo
        self.theme_repo = theme_repo
        self.image_svc = image_svc
        self.audio_svc = audio_svc
        self.video_svc = video_svc
        self.grid_repo = grid_repo
        self.game_repo = game_repo
        self.matching_element_repo = matching_element_repo
        self.matching_correct_pair_repo = matching_correct_pair_repo

    def create(self, payload: QuestionCreateIn) -> Question:
        """
        Crée une question (classic ou matching).
        Pour les questions matching, crée aussi les éléments et paires associés.
        """
        # Extraire les champs matching avant de créer la question
        matching_elements_data = payload.matching_elements
        matching_correct_pairs_data = payload.matching_correct_pairs
        
        # Créer la question (exclure les champs matching du dump)
        question_data = payload.model_dump(exclude={"matching_elements", "matching_correct_pairs"})
        question = self.repo.create(**question_data, commit=False)
        
        # Si question de type matching, créer les éléments et paires
        if payload.question_type == "matching" and matching_elements_data and matching_correct_pairs_data:
            # Créer les éléments
            elements = [
                MatchingElement(
                    question_id=question.id,
                    list_index=elem.list_index,
                    position=elem.position,
                    text=elem.text,
                    media_id=elem.media_id,
                    media_type=elem.media_type,
                )
                for elem in matching_elements_data
            ]
            self.matching_element_repo.create_many(elements, commit=False)
            
            # Créer les paires correctes
            pairs = [
                MatchingCorrectPair(
                    question_id=question.id,
                    list_index_1=pair.list_index_1,
                    element_position_1=pair.element_position_1,
                    list_index_2=pair.list_index_2,
                    element_position_2=pair.element_position_2,
                )
                for pair in matching_correct_pairs_data
            ]
            self.matching_correct_pair_repo.create_many(pairs, commit=False)
        
        # Commit toutes les opérations
        self.repo.session.commit()
        self.repo.session.refresh(question)
        
        return question

    def get_one(self, question_id: int) -> Optional[Question]:
        return self.repo.get(question_id)

    def list_by_theme(
        self,
        theme_id: int,
        *,
        offset: int = 0,
        limit: int = 100,
        newest_first: bool = True,
    ) -> Sequence[Question]:
        return self.repo.list_by_theme(theme_id, offset=offset, limit=limit, newest_first=newest_first)

    def update(self, question_id: int, payload: QuestionUpdateIn) -> Question:
        """
        Met à jour une question.
        Si les champs matching sont fournis, remplace les éléments/paires existants.
        """
        q = self.repo.get(question_id)
        if not q:
            raise LookupError("Question not found.")
        
        # Extraire les données matching
        matching_elements_data = payload.matching_elements
        matching_correct_pairs_data = payload.matching_correct_pairs
        
        # Mettre à jour les champs de base (exclure matching)
        changes = payload.model_dump(exclude_unset=True, exclude={"matching_elements", "matching_correct_pairs"})
        q = self.repo.update(q, **changes, commit=False)
        
        # Si les données matching sont fournies, remplacer les éléments/paires existants
        if matching_elements_data is not None:
            # Supprimer les anciens éléments
            self.matching_element_repo.delete_by_question(question_id, commit=False)
            
            # Créer les nouveaux éléments
            if matching_elements_data:
                elements = [
                    MatchingElement(
                        question_id=question_id,
                        list_index=elem.list_index,
                        position=elem.position,
                        text=elem.text,
                        media_id=elem.media_id,
                        media_type=elem.media_type,
                    )
                    for elem in matching_elements_data
                ]
                self.matching_element_repo.create_many(elements, commit=False)
        
        if matching_correct_pairs_data is not None:
            # Supprimer les anciennes paires
            self.matching_correct_pair_repo.delete_by_question(question_id, commit=False)
            
            # Créer les nouvelles paires
            if matching_correct_pairs_data:
                pairs = [
                    MatchingCorrectPair(
                        question_id=question_id,
                        list_index_1=pair.list_index_1,
                        element_position_1=pair.element_position_1,
                        list_index_2=pair.list_index_2,
                        element_position_2=pair.element_position_2,
                    )
                    for pair in matching_correct_pairs_data
                ]
                self.matching_correct_pair_repo.create_many(pairs, commit=False)
        
        # Commit toutes les opérations
        self.repo.session.commit()
        self.repo.session.refresh(q)
        
        return q

    def delete(self, question_id: int) -> None:
        q = self.repo.get(question_id)
        if not q:
            return
        self.repo.delete(q)

    # ---------------------------------------------------------------------
    # Détails enrichis + signed URLs
    # ---------------------------------------------------------------------

    def _assert_can_view(self, user_ctx: Optional[Tuple[int, bool]], theme: Any) -> None:
        """
        IMPORTANT: adapte cette logique à celle déjà utilisée côté ThemeService.
        Ici version "safe" : si thème privé => owner/admin.
        """
        # si ton modèle Theme n'a pas ces champs, remplace par tes règles existantes
        is_public = getattr(theme, "is_public", True)
        if is_public:
            return

        if not user_ctx:
            raise PermissionError("UNAUTHENTICATED")

        user_id, is_admin = user_ctx
        if is_admin:
            return

        owner_id = getattr(theme, "owner_id", None)
        if owner_id != user_id:
            raise PermissionError("FORBIDDEN")

    def _can_sign_media_for_theme(
        self, theme: Any, user_ctx: Optional[Tuple[int, bool]], game_url: Optional[str] = None
    ) -> bool:
        """
        Vérifie si l'utilisateur peut signer les URLs des médias.
        - Si game_url fourni, autorise si user est owner de cette partie
        - Sinon, autorise si user est owner du thème ou admin
        """
        if not user_ctx:
            return False
        user_id, is_admin = user_ctx
        if is_admin:
            return True
        
        # Si game_url fourni, vérifier si user est owner de cette game
        if game_url:
            game = self.game_repo.get_by_url(game_url)
            if game and (game.owner_id == user_id or is_admin):
                return True
        
        # Fallback: vérifier ownership du thème
        owner_id = getattr(theme, "owner_id", None)
        return owner_id == user_id

    def get_one_detail(
        self,
        question_id: int,
        user_ctx: Optional[Tuple[int, bool]],
        *,
        with_signed_url: bool,
        game_url: Optional[str] = None,
    ) -> QuestionJoinWithSignedUrlOut:
        # 1) question
        q = self.repo.get(question_id)
        if not q:
            raise LookupError("Question not found.")

        # 2) theme pour permissions
        theme = self.theme_repo.get(q.theme_id)
        if not theme:
            raise LookupError("Theme not found.")
        self._assert_can_view(user_ctx, theme)

        # 3) autorisation de signer (avec game_url si fourni)
        allow_sign = with_signed_url and self._can_sign_media_for_theme(
            theme, user_ctx, game_url=game_url
        )

        # 4) signed urls (si demandé et autorisé)
        # images
        qi_url = qi_exp = ai_url = ai_exp = None
        if allow_sign and q.question_image_id:
            d: Dict[str, Any] = self.image_svc.signed_get(str(q.question_image_id))
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

        # 5) Récupérer les éléments et paires matching (si question de type matching)
        matching_elements_out = []
        matching_correct_pairs_out = []
        
        if q.question_type == "matching":
            # Récupérer les éléments
            elements = self.matching_element_repo.list_by_question(question_id)
            
            # Pour chaque élément, générer signed URL si média présent
            for elem in elements:
                media_url = media_exp = None
                
                if allow_sign and elem.media_id and elem.media_type:
                    if elem.media_type == "image":
                        d = self.image_svc.signed_get(str(elem.media_id))
                    elif elem.media_type == "audio":
                        d = self.audio_svc.signed_get(str(elem.media_id))
                    elif elem.media_type == "video":
                        d = self.video_svc.signed_get(str(elem.media_id))
                    else:
                        d = {}
                    
                    media_url = d.get("url")
                    media_exp = d.get("expires_in")
                
                matching_elements_out.append(
                    MatchingElementWithSignedUrlOut(
                        id=elem.id,
                        question_id=elem.question_id,
                        list_index=elem.list_index,
                        position=elem.position,
                        text=elem.text,
                        media_id=elem.media_id,
                        media_type=elem.media_type,
                        media_signed_url=media_url,
                        media_signed_expires_in=media_exp,
                        created_at=getattr(elem, "created_at", None),
                        updated_at=getattr(elem, "updated_at", None),
                    )
                )
            
            # Récupérer les paires correctes
            from app.features.questions.schemas import MatchingCorrectPairOut
            pairs = self.matching_correct_pair_repo.list_by_question(question_id)
            matching_correct_pairs_out = [
                MatchingCorrectPairOut(
                    id=pair.id,
                    question_id=pair.question_id,
                    list_index_1=pair.list_index_1,
                    element_position_1=pair.element_position_1,
                    list_index_2=pair.list_index_2,
                    element_position_2=pair.element_position_2,
                    created_at=getattr(pair, "created_at", None),
                    updated_at=getattr(pair, "updated_at", None),
                )
                for pair in pairs
            ]

        # 6) statistiques d'usage (si disponible)
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

        return QuestionJoinWithSignedUrlOut(
            id=q.id,
            theme_id=q.theme_id,
            question=q.question,
            answer=q.answer,
            points=q.points,
            question_type=q.question_type,

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

            matching_elements=matching_elements_out,
            matching_correct_pairs=matching_correct_pairs_out,

            created_at=getattr(q, "created_at", None),
            updated_at=getattr(q, "updated_at", None),
            positive_answers_count=pos,
            negative_answers_count=neg,
            cancelled_answers_count=cancelled,
        )
