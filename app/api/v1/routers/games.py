from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, status, Query, Path

from app.api.v1.dependencies import (
    get_access_token_from_bearer,
    get_auth_service,
    get_game_service,
    get_question_service,
)
from app.features.authentication.services import AuthService
from app.features.games.schemas import (
    JokerPublicOut,
    BonusPublicOut,
    GameCreateIn,
    GameCreateOut,
    GameWithPlayersOut,
    GameStateOut,
    RoundCreateIn,
    RoundCreateOut,
    AnswerCreateIn,
    AnswerCreateOut,
    JokerUseIn,
    JokerUseOut,
    ColorPublicOut,
    GameSetupSuggestOut,
    GameSetupSuggestIn,
    GameResultsOut,
)
from app.features.games.services import GameService, PermissionError, ConflictError
from app.features.questions.services import QuestionService
from app.features.questions.schemas import QuestionJoinWithSignedUrlOut


router = APIRouter(
    prefix="/games",
    tags=["games"],
    responses={404: {"description": "Not Found"}},
)

# -------- Helpers --------

def _get_user_ctx(
    access_token: str,
    auth_svc: AuthService,
) -> Tuple[int, bool]:
    user = auth_svc.get_current_user(access_token=access_token)
    return (user.id, getattr(user, "admin", False))

# -----------------------------
# Catalogues (public)
# -----------------------------
@router.get(
    "/jokers",
    summary="Lister tous les jokers",
    response_model=List[JokerPublicOut],
)
def list_jokers(
    svc: GameService = Depends(get_game_service),
):
    return svc.list_all_jokers()

@router.get(
    "/bonus",
    summary="Lister tous les bonus",
    response_model=List[BonusPublicOut],
)
def list_bonus(
    svc: GameService = Depends(get_game_service),
):
    return svc.list_all_bonus()

@router.get(
    "/colors",
    summary="Lister toutes les couleurs (public) avec leur hex_code",
    response_model=List[ColorPublicOut],
)
def list_colors_public(
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    svc: GameService = Depends(get_game_service),
):
    return svc.list_public_colors(offset=offset, limit=limit)

# -----------------------------
# List mine
# -----------------------------
@router.get(
    "/me",
    summary="Lister mes parties avec joueurs/couleurs/thèmes",
    response_model=List[GameWithPlayersOut],
)
def list_mine(
    access_token: str = Depends(get_access_token_from_bearer),
    auth_svc: AuthService = Depends(get_auth_service),
    svc: GameService = Depends(get_game_service),
):
    user_id, _is_admin = _get_user_ctx(access_token, auth_svc)
    return svc.list_user_games_with_players(owner_id=user_id)

# -----------------------------
# Create game (owner)
# -----------------------------
@router.post(
    "",
    summary="Créer une partie",
    status_code=status.HTTP_201_CREATED,
    response_model=GameCreateOut,
)
def create_game(
    payload: GameCreateIn,
    access_token: str = Depends(get_access_token_from_bearer),
    auth_svc: AuthService = Depends(get_auth_service),
    svc: GameService = Depends(get_game_service),
):
    user_id, _is_admin = _get_user_ctx(access_token, auth_svc)
    try:
        game = svc.create_game(payload, owner_id=user_id)
        return GameCreateOut(
            id=game.id,
            url=game.url,
            seed=game.seed,
            rows_number=game.rows_number,
            columns_number=game.columns_number,
            finished=game.finished,
            with_pawns=game.with_pawns,
        )
    except ConflictError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Game URL already exists")

# -----------------------------
# Game state
# -----------------------------
@router.get(
    "/{game_url}/state",
    summary="Récupérer l'état complet d'une partie",
    response_model=GameStateOut,
    responses={403: {"description": "Forbidden"}},
)
def get_state(
    game_url: str = Path(..., min_length=3, max_length=120),
    access_token: str = Depends(get_access_token_from_bearer),
    auth_svc: AuthService = Depends(get_auth_service),
    svc: GameService = Depends(get_game_service),
):
    user_id, is_admin = _get_user_ctx(access_token, auth_svc)
    try:
        return svc.get_game_state(game_url, user_id=user_id, is_admin=is_admin)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

# -----------------------------
# Joker usage (séparé du process Answer)
# -----------------------------
@router.post(
    "/{game_url}/jokers/use",
    summary="Utiliser un joker pendant un tour",
    status_code=status.HTTP_201_CREATED,
    response_model=JokerUseOut,
    responses={403: {"description": "Forbidden"}},
)
def use_joker(
    game_url: str = Path(..., min_length=3, max_length=120),
    payload: JokerUseIn = ...,
    access_token: str = Depends(get_access_token_from_bearer),
    auth_svc: AuthService = Depends(get_auth_service),
    svc: GameService = Depends(get_game_service),
):
    user_id, is_admin = _get_user_ctx(access_token, auth_svc)
    try:
        usage = svc.use_joker(game_url, payload, user_id=user_id, is_admin=is_admin)
        return JokerUseOut(
            id=usage.id,
            joker_in_game_id=usage.joker_in_game_id,
            round_id=usage.round_id,
            target_player_id=usage.target_player_id,
            target_grid_id=usage.target_grid_id,
        )
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    except ConflictError as e:
        # ex: joker déjà utilisé / non dispo
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

# -----------------------------
# Answer (process séparé) + auto next round
# -----------------------------
@router.post(
    "/{game_url}/answers",
    summary="Enregistrer une réponse (case de grille)",
    status_code=status.HTTP_201_CREATED,
    response_model=AnswerCreateOut,
    responses={403: {"description": "Forbidden"}},
)
def answer(
    game_url: str = Path(..., min_length=3, max_length=120),
    payload: AnswerCreateIn = ...,
    auto_next_round: bool = Query(
        True,
        description="Si true, crée automatiquement le round suivant après la réponse (si applicable)",
    ),
    access_token: str = Depends(get_access_token_from_bearer),
    auth_svc: AuthService = Depends(get_auth_service),
    svc: GameService = Depends(get_game_service),
):
    user_id, is_admin = _get_user_ctx(access_token, auth_svc)
    try:
        grid, next_round = svc.answer_question(
            game_url,
            payload,
            user_id=user_id,
            is_admin=is_admin,
            auto_next_round=auto_next_round,
        )
        return AnswerCreateOut(
            grid_id=grid.id,
            round_id=grid.round_id,
            correct_answer=grid.correct_answer,
            skip_answer=grid.skip_answer,
            next_round=(
                RoundCreateOut(id=next_round.id, player_id=next_round.player_id, round_number=next_round.round_number)
                if next_round
                else None
            ),
        )
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post(
    "/suggest-setup",
    summary="Suggérer des paramètres de partie",
    response_model=GameSetupSuggestOut,
)
def suggest_setup(
    payload: GameSetupSuggestIn,
    access_token: str = Depends(get_access_token_from_bearer),
    auth_svc: AuthService = Depends(get_auth_service),
    svc: GameService = Depends(get_game_service),
):
    user_id, _is_admin = _get_user_ctx(access_token, auth_svc)
    return svc.suggest_setup(payload)

@router.get(
    "/questions/{question_id}",
    summary="Récupérer une question par ID (avec signed URLs si autorisé)",
    response_model=QuestionJoinWithSignedUrlOut,
    status_code=status.HTTP_200_OK,
)
def get_question_by_id(
    question_id: int,
    with_signed_url: bool = Query(
        False,
        description="Si true, inclut des signed URLs si l'utilisateur est autorisé",
    ),
    access_token: str = Depends(get_access_token_from_bearer),
    auth_svc: AuthService = Depends(get_auth_service),
    svc: QuestionService = Depends(get_question_service),
):
    # 🔐 Auth obligatoire (même pattern que create_game)
    user_id, is_admin = _get_user_ctx(access_token, auth_svc)
    user_ctx = (user_id, is_admin)

    try:
        return svc.get_one_detail(question_id, user_ctx, with_signed_url=with_signed_url)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

@router.get(
    "/{game_url}/results",
    summary="Récupérer les résultats et l'historique d'une partie",
    response_model=GameResultsOut,
    responses={403: {"description": "Forbidden"}},
)
def get_results(
    game_url: str = Path(..., min_length=3, max_length=120),
    access_token: str = Depends(get_access_token_from_bearer),
    auth_svc: AuthService = Depends(get_auth_service),
    svc: GameService = Depends(get_game_service),
):
    user_id, is_admin = _get_user_ctx(access_token, auth_svc)
    try:
        return svc.get_game_results(game_url, user_id=user_id, is_admin=is_admin)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")