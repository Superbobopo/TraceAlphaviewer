from __future__ import annotations
import copy
from dataclasses import dataclass, field
from typing import List, Optional

# ── Palette de couleurs pour les boîtes ──────────────────────────────────────
BOX_PALETTE = [
    "#4FC3F7", "#81C784", "#FFB74D", "#F06292",
    "#BA68C8", "#4DB6AC", "#FF8A65", "#E6EE9C",
    "#CE93D8", "#80DEEA", "#FFCC02", "#A5D6A7",
]


def box_color(barcode: str) -> str:
    """Retourne une couleur reproductible à partir du code-barres."""
    try:
        idx = int(barcode[-5:]) % len(BOX_PALETTE)
    except (ValueError, IndexError):
        idx = sum(ord(ch) for ch in barcode) % len(BOX_PALETTE)
    return BOX_PALETTE[idx]


# ── Modèle d'une boîte ───────────────────────────────────────────────────────
@dataclass
class MachineEvent:
    line_num: int
    timestamp: float
    timestamp_str: str
    severity: str
    kind: str
    title: str
    detail: str = ""


@dataclass
class BoxInfo:
    barcode: str = ""
    source_ref: str = ""  # reference initiale avant re-identification (ex: ALPHA-INC-001)
    name: str = ""
    lot: str = ""
    length_mm: int = 0   # dimension dans le sens T5 (mm)
    width_mm: int = 0    # largeur (mm)
    height_mm: int = 0   # hauteur (mm)
    t5_footprint_mm: int = 0  # largeur occupee sur T5/goulotte (mm)
    id_b: int = 0        # identifiant de cheminement Alpha (Nboite / idB)
    id_alpha: int = 0    # identifiant BdD alpha
    x_pos: int = 0       # position X sur T5 (mm, coordonnées machine)
    t5_entry_aligned: bool = False  # arrivee T5 a afficher dans l'axe T4
    color: str = "#4FC3F7"

    def short_label(self) -> str:
        """Libellé court pour affichage sur canvas."""
        if self.name:
            words = self.name.split()
            return " ".join(words[:2])
        if self.source_ref:
            return self.source_ref
        return self.barcode[-6:] if self.barcode else "?"

    def dim_label(self) -> str:
        if self.length_mm:
            return f"{self.width_mm}×{self.height_mm}×{self.length_mm}mm"
        return ""


# ── Snapshot complet de l'état machine à un instant donné ───────────────────
@dataclass
class MachineState:
    line_num: int = 0
    timestamp: float = 0.0      # secondes depuis le début de la trace
    timestamp_str: str = ""     # "HH:MM:SS"

    # -- États des tâches (chaînes comme "WAIT-COND", "MODE-AUTO", …) --------
    state_T0: str = "INIT"
    state_T1: str = "INIT"
    state_T2: str = "INIT"
    state_tEA_T3: str = "INIT"
    state_tT3_T4: str = "INIT"
    state_tT4_T5: str = "INIT"
    state_T5: str = "INIT"

    # -- Codes moteurs (eT) --------------------------------------------------
    eT0: int = 0
    eT1: int = 0
    eT2: int = 0
    eT3: int = 0
    eT4: int = 0
    eT5: int = 0

    # -- Capteurs (0=inactif, 1=actif) ----------------------------------------
    C0: int = 0    # début T1 (présence boîte entrée T1)
    C1: int = 0    # fin T1 (présence boîte sortie T1)
    C2: int = 0    # T2
    C3: int = 0    # T2 (chargé)
    C4: int = 0    # EA (présence boîte sur zone EA)
    C5: int = 0    # T3 (présence boîte sur T3)
    C6: int = 0    # T4 (présence boîte sur T4)
    C9: int = 0    # laser T5

    # -- Capteurs spéciaux T5 ------------------------------------------------
    flag_poubelle_pleine: int = 0   # FlagPoubellePleine (gauche T5)
    lzb: int = 0                    # mesure hauteur (droite T5, tentative LzB)

    # -- Positions des boîtes (mm) -------------------------------------------
    pT3: int = 0          # ≤ 0 : boîte présente sur T3 (0 = référence départ)
    pT4: int = 0          # > 0 : boîte sur T4 ; ≤ 0 : passée sur T5
    pT5: int = 0          # position encodeur T5
    LgBtT4: float = 0.0   # longueur boîte mesurée sur T4 (mm)
    larg_T5: int = 0      # largeur mesurée sur T5
    fgBfinT3: int = 0
    fgBfinT4: int = 0
    eT5useO: int = 0
    eT5useA: int = 0

    # -- Identification -------------------------------------------------------
    idCB1_state: str = ""
    idCB1_barcode: str = ""

    # -- Boîtes tracées -------------------------------------------------------
    box_in_EA: Optional[BoxInfo] = None     # boîte en cours d'identification
    box_on_T3: Optional[BoxInfo] = None     # boite sur T3 / C5 / CB2
    box_on_T4: Optional[BoxInfo] = None     # boite sur T4 / C6
    boxes_on_T5: List[BoxInfo] = field(default_factory=list)  # boîtes sur T5

    # -- Lignes brutes de ce timestamp : List[Tuple[int, str]] ---------------
    # Chaque élément = (numéro_ligne_fichier, texte)
    raw_lines: List[tuple] = field(default_factory=list)
    events: List[MachineEvent] = field(default_factory=list)

    def deep_copy(self) -> "MachineState":
        """Copie profonde efficace (ne duplique pas raw_lines)."""
        s = copy.copy(self)
        s.raw_lines = list(self.raw_lines)
        s.events = list(self.events)
        s.boxes_on_T5 = [copy.copy(b) for b in self.boxes_on_T5]
        s.box_in_EA = copy.copy(self.box_in_EA) if self.box_in_EA else None
        s.box_on_T3 = copy.copy(self.box_on_T3) if self.box_on_T3 else None
        s.box_on_T4 = copy.copy(self.box_on_T4) if self.box_on_T4 else None
        return s

    def format_time(self) -> str:
        """Retourne une chaîne HH:MM:SS à partir du timestamp relatif."""
        t = int(self.timestamp)
        h, r = divmod(t, 3600)
        m, s = divmod(r, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
