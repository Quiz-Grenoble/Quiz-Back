import hashlib
import datetime
from typing import Optional, Tuple, Set
import filetype


# Allow-lists (ajuste selon tes besoins)
ALLOWED_IMAGE_MIME: Set[str] = {"image/jpeg", "image/png", "image/webp", "image/avif", "image/gif"}

ALLOWED_AUDIO_MIME: Set[str] = {
    "audio/mpeg",      # mp3
    "audio/mp4",       # m4a
    "audio/aac",
    "audio/wav",
    "audio/x-wav",
    "audio/ogg",
    "audio/webm",
    "audio/flac",
}

ALLOWED_VIDEO_MIME: Set[str] = {
    "video/mp4",
    "video/webm",
    "video/ogg",
    "video/quicktime",   # mov
    "video/x-matroska",  # mkv (selon filetype)
}


def detect_mime_and_ext(file_bytes: bytes) -> Tuple[str, str]:
    """
    Détecte le type réel via 'filetype'.
    Retourne (real_mime, ext_with_dot).
    """
    kind = filetype.guess(file_bytes)
    real_mime = kind.mime if kind else "application/octet-stream"
    ext = "." + (kind.extension if kind else "bin")
    return real_mime, ext


def validate_bytes(
    file_bytes: bytes,
    *,
    max_mb: int,
    allowed_mime: Set[str],
) -> Tuple[str, str, int, str]:
    """
    Retourne (real_mime, ext_with_dot, size_bytes, sha256).
    Lève ValueError si invalide.
    """
    size = len(file_bytes)
    if size == 0:
        raise ValueError("Fichier vide")
    if size > max_mb * 1024 * 1024:
        raise ValueError(f"Taille invalide (max {max_mb} MB)")

    real_mime, ext = detect_mime_and_ext(file_bytes)

    if real_mime not in allowed_mime:
        raise ValueError(f"Type non autorisé: {real_mime}")

    sha = hashlib.sha256(file_bytes).hexdigest()
    return real_mime, ext, size, sha


def build_object_key(*, prefix: str, owner_id: Optional[int], ext_with_dot: str) -> str:
    """
    Construit une clé MinIO stable et lisible.
    Exemple:
      prefix="images" -> images/users/12/2025-12-18/<uuid>.png
      prefix="audios" -> audios/users/12/2025-12-18/<uuid>.mp3
    """
    today = datetime.date.today().isoformat()
    from uuid import uuid4

    safe_owner = owner_id if owner_id is not None else "anonymous"
    ext = ext_with_dot if ext_with_dot.startswith(".") else f".{ext_with_dot}"

    return f"{prefix}/users/{safe_owner}/{today}/{uuid4().hex}{ext}"
