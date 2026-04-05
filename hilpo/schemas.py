"""Schemas Pydantic pour le pipeline HILPO."""

from __future__ import annotations

from pydantic import BaseModel


# ── Features extraites par le descripteur ──────────────────────


class TexteOverlay(BaseModel):
    present: bool = False
    type: str | None = None  # actualite, citation, chiffre, titre_editorial, liste_numerotee, annotation, description_produit
    contenu_resume: str | None = None


class Logos(BaseModel):
    views: bool = False
    specifique: str | None = None  # BLUEPRINT, MOODY_MONDAY, MOODY_SUNDAY, REWIND, 9_PIECES, THROWBACK, VIEWS_ESSENTIALS, VIEWS_RESEARCH, VIEWS_TV
    marque_partenaire: str | None = None


class MiseEnPage(BaseModel):
    fond: str | None = None  # photo_plein_cadre, couleur_unie, texture, collage, split_screen
    nombre_slides: int = 1
    structure: str | None = None  # slide_unique, gabarit_repete, opener_contenu_closer, collage_grille


class ContenuPrincipal(BaseModel):
    personnes_visibles: bool = False
    type_personne: str | None = None  # artiste, athlete, personnalite, anonyme
    screenshots_film: bool = False
    pochettes_album: bool = False
    zoom_objet: bool = False
    photos_evenement: bool = False


class AudioVideo(BaseModel):
    voix_off_narrative: bool = False
    interview_face_camera: bool = False
    musique_dominante: bool = False
    type_montage: str | None = None  # captation_live, montage_edite, face_camera, b_roll_narration


class AnalyseCaption(BaseModel):
    longueur: int = 0
    mentions_marques: list[str] = []
    hashtags_format: str | None = None
    mention_partenariat: bool = False
    sujet_resume: str | None = None


class IndicesBrandContent(BaseModel):
    produit_mis_en_avant: bool = False
    mention_partenariat_caption: bool = False
    logo_marque_commerciale: bool = False


class DescriptorFeatures(BaseModel):
    """Output structuré du descripteur multimodal."""

    resume_visuel: str
    texte_overlay: TexteOverlay = TexteOverlay()
    logos: Logos = Logos()
    mise_en_page: MiseEnPage = MiseEnPage()
    contenu_principal: ContenuPrincipal = ContenuPrincipal()
    audio_video: AudioVideo = AudioVideo()
    analyse_caption: AnalyseCaption = AnalyseCaption()
    indices_brand_content: IndicesBrandContent = IndicesBrandContent()


# ── Résultat de classification d'un post ───────────────────────


class PostPrediction(BaseModel):
    """Prédictions pour un post (3 axes)."""

    ig_media_id: int
    category: str
    visual_format: str
    strategy: str
    features: DescriptorFeatures
