from typing import Optional, Literal, List
from datetime import datetime
from pydantic import BaseModel, Field as PydField, field_validator, model_validator


# ============================================================================
# Matching Question Schemas (must be defined before QuestionCreateIn)
# ============================================================================

class MatchingElementIn(BaseModel):
    """Schéma d'entrée pour un élément de question matching."""
    list_index: int = PydField(..., ge=0, description="Index de la liste (0-based)")
    position: int = PydField(..., ge=0, description="Position dans la liste (0-based)")
    text: Optional[str] = PydField(None, description="Contenu texte (exclusif avec media)")
    media_id: Optional[int] = PydField(None, ge=1, description="ID du média (Image/Audio/Video)")
    media_type: Optional[Literal["image", "audio", "video"]] = PydField(
        None, description="Type de média"
    )

    @model_validator(mode='after')
    def validate_text_or_media(self):
        """Valide que soit text soit media est fourni, mais pas les deux."""
        has_text = self.text is not None and len(self.text.strip()) > 0
        has_media = self.media_id is not None and self.media_type is not None
        
        if has_text and has_media:
            raise ValueError("Un élément ne peut avoir à la fois du texte et un média")
        if not has_text and not has_media:
            raise ValueError("Un élément doit avoir soit du texte soit un média")
        
        # Si media sans media_type ou vice versa
        if (self.media_id is not None) != (self.media_type is not None):
            raise ValueError("media_id et media_type doivent être fournis ensemble")
        
        return self


class MatchingElementOut(MatchingElementIn):
    """Schéma de sortie pour un élément de question matching."""
    id: int
    question_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MatchingElementWithSignedUrlOut(MatchingElementOut):
    """Schéma de sortie pour un élément matching avec signed URLs pour les médias."""
    media_signed_url: Optional[str] = None
    media_signed_expires_in: Optional[int] = None


class MatchingCorrectPairIn(BaseModel):
    """Schéma d'entrée pour une paire correcte de question matching."""
    list_index_1: int = PydField(..., ge=0, description="Index de la première liste")
    element_position_1: int = PydField(..., ge=0, description="Position du premier élément")
    list_index_2: int = PydField(..., ge=0, description="Index de la seconde liste")
    element_position_2: int = PydField(..., ge=0, description="Position du second élément")


class MatchingCorrectPairOut(MatchingCorrectPairIn):
    """Schéma de sortie pour une paire correcte de question matching."""
    id: int
    question_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ============================================================================
# Question Schemas
# ============================================================================

class QuestionCreateIn(BaseModel):
    question: str = PydField(..., description="Intitulé de la question")
    answer: str = PydField("", description="Réponse attendue (utilisé uniquement pour type 'classic')")
    points: int = PydField(1, ge=0, description="Points attribués à la question")
    
    question_type: Literal["classic", "matching"] = PydField(
        "classic", 
        description="Type de question: 'classic' ou 'matching'"
    )

    theme_id: int = PydField(..., ge=1, description="ID du thème associé")

    # Champs pour questions classiques
    question_image_id: Optional[int] = None
    answer_image_id: Optional[int] = None

    question_audio_id: Optional[int] = None
    answer_audio_id: Optional[int] = None

    question_video_id: Optional[int] = None
    answer_video_id: Optional[int] = None
    
    # Champs pour questions matching
    matching_elements: Optional[List[MatchingElementIn]] = None
    matching_correct_pairs: Optional[List[MatchingCorrectPairIn]] = None

    @model_validator(mode='after')
    def validate_question_type_fields(self):
        """Valide que les bons champs sont fournis selon le type de question."""
        if self.question_type == "classic":
            if not self.answer or len(self.answer.strip()) == 0:
                raise ValueError("Le champ 'answer' est requis pour les questions de type 'classic'")
        
        elif self.question_type == "matching":
            if not self.matching_elements or not self.matching_correct_pairs:
                raise ValueError(
                    "Les champs 'matching_elements' et 'matching_correct_pairs' "
                    "sont requis pour les questions de type 'matching'"
                )
            
            # Valider la structure des listes
            if len(self.matching_elements) < 2:
                raise ValueError("Une question matching doit avoir au moins 2 éléments")
            
            # Grouper par list_index pour vérifier qu'il y a au moins 2 listes
            lists_dict = {}
            for elem in self.matching_elements:
                if elem.list_index not in lists_dict:
                    lists_dict[elem.list_index] = []
                lists_dict[elem.list_index].append(elem)
            
            if len(lists_dict) < 2:
                raise ValueError("Une question matching doit avoir au moins 2 listes")
            
            # Vérifier que toutes les listes ont le même nombre d'éléments
            list_lengths = [len(elems) for elems in lists_dict.values()]
            if len(set(list_lengths)) > 1:
                raise ValueError(
                    "Toutes les listes doivent avoir le même nombre d'éléments. "
                    f"Longueurs détectées: {list_lengths}"
                )
            
            # Vérifier qu'il y a au moins 2 éléments par liste
            if list_lengths[0] < 2:
                raise ValueError("Chaque liste doit avoir au moins 2 éléments")
            
            # Valider que les paires correctes référencent des éléments existants
            for pair in self.matching_correct_pairs:
                # Vérifier que les indices de liste existent
                if pair.list_index_1 not in lists_dict or pair.list_index_2 not in lists_dict:
                    raise ValueError(
                        f"Paire incorrecte: liste {pair.list_index_1} ou {pair.list_index_2} n'existe pas"
                    )
                
                # Vérifier que les positions existent dans leurs listes
                if pair.element_position_1 >= len(lists_dict[pair.list_index_1]):
                    raise ValueError(
                        f"Position {pair.element_position_1} invalide pour liste {pair.list_index_1}"
                    )
                if pair.element_position_2 >= len(lists_dict[pair.list_index_2]):
                    raise ValueError(
                        f"Position {pair.element_position_2} invalide pour liste {pair.list_index_2}"
                    )
                
                # Vérifier que les deux éléments sont dans des listes différentes
                if pair.list_index_1 == pair.list_index_2:
                    raise ValueError("Une paire ne peut pas associer deux éléments de la même liste")
        
        return self


class QuestionUpdateIn(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    points: Optional[int] = PydField(None, ge=0)
    
    question_type: Optional[Literal["classic", "matching"]] = None

    question_image_id: Optional[int] = None
    answer_image_id: Optional[int] = None

    question_audio_id: Optional[int] = None
    answer_audio_id: Optional[int] = None

    question_video_id: Optional[int] = None
    answer_video_id: Optional[int] = None
    
    # Champs pour questions matching (si fournis, remplacent les éléments/paires existants)
    matching_elements: Optional[List[MatchingElementIn]] = None
    matching_correct_pairs: Optional[List[MatchingCorrectPairIn]] = None


class QuestionOut(BaseModel):
    id: int
    theme_id: int

    question: str
    answer: str
    points: int
    
    question_type: Literal["classic", "matching"] = "classic"

    question_image_id: Optional[int]
    answer_image_id: Optional[int]

    question_audio_id: Optional[int]
    answer_audio_id: Optional[int]

    question_video_id: Optional[int]
    answer_video_id: Optional[int]
    
    # Champs pour questions matching
    matching_elements: List[MatchingElementOut] = []
    matching_correct_pairs: List[MatchingCorrectPairOut] = []

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class QuestionJoinWithSignedUrlOut(QuestionOut):
    question_image_signed_url: Optional[str] = None
    question_image_signed_expires_in: Optional[int] = None
    answer_image_signed_url: Optional[str] = None
    answer_image_signed_expires_in: Optional[int] = None

    question_audio_signed_url: Optional[str] = None
    question_audio_signed_expires_in: Optional[int] = None
    answer_audio_signed_url: Optional[str] = None
    answer_audio_signed_expires_in: Optional[int] = None

    question_video_signed_url: Optional[str] = None
    question_video_signed_expires_in: Optional[int] = None
    answer_video_signed_url: Optional[str] = None
    answer_video_signed_expires_in: Optional[int] = None

    # Override pour matching elements avec signed URLs
    matching_elements: List[MatchingElementWithSignedUrlOut] = []

    # Statistiques d'usage pour cette question
    positive_answers_count: int = 0
    negative_answers_count: int = 0
    cancelled_answers_count: int = 0
