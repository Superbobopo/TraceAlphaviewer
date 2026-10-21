"""
Generation d'un rapport HTML local pour les diagnostics.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from Models.diagnostic import DiagnosticIncident, camera_report_stats
from Models.state import MachineState
from Models.measurement_analysis import analyze_measurements, representative_samples
from Models.robot_drain import t5_priority_score, drain_metric_text


_SEVERITY_LABELS = {
    "error": "CRITIQUE",
    "warning": "ALERTE",
    "info": "INFO",
}

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}

_FAMILY_LABELS = {
    "all": "Tout",
    "critical": "Critique",
    "t2": "T2/C4/T3",
    "t4": "T4/C6",
    "t5": "T5/C9",
    "camera": "Cameras",
    "references": "Références",
    "dimensions": "Dimensions",
    "robot": "Robot/vidage",
    "system": "Carte Alpha",
    "other": "Autre",
}

_DIMENSION_CODES = {"ORIENTATION", "T4_LENGTH", "T5_HEIGHT", "T5_WIDTH", "GLOBAL"}
_REPORT_APP_DIR = Path(__file__).resolve().parents[1] / "report_app"
_REPORT_APP_BUILD_DIR = _REPORT_APP_DIR / "out"


def reports_dir() -> Path:
    base_dir = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    return base_dir / "TraceAlphaViewer" / "reports"


def _clean(text: object) -> str:
    return " ".join(str(text or "").split())


def _shorten(text: object, max_len: int = 170) -> str:
    value = _clean(text)
    if len(value) <= max_len:
        return value
    return value[: max_len - 3].rstrip() + "..."


def _duration_label(start: float, end: float) -> str:
    duration = max(0, int(end - start))
    minutes, seconds = divmod(duration, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def _metric_from_summary(summary: str, code: str, occurrence_count: int, metrics=None) -> str:
    metrics = metrics or {}
    if code == 'DemVidageComplet' and metrics.get('hour'):
        return drain_metric_text(metrics)
    if code == 'ALPHA_CARD_RESET' and 'trace_duration' in metrics:
        return f"{occurrence_count} reset(s) sur {metrics['trace_duration']} de trace"
    if code == 'UNKNOWN' and metrics.get('total_boxes'):
        total = metrics['total_boxes']
        return f"{occurrence_count} unknown / {total} boites ({100 * occurrence_count / total:.1f}%)"
    if code == 'REFERENCE_ABSENT':
        total = metrics.get('total_boxes', 0)
        population = f" / {total} passages" if total else ''
        return f"{occurrence_count} boîte(s){population} · {metrics.get('reference_count', 0)} référence(s)"
    if code == 'CAM-NO-READ' and 'missing_cameras' in metrics:
        return 'cameras sans lecture: ' + ', '.join(metrics['missing_cameras'])
    if code == "ALPHA_CARD_RESET":
        match = re.search(r"(\d+) reset(?:\(s\))? carte Alpha .*? sur ([^.]+?) de trace", summary)
        if match:
            return f"{match.group(1)} reset(s) sur {match.group(2)} de trace"
        return f"{occurrence_count} reset(s) carte Alpha"
    if code == "UNKNOWN":
        match = re.search(
            r"(\d+) boite\(s\) unknown confirmee\(s\) CB1\+CB2 sur (\d+) boite\(s\) passees \(([^)]+)\)",
            summary,
        )
        if match:
            return f"{match.group(1)} unknown / {match.group(2)} boites ({match.group(3)})"
    if code == "CAM-NO-READ":
        match = re.search(r"Camera\(s\) sans reussite observee .*?: (.+?)\.", summary)
        if match:
            return f"cameras sans lecture: {match.group(1)}"
    if code == "C9_WIDTH_INVALID":
        return f"{occurrence_count} largeur(s) <2 mm avec C9 actif"
    if code == "CUBESTOP_C4_BLOCKED":
        return f"{occurrence_count} tentative(s) EA->T3 bloquee(s)"
    return f"{occurrence_count} occurrence(s)"


def _family_for(belt: str, code: str, title: str) -> str:
    text = f"{belt} {code} {title}".upper()
    if code == 'DemVidageComplet':
        return 'robot'
    if code == "ALPHA_CARD_RESET":
        return "system"
    if code == 'REFERENCE_ABSENT':
        return 'references'
    if code in _DIMENSION_CODES:
        return "dimensions"
    if code in {"UNKNOWN", "CAM-NO-READ"} or belt == "IDENTIF":
        return "camera"
    if code == "CUBESTOP_C4_BLOCKED" or belt in {"EA", "T2"} or (belt == "T3" and code in {"-43", "-48"}):
        return "t2"
    if code == "C9_WIDTH_INVALID" or "C9" in text or belt == "T5":
        return "t5"
    if belt == "T4" or code in {"C6", "DIFFT4"} or "C6" in text:
        return "t4"
    if "VIDAGE" in text or "ROBOT" in text:
        return "robot"
    return "other"


def _action_label(code: str, belt: str, title: str) -> str:
    if code == 'REFERENCE_ABSENT':
        return ('Faire passer cette référence par la zone de chargement manuel pour créer sa fiche '
                'avant son utilisation dans l’Alpha.')
    if code == "ALPHA_CARD_RESET":
        return "Verifier shunts CubeStop/balance et alimentation Alpha"
    if code == "C9_WIDTH_INVALID":
        return "Verifier C9 et le passage boite sur T5"
    if code == "CUBESTOP_C4_BLOCKED":
        return "Verifier CubeStop, C4 et ejecteur vers T3"
    if code == "UNKNOWN":
        return "Controler les cameras et lectures Datamatrix"
    if code == "CAM-NO-READ":
        return "Verifier la camera sans lecture"
    if code == "ORIENTATION":
        return "Controler l'orientation physique des boites"
    if code == "GLOBAL":
        return "Chercher blocage, tassage T5 ou mesure perturbee"
    if code == "T5_WIDTH":
        return "Verifier la mesure largeur C9/T5"
    if code == "T5_HEIGHT":
        return "Verifier le capteur hauteur LzB"
    if code in {"T4_LENGTH", "diffT4"} or belt == "T4":
        return "Verifier C6, entrainement et longueur T4"
    if "Vidage" in title or "VIDAGE" in code.upper():
        return "Analyser vidage T5 et prise robot"
    return _shorten(title, 90)


def _impact_label(code: str, belt: str) -> str:
    if code == 'REFERENCE_ABSENT':
        return 'Le CIP est lu, mais la référence absente des tables est rejetée avec une référence technique unknown.'
    if code == "C9_WIDTH_INVALID":
        return "La largeur T5 est invalide alors que C9 detecte une presence ; la boite peut etre mal mesuree ou mal passee."
    if code == "CUBESTOP_C4_BLOCKED":
        return "Le passage EA/C4 vers T3 ne se libere pas ; la boite reste sur C4 malgre la demande de transfert."
    if code == "UNKNOWN":
        return "Des boites sortent sans reference fiable ; le tri et le suivi produit deviennent incertains."
    if code == "CAM-NO-READ":
        return "Une camera attendue ne contribue pas ; les non lectures risquent d'augmenter."
    if code == "ORIENTATION":
        return "Les dimensions suggerent une autre orientation ou un sens indecidable ; verifier la presentation physique."
    if code == "GLOBAL":
        return "Plusieurs dimensions ne collent pas a la BdD ; suspicion blocage, mauvais tassement ou capteur perturbe."
    if code == "T5_WIDTH":
        return "La largeur mesuree sur T5/C9 ne colle pas a la reference ; verifier C9 et le mouvement T5."
    if code == "T5_HEIGHT":
        return "La hauteur mesuree ne colle pas a la reference ; verifier LzB et son parametrage."
    if code == "T4_LENGTH" or code == "diffT4" or belt == "T4":
        return "La longueur T4 peut etre fausse ; verifier C6, moteur, rouleau et entrainement."
    if belt == "T5":
        return "Le cycle T5 peut perturber la mesure ou la prise robot."
    return "Ce diagnostic demande un controle terrain avant de conclure."


def _business_lines(summary: str, code: str) -> list[str]:
    if code == 'REFERENCE_ABSENT':
        return [summary]
    if code == "UNKNOWN":
        lines: list[str] = []
        attribution = re.search(r"Attribution unknown finales: ([^.]+)\.", summary)
        zero_codes = re.search(r"(CB1 0 code: [^.]+; CB2 0 code: [^.]+)\.", summary)
        cameras = re.search(r"(CB1 cameras reussies: [^.]+; CB2 cameras reussies: [^.]+)\.", summary)
        for match in (attribution, zero_codes, cameras):
            if match:
                lines.append(match.group(1))
        return lines or [_shorten(summary, 220)]
    if code == "CAM-NO-READ":
        match = re.search(r"Camera\(s\) sans reussite observee .*?: (.+?)\.", summary)
        return [f"Camera(s) a verifier: {match.group(1)}"] if match else [_shorten(summary, 220)]
    if code == "C9_WIDTH_INVALID":
        return ["Largeur T5 <2 mm avec C9 actif: suspicion forte C9/T5."]
    if code == "CUBESTOP_C4_BLOCKED":
        return ["CubeStop commande HAUT, transfert EA->T3 demande, mais C4 reste actif et C5 ne voit pas la boite."]
    if code == 'DemVidageComplet':
        return [summary]
    if code == "T5_STALE_UNMEASURED_BOX":
        return ["Boite T5 non mesuree reste en base et provoque des manques de place."]
    if code == "ORIENTATION":
        return ["Orientation probable ou indecidable d'apres les dimensions : boite exclue du bilan, presentation a verifier."]
    return [_shorten(summary, 220)]


def _ratio(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return count / total


def _affected_label(count: int, total: int) -> str:
    if total <= 0:
        return f"{count} occurrence(s)"
    return f"{count}/{total} boites ({_ratio(count, total) * 100:.1f}%)"


def _stale_t5_box_id(summary: str) -> str:
    match = re.search(r"\bIdA:(\d+)", summary)
    return match.group(1) if match else "?"


def _stale_t5_box_metric(group: dict[str, object], total_boxes: int) -> str:
    incidents = list(group.get("incidents", []))
    box_ids = [
        _stale_t5_box_id(str(incident.get("summary", "")))
        for incident in incidents
        if isinstance(incident, dict)
    ]
    box_ids = [box_id for box_id in box_ids if box_id != "?"]
    box_count = len(box_ids) or int(group.get("incident_count", 0))
    message_count = int(group.get("occurrence_count", 0))
    ids = f": {', '.join(box_ids)}" if box_ids else ""
    total = f" | {total_boxes} boites vues trace" if total_boxes > 0 else ""
    return (
        f"{box_count} boite(s) T5 non mesuree(s){ids} | "
        f"{message_count} messages \"pas assez de place\"{total}"
    )


def _stale_t5_business_lines(group: dict[str, object]) -> list[str]:
    incidents = list(group.get("incidents", []))
    lines = ["Gravite: blocage complet T5, pas volume de boites touchees."]
    for incident in incidents:
        if not isinstance(incident, dict):
            continue
        box_id = _stale_t5_box_id(str(incident.get("summary", "")))
        count = int(incident.get("count", 0) or 0)
        if box_id != "?" and count:
            lines.append(f"IdA {box_id}: {count} messages \"pas assez de place\".")
    lines.append("Impact: empeche la mesure/repos des boites suivantes.")
    return lines


def _field_zone_label(group: dict[str, object]) -> str:
    belt = str(group["belt"])
    code = str(group["code"])
    if code == "ALPHA_CARD_RESET":
        return "Carte Alpha"
    if belt == "T2" and code == "-88":
        return "T2/C4"
    if belt == "T3" and code == "-48":
        return "T3/C4"
    if belt == "T3" and code == "-43":
        return "T3/C4"
    if code == "CUBESTOP_C4_BLOCKED":
        return "T2/C4/T3"
    if code == "C9_WIDTH_INVALID" or code == "T5_WIDTH":
        return "T5/C9"
    if code == "T5_STALE_UNMEASURED_BOX":
        return "T5 blocage"
    if code in _DIMENSION_CODES:
        return "Dimensions"
    return str(group["family_label"])


def _field_explanation(group: dict[str, object], total_boxes: int, c9_massive: bool) -> tuple[str, str, str]:
    code = str(group["code"])
    if code == 'DemVidageComplet':
        return (str(group['summary']),
                "Le robot demande de vider tout T5 apres un incident de prise ; la cause reste a confirmer.",
                "Comparer deplacement commande/reel T5, presentation des boites et position physique de l'Alpha.")
    belt = str(group["belt"])
    count = int(group["occurrence_count"])
    ratio = _ratio(count, total_boxes)

    if code == 'REFERENCE_ABSENT':
        return (
            'Le CIP est décodé, mais la référence est absente et sa création par l’Alpha est refusée.',
            'Le passage reste en référence technique unknown ; il est exclu des UNKNOWN de décodage.',
            str(group['action']),
        )

    if code == "ALPHA_CARD_RESET":
        if count <= 0:
            return (
                "Le compteur d'uptime Alpha ne redescend pas pendant la trace.",
                "Aucun redemarrage spontane de la carte n'est observe.",
                "Aucune action requise sur la base de ce compteur.",
            )
        return (
            "Le compteur d'uptime de la carte Alpha chute et repart pres de zero.",
            "La carte Alpha redemarre en fonctionnement, ce qui peut interrompre completement le cycle machine.",
            "Verifier les shunts CubeStop/balance, puis le cablage, les masses et l'alimentation Alpha.",
        )

    if code == "C9_WIDTH_INVALID":
        return (
            "La largeur lue sur T5 est quasi nulle alors que C9 voit une boite.",
            "C9 perturbe, mauvais passage devant C9, mauvais tassement T5 ou boites bloquees avant butee.",
            "Controler C9, le passage devant C9 et le tassage T5 avant de relancer en production.",
        )
    if code == "T5_STALE_UNMEASURED_BOX":
        return (
            "Une boite reste non mesuree dans la base T5 et se deplace avec les mouvements collectifs.",
            "Le T5 manque de place pour mesurer/repositionner les boites suivantes sans pousser cette boite trop loin.",
            "Retrouver la boite indiquee par IdA, verifier son blocage physique puis vider ou corriger l'etat T5 avant reprise.",
        )
    if code == "CUBESTOP_C4_BLOCKED":
        return (
            "Le CubeStop est commande en haut pour liberer le passage vers T3, mais C4 reste actif.",
            "La boite ne quitte pas C4: volet CubeStop suspect, ejecteur inefficace, blocage mecanique ou C4 faux actif.",
            "Observer le CubeStop pendant la commande HAUT, verifier l'ejecteur C4, le rail vers T3 et le capteur C4.",
        )
    if code == "GLOBAL":
        return (
            "Plusieurs dimensions mesurées ne correspondent pas aux dimensions attendues dans la base de données (BdD).",
            "Boite bloquee, mauvais tassage T5, mesure perturbee par une boite precedente, probleme mecanique T4/T5 ou capteur.",
            "Chercher un blocage physique et verifier C6, C9, LzB ainsi que l'entrainement T4/T5.",
        )
    if code == "T4_LENGTH":
        return (
            "La longueur mesurée sur T4, avec le capteur C6, est trop courte ou trop longue par rapport à la dimension attendue dans la base de données.",
            "Le sens et la régularité des écarts aident à choisir les contrôles ; ils ne prouvent pas une cause à eux seuls.",
            "Comparer les écarts en moins et en trop, puis suivre les pistes du bilan de longueur.",
        )
    if code == "T5_HEIGHT":
        return (
            "La hauteur mesurée sur T5 ne correspond pas à la hauteur attendue dans la base de données.",
            "La mesure de hauteur ou la présentation de la boîte peut être perturbée.",
            "Vérifier le capteur de hauteur LzB, sa fixation et son paramétrage.",
        )
    if code == "T5_WIDTH":
        action = "Traiter avec le probleme C9 massif deja detecte." if c9_massive else "Verifier C9/T5 et refaire une mesure controlee."
        return (
            "La largeur mesurée sur T5, avec le capteur C9, ne correspond pas à la largeur attendue dans la base de données.",
            "Suspicion mesure C9/T5 ou passage boite incorrect devant C9.",
            action,
        )
    if belt == "T2" and code == "-88":
        return (
            "Le transfert signale une boîte déjà présente au niveau du capteur C4.",
            "Boite bloquee sur C4, ejecteur qui n'ejecte pas, C4 faux actif ou cubestop qui ne laisse pas passer.",
            "Verifier C4, l'ejecteur, le capteur C4 et le cubestop. Critique seulement si le defaut se repete ou bloque le flux.",
        )
    if belt == "T3" and code == "-43":
        return (
            "T3 signale une boite coincee pendant le transfert EA/C4 vers T3.",
            "Boite bloquee sur C4, ejecteur inefficace, C4 faux actif ou CubeStop qui ne remonte pas vraiment.",
            "Verifier le mouvement reel du CubeStop, l'ejecteur C4, le rail vers T3 et le capteur C4.",
        )
    if belt == "T3" and code == "-48":
        return (
            "T3 attend une boite venant de C4 mais l'evenement est isole dans cette trace.",
            "Ejection/transfert C4 ponctuel a verifier, sans preuve de blocage massif si une seule occurrence.",
            "Surveiller la recurrence ; ne pas traiter comme critique sur une occurrence isolee.",
        )
    if code == "ORIENTATION":
        return (
            "Une autre orientation explique mieux les mesures, ou le sens reste indecidable.",
            "La presentation physique reste a verifier avant d'interpreter ces ecarts comme un defaut de mesure.",
            "Verifier la presentation physique de la reference.",
        )
    if ratio >= 0.10 and code in _DIMENSION_CODES:
        return (
            "Anomalie dimensionnelle recurrente.",
            "Mesure ou presentation boite instable.",
            "Verifier la zone de mesure correspondant a l'axe en erreur.",
        )
    return (
        str(group["symptom"] or group["impact"]),
        "Controle terrain recommande avant conclusion.",
        str(group["action"]),
    )


def _field_severity_for(group: dict[str, object], total_boxes: int, c9_massive: bool) -> str:
    code = str(group["code"])
    belt = str(group["belt"])
    count = int(group["occurrence_count"])
    ratio = _ratio(count, total_boxes)

    if code == "ALPHA_CARD_RESET":
        return "error" if count > 0 else "info"

    if code == "C9_WIDTH_INVALID":
        return "error" if count >= 5 or ratio >= 0.10 else "warning"
    if code == "T5_STALE_UNMEASURED_BOX":
        return "error"
    if code == "CUBESTOP_C4_BLOCKED":
        return "error" if count >= 2 or str(group["severity"]) == "error" else "warning"
    if code in _DIMENSION_CODES and code != "ORIENTATION":
        comparable = int(group.get("measurement_stats", {}).get("comparable_count", 0))
        return "error" if count >= 10 and comparable > 0 and count * 10 >= comparable else "warning"
    if belt == "T2" and code == "-88":
        return "error" if count >= 3 else "warning"
    if belt == "T3" and code == "-43":
        return "error" if count >= 2 else "warning"
    if belt == "T3" and code == "-48":
        return "warning" if count > 1 else "info"
    if code == "ORIENTATION":
        return "warning"
    if code in {"UNKNOWN", "CAM-NO-READ", "REFERENCE_ABSENT"}:
        return "warning"
    if code in _DIMENSION_CODES:
        return "warning"
    if str(group["severity"]) == "error" and str(code).startswith("-"):
        return "warning"
    return str(group["severity"])


def _field_priority_score(group: dict[str, object]) -> int:
    shared = t5_priority_score(str(group['code']), str(group['field_severity']),
                               int(group['occurrence_count']), group.get('metrics'))
    if shared is not None:
        return shared
    severity_score = {"error": 500, "warning": 190, "info": 80}.get(str(group["field_severity"]), 0)
    code = str(group["code"])
    belt = str(group["belt"])
    code_bonus = {
        "C9_WIDTH_INVALID": 100,
        "T5_STALE_UNMEASURED_BOX": 120,
        "CUBESTOP_C4_BLOCKED": 110,
        "ALPHA_CARD_RESET": 130,
        "GLOBAL": 90,
        "T5_WIDTH": 75,
        "UNKNOWN": 65,
        "REFERENCE_ABSENT": 65,
        "CAM-NO-READ": 60,
        "T4_LENGTH": 55,
        "T5_HEIGHT": 55,
        "ORIENTATION": 35,
    }.get(code, 0)
    if belt == "T2" and code == "-88":
        code_bonus = 70
    elif belt == "T3" and code == "-48":
        code_bonus = 20
    count = int(group["occurrence_count"])
    measurement_bonus = (round(1000 * float(group.get("affected_ratio", 0)))
                         if code in _DIMENSION_CODES and code != "ORIENTATION" and count >= 10 else 0)
    return severity_score + code_bonus + min(count, 60) + measurement_bonus


def _apply_field_severity(grouped: list[dict[str, object]], total_boxes: int) -> None:
    def is_massive_c9(group: dict[str, object]) -> bool:
        count = int(group["occurrence_count"])
        return str(group["code"]) == "C9_WIDTH_INVALID" and (count >= 5 or _ratio(count, total_boxes) >= 0.10)

    c9_massive = any(is_massive_c9(group) for group in grouped)
    for group in grouped:
        count = int(group["occurrence_count"])
        severity = _field_severity_for(group, total_boxes, c9_massive)
        explanation, impact, action = _field_explanation(group, total_boxes, c9_massive)
        group["field_severity"] = severity
        group["field_severity_label"] = _SEVERITY_LABELS.get(severity, severity.upper())
        group["field_zone_label"] = _field_zone_label(group)
        if str(group["code"]) == "T5_STALE_UNMEASURED_BOX":
            group["affected_ratio"] = 0.0
            group["affected_label"] = _stale_t5_box_metric(group, total_boxes)
        elif str(group["code"]) == "ALPHA_CARD_RESET":
            group["affected_ratio"] = 0.0
            group["affected_label"] = str(group["metric"])
        elif str(group['code']) in _DIMENSION_CODES:
            population = group.get('measurement_stats', {})
            total = population.get('comparable_count', 0)
            if group['code'] == 'ORIENTATION':
                total += sum(population.get('excluded', {}).get(key, 0)
                             for key in ('orientation', 'orientation_uncertain'))
            group['affected_ratio'] = _ratio(count,total)
            group['affected_label'] = _affected_label(count,total)
            if group['code'] != 'ORIENTATION' and population and group.get('checks'):
                impact = 'Examiner les écarts par dimension et par produit ; la comparaison seule ne prouve pas une cause.'
                action = group['checks'][0]
                group['impact'] = impact
                group['action'] = action
        else:
            group['affected_ratio'] = _ratio(count,total_boxes) if str(group['code']) == 'UNKNOWN' else 0
            group['affected_label'] = str(group['metric'])
        group["field_explanation"] = explanation
        group["field_impact"] = impact
        group["field_action"] = action
        group["field_priority"] = _field_priority_score(group)


def _priority_score(group: dict[str, object]) -> int:
    shared = t5_priority_score(str(group['code']), str(group['severity']),
                               int(group['occurrence_count']), group.get('metrics'))
    if shared is not None:
        return shared
    severity_score = {"error": 500, "warning": 190, "info": 80}.get(str(group["severity"]), 0)
    code = str(group["code"])
    code_bonus = {
        "C9_WIDTH_INVALID": 95,
        "CUBESTOP_C4_BLOCKED": 100,
        "ALPHA_CARD_RESET": 120,
        "UNKNOWN": 85,
        "REFERENCE_ABSENT": 85,
        "CAM-NO-READ": 80,
        "GLOBAL": 70,
        "T5_WIDTH": 60,
        "T4_LENGTH": 55,
        "T5_HEIGHT": 55,
        "diffT4": 45,
        "C6": 45,
    }.get(code, 0)
    return severity_score + code_bonus + min(int(group["occurrence_count"]), 50)


def _incident_payload(incident: DiagnosticIncident) -> dict[str, object]:
    return {
        "severity": incident.severity,
        "severity_label": _SEVERITY_LABELS.get(incident.severity, incident.severity.upper()),
        "title": incident.title,
        "belt": incident.belt or "-",
        "code": incident.code or "-",
        "first_line": incident.first_line,
        "last_line": incident.last_line,
        "start_time_str": incident.start_time_str,
        "end_time_str": incident.end_time_str,
        "duration": incident.duration_label(),
        "count": incident.count,
        "summary": incident.summary,
        "symptom": incident.symptom,
        "probable_causes": incident.probable_causes,
        "checks": incident.checks,
        "confidence": incident.confidence or "-",
        "event_lines": incident.event_lines,
        "measurement_stats": incident.measurement_stats,
        "examples": incident.examples,
        "metrics": incident.metrics,
    }


def _group_incidents(incidents: list[DiagnosticIncident]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str, str], dict[str, object]] = {}
    for incident in incidents:
        key = (incident.severity, incident.belt, incident.code, incident.title)
        group = groups.get(key)
        if group is None:
            belt = incident.belt or "-"
            code = incident.code or "-"
            family = _family_for(belt, code, incident.title)
            groups[key] = {
                "severity": incident.severity,
                "severity_label": _SEVERITY_LABELS.get(incident.severity, incident.severity.upper()),
                "belt": belt,
                "code": code,
                "title": incident.title,
                "family": family,
                "family_label": _FAMILY_LABELS.get(family, "Autre"),
                "first_line": incident.first_line,
                "last_line": incident.last_line,
                "start_time": incident.start_time,
                "end_time": incident.end_time,
                "start_time_str": incident.start_time_str,
                "end_time_str": incident.end_time_str,
                "incident_count": 1,
                "occurrence_count": incident.count,
                "summary": incident.summary,
                "metrics": incident.metrics,
                "symptom": incident.symptom,
                "probable_causes": list(incident.probable_causes),
                "checks": list(incident.checks),
                "confidence": incident.confidence or "-",
                "business_lines": _business_lines(incident.summary, code),
                "incidents": [_incident_payload(incident)],
            }
            continue

        group["incident_count"] = int(group["incident_count"]) + 1
        group["occurrence_count"] = int(group["occurrence_count"]) + incident.count
        group["incidents"].append(_incident_payload(incident))
        for field in ('probable_causes', 'checks'):
            group[field] = list(dict.fromkeys(group[field] + getattr(incident, field)))
        if incident.first_line < int(group["first_line"]):
            group["first_line"] = incident.first_line
            group["start_time"] = incident.start_time
            group["start_time_str"] = incident.start_time_str
        if incident.last_line > int(group["last_line"]):
            group["last_line"] = incident.last_line
            group["end_time"] = incident.end_time
            group["end_time_str"] = incident.end_time_str

    grouped = list(groups.values())
    for group in grouped:
        code = str(group["code"])
        belt = str(group["belt"])
        group["duration"] = _duration_label(float(group["start_time"]), float(group["end_time"]))
        group["metric"] = _metric_from_summary(str(group["summary"]), code, int(group["occurrence_count"]), group['metrics'])
        if code == "T5_STALE_UNMEASURED_BOX":
            group["business_lines"] = _stale_t5_business_lines(group)
        group["action"] = _action_label(code, belt, str(group["title"]))
        group["impact"] = _impact_label(code, belt)
        group["priority_score"] = _priority_score(group)
        group["evidence"] = (
            f"{group['start_time_str']} -> {group['end_time_str']} | "
            f"L.{group['first_line']} -> L.{group['last_line']} | {group['duration']}"
        )
        group["field_severity"] = group["severity"]
        group["field_severity_label"] = group["severity_label"]
        group["field_zone_label"] = group["family_label"]
        group["affected_ratio"] = 0.0
        group["affected_label"] = group["metric"]
        group["field_explanation"] = group["impact"]
        group["field_impact"] = group["impact"]
        group["field_action"] = group["action"]
        group["field_priority"] = group["priority_score"]
    return sorted(
        grouped,
        key=lambda group: (
            _SEVERITY_ORDER.get(str(group.get("field_severity", group["severity"])), 9),
            -int(group.get("field_priority", group["priority_score"])),
            int(group["first_line"]),
        ),
    )


def _priority_groups(grouped: list[dict[str, object]]) -> list[dict[str, object]]:
    priority = sorted(
        grouped,
        key=lambda group: (-int(group.get("field_priority", group["priority_score"])), int(group["first_line"])),
    )[:5]
    keys = {(str(g["severity"]), str(g["belt"]), str(g["code"]), str(g["title"])) for g in priority}
    for group in grouped:
        key = (str(group["severity"]), str(group["belt"]), str(group["code"]), str(group["title"]))
        important_code = str(group["code"]) in {
            "C9_WIDTH_INVALID", "CUBESTOP_C4_BLOCKED", "ALPHA_CARD_RESET",
            "GLOBAL", "T5_WIDTH", "UNKNOWN", "CAM-NO-READ", "REFERENCE_ABSENT",
        }
        important_et = (str(group["belt"]), str(group["code"])) in {("T2", "-88"), ("T3", "-43"), ("T3", "-48")}
        if (important_code or important_et) and key not in keys:
            priority.append(group)
            keys.add(key)
    return priority[:8]


def _zone_summary(grouped: list[dict[str, object]]) -> list[dict[str, object]]:
    order = ["system", "references", "camera", "t2", "t4", "t5", "dimensions", "robot", "other"]
    summaries: dict[str, dict[str, object]] = {
        family: {
            "family": family,
            "label": _FAMILY_LABELS.get(family, family),
            "groups": 0,
            "occurrences": 0,
            "errors": 0,
            "warnings": 0,
            "top_action": "",
        }
        for family in order
    }
    for group in grouped:
        family = str(group["family"])
        item = summaries.setdefault(family, {
            "family": family,
            "label": _FAMILY_LABELS.get(family, family),
            "groups": 0,
            "occurrences": 0,
            "errors": 0,
            "warnings": 0,
            "top_action": "",
        })
        item["groups"] = int(item["groups"]) + 1
        item["occurrences"] = int(item["occurrences"]) + int(group["occurrence_count"])
        field_severity = str(group.get("field_severity", group["severity"]))
        if field_severity == "error":
            item["errors"] = int(item["errors"]) + 1
        elif field_severity == "warning":
            item["warnings"] = int(item["warnings"]) + 1
        if not item["top_action"]:
            item["top_action"] = group.get("field_action", group["action"])
    return [summaries[family] for family in order if int(summaries[family]["groups"]) > 0]


def _verdict(counts: dict[str, int]) -> dict[str, str]:
    if counts["error"] > 0:
        return {
            "level": "critical",
            "label": "Critique",
            "title": "Points à vérifier en premier",
            "text": "Les problèmes ci-dessous sont classés en priorité selon les blocages ou anomalies observés. Les causes restent à vérifier sur la machine.",
        }
    if counts["warning"] > 0:
        return {
            "level": "warning",
            "label": "A surveiller",
            "title": "Points à vérifier en premier",
            "text": "La trace contient des alertes. Commencez par les contrôles proposés ci-dessous, puis consultez les exemples si nécessaire.",
        }
    return {
        "level": "ok",
        "label": "Rien de bloquant",
        "title": "Aucun incident significatif",
        "text": "Le rapport ne remonte pas d'anomalie prioritaire.",
    }


def _empty_camera_stats() -> dict[str, object]:
    return {
        "available": False,
        "total_boxes": 0,
        "chart": [],
        "reader_stats": [],
        "alerts": [],
        "note": "Donnees cameras indisponibles pour ce rapport.",
        "unknown": {'count': 0, 'total': 0, 'ratio': None, 'alert': False,
                    'buckets': {}, 'checks': [], 'causes': [], 'examples': []},
    }


def _sample_box_details(frame, belt, text):
    candidates = {
        'T4': [frame.box_on_T4], 'T5': frame.boxes_on_T5,
        'EA': [frame.box_in_EA], 'T3': [frame.box_on_T3],
        'IDENTIF': [frame.box_in_EA, frame.box_on_T3],
    }.get(belt, [])
    candidates = [box for box in candidates if box is not None]
    for pattern, attribute in ((r'\bIdA\s*[:=]?\s*(\d+)', 'id_alpha'),
                               (r'\b(?:idB|Nboite)\s*[:=]?\s*(\d+)', 'id_b')):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidates = [b for b in candidates if getattr(b, attribute) == int(match[1])]
    if len(candidates) != 1:
        return {}
    box = candidates[0]
    details = {'box': f'IdA:{box.id_alpha}' if box.id_alpha else f'idB:{box.id_b}' if box.id_b else '',
               'barcode': box.barcode or box.source_ref, 'source_ref': box.source_ref}
    expected = [box.bdd_width_mm, box.bdd_height_mm, box.bdd_length_mm]
    measured = [box.measured_t5_width_mm, box.measured_t5_height_mm,
                box.measured_t4_length_mm if box.measured_t4_line else 0]
    if all(v > 0 for v in expected) and (all(v > 0 for v in measured) or box.measurement_status == 'c9_error'):
        details.update(expected=expected, measured=measured, deltas=[m-e for m,e in zip(measured,expected)],
                       invalid=box.measurement_status == 'c9_error')
    return details


def build_report_payload(
    incidents: list[DiagnosticIncident],
    frames: list[MachineState] | None = None,
    source_name: str = '',
) -> dict[str, object]:
    camera_stats = (frames.read_camera_report() if hasattr(frames, 'read_camera_report') else
                    camera_report_stats(frames) if frames is not None else _empty_camera_stats())
    unknown = dict(camera_stats.get('unknown', {}))
    unknown['examples'] = [dict(sample, id=f'unknown:{sample["line"]}', incident_line=0)
                           for sample in unknown.get('examples', [])]
    total_boxes = int(camera_stats.get("total_boxes") or 0)
    grouped = _group_incidents(incidents)
    analysis = (frames.read_measurements() if hasattr(frames, 'read_measurements') else
                analyze_measurements(frames if frames is not None else []))
    wanted = set()
    targets = {}
    reference_samples = {}
    reference_lists = {}
    for axis, sides in analysis['references'].items():
        reference_lists[axis] = {}
        for side, rows in sides.items():
            reference_lists[axis][side] = []
            for row in rows:
                ids = []
                representative_ids = []
                proofs = [('sample', s) for s in row['samples']]
                proofs += [('representative', s) for s in row.get('representatives', [])]
                for role, original in proofs:
                    key = f"measurement:{original['cycle']}:{original['line']}"
                    if role == 'sample':
                        ids.append(key)
                    if role == 'representative' and key not in representative_ids:
                        representative_ids.append(key)
                    if key not in reference_samples:
                        sample = dict(original, id=key)
                        reference_samples[key] = sample
                        for line in set(sample['sources'].values()) - {0}:
                            wanted.update(range(max(1, line - 2), line + 3))
                reference_lists[axis][side].append(dict({k:v for k,v in row.items() if k not in ('samples', 'representatives')},
                                                       sample_ids=list(dict.fromkeys(ids)), representative_ids=representative_ids,
                                                       navigation_sample_id=ids[0] if ids and side in ('under', 'over') else '',
                                                       display_primary=row['count'] * 10 >= row['total'] if side in ('under', 'over') else True))
    orientation_lists = {}
    for kind, rows in analysis.get('orientation_references', {}).items():
        orientation_lists[kind] = []
        for row in rows:
            ids = []
            for original in row['samples']:
                key = f"orientation:{original['cycle']}:{original['display_frame_index']}"
                ids.append(key)
                reference_samples[key] = dict(original, id=key)
                for line in set(original['sources'].values()) - {0}:
                    wanted.update(range(max(1, line - 2), line + 3))
            orientation_lists[kind].append(dict({key: value for key, value in row.items() if key != 'samples'},
                sample_ids=ids, navigation_sample_id=ids[0]))
    for group in grouped:
        group['id'] = f"{group['code']}:{group['first_line']}:{group['belt']}"
        if group['code'] in _DIMENSION_CODES:
            examples = [dict(sample) for sample in analysis['samples'] if sample['code'] == group['code']]
        else:
            examples = []
            group['series'] = []
            for incident in sorted(group['incidents'], key=lambda item: item['first_line']):
                lines = list(dict.fromkeys(incident['event_lines'] or [incident['first_line']]))
                lines.sort()
                start = len(examples)
                evidence_count = len(lines)
                if group['code'] == 'REFERENCE_ABSENT' and incident['examples']:
                    proofs = sorted(incident['examples'], key=lambda sample: sample['line'])
                    evidence_count = len(proofs)
                    examples.extend(dict(sample, incident_line=incident['first_line']) for sample in proofs[:10])
                else:
                    for line in lines[:10]:
                        examples.append({'line': line, 'time_str': incident['start_time_str'],
                                         'box': '', 'barcode': '', 'detail': incident['summary'],
                                         'incident_line': incident['first_line']})
                group['series'].append({key: incident[key] for key in (
                    'first_line', 'last_line', 'start_time_str', 'end_time_str', 'duration', 'summary', 'count')})
                group['series'][-1].update(example_start=start, example_count=len(examples) - start,
                                          evidence_count=evidence_count,
                                          distinct_events=group['code'] == 'DemVidageComplet')
                # Le total reste complet ; seules les preuves exportees sont bornees.
                incident['event_lines'] = lines[:10]
                incident['examples'] = incident['examples'][:10]
        group['examples'] = examples
        for index, sample in enumerate(examples):
            sample.update(id=f"{group['id']}:{index}", group_id=group['id'])
            if 'measured' not in sample and group['code'] != 'REFERENCE_ABSENT':
                targets.setdefault(sample['line'], []).append((group['belt'], sample))
            wanted.update(range(max(1, sample['line'] - 2), sample['line'] + 3))
            for line in set(sample.get('sources', {}).values()) - {0}:
                wanted.update(range(max(1, line - 2), line + 3))
    for sample in unknown['examples']:
        wanted.update(range(max(1, sample['line'] - 2), sample['line'] + 3))
    raw = {}
    if frames is not None:
        selected_frames = frames.frames_for_lines(wanted) if hasattr(frames, 'frames_for_lines') else frames
        for frame in selected_frames:
            for line, text, *_ in frame.raw_lines:
                if line in wanted:
                    raw[line] = (text, frame.timestamp_str)
                    for belt, sample in targets.pop(line, []):
                        sample.update(_sample_box_details(frame, belt, text))
    for group in grouped:
        for sample in group['examples']:
            sample['context'] = [{'line': n, 'text': raw[n][0]} for n in range(max(1, sample['line'] - 2), sample['line'] + 3) if n in raw]
            present = {row['line'] for row in sample['context']}
            sample['context'] += [{'line': n, 'text': raw[n][0]} for n in sorted(set(sample.get('sources', {}).values()) - present) if n in raw]
            if sample['line'] in raw:
                sample['time_str'] = raw[sample['line']][1]
        group['representative_ids'] = [s['id'] for s in representative_samples(group['examples'], code=group['code'])]
        group['measurement_stats'] = analysis['summary'] if group['code'] in _DIMENSION_CODES else {}
    for sample in reference_samples.values():
        lines = set(sample['sources'].values()) - {0}
        sample['context'] = [{'line': n, 'text': raw[n][0]} for n in sorted(lines) if n in raw]
        if sample['line'] in raw:
            sample['time_str'] = raw[sample['line']][1]
        sample['incident_line'] = next((g['first_line'] for g in grouped if g['code'] == sample['code']), 0)
    unknown_incident = next((g['first_line'] for g in grouped if g['code'] == 'UNKNOWN'), 0)
    for sample in unknown['examples']:
        sample['incident_line'] = unknown_incident
        sample['context'] = [{'line': n, 'text': raw[n][0]} for n in
                             range(max(1, sample['line'] - 2), sample['line'] + 3) if n in raw]
    all_samples = [sample for group in grouped for sample in group['examples']]
    all_samples += list(reference_samples.values()) + unknown['examples']
    for sample in all_samples:
        for row in sample['context']:
            key = f'source:{row["line"]}'
            row['navigation_id'] = key
    _apply_field_severity(grouped, total_boxes)
    grouped.sort(
        key=lambda group: (
            _SEVERITY_ORDER.get(str(group.get("field_severity", group["severity"])), 9),
            -int(group.get("field_priority", group["priority_score"])),
            int(group["first_line"]),
        )
    )
    counts = {
        "error": sum(1 for group in grouped if group.get("field_severity") == "error"),
        "warning": sum(1 for group in grouped if group.get("field_severity") == "warning"),
        "info": sum(1 for group in grouped if group.get("field_severity") == "info"),
        "raw_error": sum(1 for incident in incidents if incident.severity == "error"),
        "raw_warning": sum(1 for incident in incidents if incident.severity == "warning"),
        "raw_info": sum(1 for incident in incidents if incident.severity == "info"),
        "incidents": len(incidents),
        "types": len(grouped),
        "total_boxes": total_boxes,
        "analyzed_boxes": max(total_boxes, analysis['summary'].get('cycle_count', 0)),
    }
    return {
        "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "source": {'name': source_name, 'start': frames[0].timestamp_str if frames else '',
                   'end': frames[-1].timestamp_str if frames else '',
                   'duration': _duration_label(frames[0].timestamp, frames[-1].timestamp) if frames else ''},
        "measurements": analysis['summary'],
        "measurement_references": reference_lists,
        "orientation_references": orientation_lists,
        "measurement_examples": list(reference_samples.values()),
        "counts": counts,
        "verdict": _verdict(counts),
        "groups": grouped,
        "priority": _priority_groups([group for group in grouped if group['code'] != 'ORIENTATION']),
        "zones": _zone_summary(grouped),
        "camera": camera_stats,
        "unknown": unknown,
        "families": [
            {"id": "all", "label": _FAMILY_LABELS["all"]},
            {"id": "critical", "label": _FAMILY_LABELS["critical"]},
            {"id": "system", "label": _FAMILY_LABELS["system"]},
            {"id": "t2", "label": _FAMILY_LABELS["t2"]},
            {"id": "t4", "label": _FAMILY_LABELS["t4"]},
            {"id": "t5", "label": _FAMILY_LABELS["t5"]},
            {"id": "camera", "label": _FAMILY_LABELS["camera"]},
            {"id": "references", "label": _FAMILY_LABELS["references"]},
            {"id": "dimensions", "label": _FAMILY_LABELS["dimensions"]},
            {"id": "robot", "label": _FAMILY_LABELS["robot"]},
            {"id": "other", "label": _FAMILY_LABELS["other"]},
        ],
    }


def _copy_report_app_assets(output_dir: Path) -> bool:
    index_path = _REPORT_APP_BUILD_DIR / "index.html"
    next_dir = _REPORT_APP_BUILD_DIR / "_next"
    if not index_path.exists() or not next_dir.exists():
        return False
    target_next = output_dir / "_next"
    shutil.copytree(next_dir, target_next, dirs_exist_ok=True)
    return True


def _react_report_html(payload: dict[str, object]) -> str | None:
    index_path = _REPORT_APP_BUILD_DIR / "index.html"
    if not index_path.exists():
        return None
    template = index_path.read_text(encoding="utf-8")
    data_json = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c')
    data_script = (
        '<script id="trace-report-data">'
        f"window.__TRACE_REPORT_DATA__={json.dumps(data_json, ensure_ascii=False).replace('<', r'\u003c')};"
        "window.__TRACE_REPORT_DATA__=JSON.parse(window.__TRACE_REPORT_DATA__);"
        "</script>"
    )
    return template.replace("</head>", f"{data_script}</head>", 1)


def report_files_available(path: Path) -> bool:
    """Verifier le petit manifeste sans relire les preuves HTML/JSON."""
    path = Path(path)
    try:
        files = json.loads(path.with_suffix('.manifest.json').read_text(encoding='utf-8'))
        return bool(files) and all((path.parent / name).is_file() for name in files)
    except (OSError, ValueError, TypeError):
        return False


def write_diagnostic_report(
    incidents: list[DiagnosticIncident],
    output_dir: Path | None = None,
    frames: list[MachineState] | None = None,
    source_name: str = '',
) -> Path:
    output_dir = output_dir or reports_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    payload = build_report_payload(incidents, frames=frames, source_name=source_name)
    data_path = output_dir / f"report_data_{stamp}.json"
    data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    output_path = output_dir / f"diagnostic_report_{stamp}.html"
    html_text = _react_report_html(payload) if _copy_report_app_assets(output_dir) else None
    if not html_text:
        html_text = build_diagnostic_report_html(incidents, frames=frames, payload=payload)
    output_path.write_text(html_text, encoding="utf-8")
    assets = re.findall(r'(?:src|href)=[\"\']([^\"\']*_next/[^\"\']+)[\"\']', html_text)
    files = [output_path.name, data_path.name] + [html.unescape(a).split('?', 1)[0].removeprefix('./') for a in assets]
    output_path.with_suffix('.manifest.json').write_text(json.dumps(list(dict.fromkeys(files))), encoding='utf-8')
    return output_path


def build_diagnostic_report_html(incidents, frames=None, payload=None) -> str:
    payload = payload if payload is not None else build_report_payload(incidents, frames=frames)
    public = _REPORT_APP_DIR / 'public'
    script = (public / 'report-ui.js').read_text(encoding='utf-8')
    styles = (public / 'report-ui.css').read_text(encoding='utf-8')
    data = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c')
    return ('<!doctype html><html lang="fr"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Rapport diagnostic TraceAlphaViewer</title><style>' + styles +
            '</style></head><body><div id="report"></div><script>window.__TRACE_REPORT_DATA__=' +
            data + ';</script><script>' + script +
            '</script><script>TraceReport.mount(document.getElementById("report"),window.__TRACE_REPORT_DATA__);</script></body></html>')
