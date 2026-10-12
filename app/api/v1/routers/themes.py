from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, status, Query, Path

from app.api.v1.dependencies import (
    get_access_token_from_bearer,
    get_auth_service,
    get_theme_service,
    get_category_service
)
from app.features.authentication.services import AuthService
from app.features.themes.schemas import (
    ThemeCreateIn, 
    ThemeUpdateWithQuestionsIn,
    ThemeJoinOut, 
    ThemeCreateOut, 
    ThemeDetailJoinWithSignedUrlOut,
    ThemeJoinWithSignedUrlOut, 
    CategoryPublicList,  
    ThemePreviewOut
)
from app.features.themes.services import ThemeService, PermissionError, CategoryService

router = APIRouter(
    prefix="/themes",
    tags=["themes"],
    responses={404: {"description": "Not Found"}},
)

# -------- Helpers --------

def _get_user_ctx_or_none(
    access_token: Optional[str],
    auth_svc: AuthService,
) -> Optional[Tuple[int, bool]]:
    if not access_token:
        return None
    user = auth_svc.get_current_user(access_token=access_token)
    return (user.id, getattr(user, "admin", False))

def _enrich_with_signed(
    themes: List[ThemeJoinOut],
    *,
    svc: ThemeService,
    user_ctx: Optional[Tuple[int, bool]],
) -> List[ThemeJoinWithSignedUrlOut]:
    enriched: List[ThemeJoinWithSignedUrlOut] = []
    for t in themes:
        signed = svc._signed_url_for_theme(t, user_ctx)
        enriched.append(
            ThemeJoinWithSignedUrlOut(
                **t.model_dump(),  # type: ignore
                image_signed_url=(signed["url"] if signed else None),
                image_signed_expires_in=(signed["expires_in"] if signed else None),
            )
        )
    return enriched

# -----------------------------
# Public list (no auth)
# -----------------------------
@router.get(
    "/public",
    summary="Lister les thèmes publics",
    response_model=List[ThemeJoinWithSignedUrlOut],
)
def list_public(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    # ready_only: bool = Query(True),
    # validated_only: bool = Query(False),
    category_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None),
    newest_first: bool = Query(True),
    with_signed_url: bool = Query(False),
    svc: ThemeService = Depends(get_theme_service),
):
    themes = svc.list_public(
        offset=offset,
        limit=limit,
        ready_only=True,
        validated_only=True,
        category_id=category_id,
        q=q,
        newest_first=newest_first,
    )

    if not with_signed_url:
        # on “cast” simplement vers le schéma superset
        return [ThemeJoinWithSignedUrlOut(**t.model_dump()) for t in themes]  # type: ignore
    # public: pas d’auth → URL seulement si (public & validé)
    return _enrich_with_signed(themes, svc=svc, user_ctx=None)

@router.get(
    "/categories",
    summary="Lister les catégories (public) avec leur couleur",
    response_model=CategoryPublicList,
)
def list_categories(
    category_svc: CategoryService = Depends(get_category_service),
) -> CategoryPublicList:
    return category_svc.list_public()

# -----------------------------
# List mine (owner)
# -----------------------------
@router.get(
    "/me",
    summary="Lister mes thèmes",
    response_model=List[ThemeJoinWithSignedUrlOut],
)
def list_mine(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    ready_only: bool = Query(False),
    public_only: bool = Query(False),
    validated_only: bool = Query(False),
    category_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None),
    newest_first: bool = Query(True),
    with_signed_url: bool = Query(False, description="Inclure une URL signée si autorisé"),
    access_token: str = Depends(get_access_token_from_bearer),
    auth_svc: AuthService = Depends(get_auth_service),
    svc: ThemeService = Depends(get_theme_service),
):
    user = auth_svc.get_current_user(access_token=access_token)

    themes = svc.list_mine(
        user_id=user.id,
        offset=offset,
        limit=limit,
        ready_only=ready_only,
        public_only=public_only,
        validated_only=validated_only,
        category_id=category_id,
        q=q,
        newest_first=newest_first,
    )
    if not with_signed_url:
        return [ThemeJoinWithSignedUrlOut(**t.model_dump()) for t in themes]  # type: ignore
    # owner: peut obtenir l’URL de ses thèmes
    return _enrich_with_signed(themes, svc=svc, user_ctx=(user.id, getattr(user, "admin", False)))



# -----------------------------
# Admin: list all
# -----------------------------
@router.get(
    "",
    summary="Lister tous les thèmes (admin)",
    response_model=List[ThemeJoinWithSignedUrlOut],
)
def list_all_admin(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    category_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None),
    newest_first: bool = Query(True),
    with_signed_url: bool = Query(False, description="Inclure une URL signée si autorisé"),
    access_token: str = Depends(get_access_token_from_bearer),
    auth_svc: AuthService = Depends(get_auth_service),
    svc: ThemeService = Depends(get_theme_service),
):
    user = auth_svc.get_current_user(access_token=access_token)
    
    if not getattr(user, "admin", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    themes = svc.list_all_as_admin(
        offset=offset,
        limit=limit,
        category_id=category_id,
        q=q,
        newest_first=newest_first,
    )
    if not with_signed_url:
        return [ThemeJoinWithSignedUrlOut(**t.model_dump()) for t in themes]  # type: ignore
    # admin: URL signée pour tous les thèmes
    return _enrich_with_signed(themes, svc=svc, user_ctx=(user.id, True))

# -----------------------------
# Get by id (public/owner/admin)
# -----------------------------
@router.get(
    "/{theme_id}",
    summary="Récupérer un thème et ses questions",
    response_model=ThemeDetailJoinWithSignedUrlOut,
    responses={403: {"description": "Forbidden"}},
)
def get_one(
    theme_id: int = Path(..., ge=1),
    with_signed_url: bool = Query(False),
    access_token: Optional[str] = Depends(get_access_token_from_bearer),  # peut être None si pas d'Authorization
    auth_svc: AuthService = Depends(get_auth_service),
    svc: ThemeService = Depends(get_theme_service),
):
    user_ctx = _get_user_ctx_or_none(access_token, auth_svc) if access_token else None
    try:
        return svc.get_one_detail(theme_id, user_ctx, with_signed_url=with_signed_url)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


@router.get(
    "/{theme_id}/preview",
    summary="Récupérer la preview publique d'un thème (métadonnées + stats)",
    response_model= ThemePreviewOut,
)
def get_preview(
    theme_id: int = Path(..., ge=1),
    with_signed_url: bool = Query(True, description="Inclure l'URL signée de la couverture si possible"),
    comments_offset: int = Query(0, ge=0),
    comments_limit: int = Query(100, ge=1, le=200),
    svc: ThemeService = Depends(get_theme_service),
):
    try:
        return svc.get_preview(
            theme_id,
            with_signed_url=with_signed_url,
            comments_offset=comments_offset,
            comments_limit=comments_limit,
        )
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

# -----------------------------
# Create (owner or admin)
# -----------------------------
@router.post(
    "",
    summary="Créer un thème",
    status_code=status.HTTP_201_CREATED,
    response_model=ThemeCreateOut,
)
def create(
    payload: ThemeCreateIn,
    access_token: str = Depends(get_access_token_from_bearer),
    auth_svc: AuthService = Depends(get_auth_service),
    svc: ThemeService = Depends(get_theme_service),
):
    user = auth_svc.get_current_user(access_token=access_token)
    try:
        return svc.create(payload, user_id=user.id, is_admin=getattr(user, "admin", False))
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


# -----------------------------
# Update (owner or admin)
# -----------------------------
@router.patch(
    "/{theme_id}",
    summary="Mettre à jour un thème (avec ses questions)",
    response_model=ThemeDetailJoinWithSignedUrlOut,
)
def update(
    theme_id: int,
    payload: ThemeUpdateWithQuestionsIn,
    access_token: str = Depends(get_access_token_from_bearer),
    auth_svc: AuthService = Depends(get_auth_service),
    svc: ThemeService = Depends(get_theme_service),
):
    user = auth_svc.get_current_user(access_token=access_token)
    try:
        return svc.update(theme_id, payload, user_id=user.id, is_admin=getattr(user, "admin", False))
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    except ValueError as e:
        # Validation errors from question validation → 422 (Unprocessable Entity)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


# -----------------------------
# Delete (owner or admin) — optionnel
# -----------------------------
@router.delete(
    "/{theme_id}",
    summary="Supprimer un thème",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete(
    theme_id: int,
    access_token: str = Depends(get_access_token_from_bearer),
    auth_svc: AuthService = Depends(get_auth_service),
    svc: ThemeService = Depends(get_theme_service),
):
    user = auth_svc.get_current_user(access_token=access_token)
    try:
        svc.delete(theme_id, user_id=user.id, is_admin=getattr(user, "admin", False))
        return None
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
