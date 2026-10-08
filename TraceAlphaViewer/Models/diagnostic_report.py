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


def _metric_from_summary(summary: str, code: str, occurrence_count: int) -> str:
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
    if code == "ALPHA_CARD_RESET":
        return "system"
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
    if code == "C9_WIDTH_INVALID":
        return "La largeur T5 est invalide alors que C9 detecte une presence ; la boite peut etre mal mesuree ou mal passee."
    if code == "CUBESTOP_C4_BLOCKED":
        return "Le passage EA/C4 vers T3 ne se libere pas ; la boite reste sur C4 malgre la demande de transfert."
    if code == "UNKNOWN":
        return "Des boites sortent sans reference fiable ; le tri et le suivi produit deviennent incertains."
    if code == "CAM-NO-READ":
        return "Une camera attendue ne contribue pas ; les non lectures risquent d'augmenter."
    if code == "ORIENTATION":
        return "Les dimensions existent mais ne sont pas dans le bon sens ; ce n'est pas d'abord un defaut capteur."
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
    if code == "T5_STALE_UNMEASURED_BOX":
        return ["Boite T5 non mesuree reste en base et provoque des manques de place."]
    if code == "ORIENTATION":
        return ["Dimensions compatibles mais permutees: verifier le sens de presentation de la boite."]
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
    belt = str(group["belt"])
    count = int(group["occurrence_count"])
    ratio = _ratio(count, total_boxes)

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
            "Les mesures Alpha ne correspondent pas aux dimensions BdD sur plusieurs axes.",
            "Boite bloquee, mauvais tassage T5, mesure perturbee par une boite precedente, probleme mecanique T4/T5 ou capteur.",
            "Chercher un blocage physique et verifier C6, C9, LzB ainsi que l'entrainement T4/T5.",
        )
    if code == "T5_WIDTH":
        action = "Traiter avec le probleme C9 massif deja detecte." if c9_massive else "Verifier C9/T5 et refaire une mesure controlee."
        return (
            "La largeur mesuree ne colle pas a la reference BdD.",
            "Suspicion mesure C9/T5 ou passage boite incorrect devant C9.",
            action,
        )
    if belt == "T2" and code == "-88":
        return (
            "T2 indique qu'une boite est deja sur C4 au moment du transfert.",
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
            "Les dimensions existent mais sont permutees.",
            "Boite dans le mauvais sens ou sur la tranche, pas un defaut capteur en premier diagnostic.",
            "Verifier la presentation physique de la reference.",
        )
    if ratio >= 0.10 and code in _DIMENSION_CODES:
        return (
            "Anomalie dimensionnelle recurrente.",
            "Mesure ou presentation boite instable.",
            "Verifier la zone de mesure correspondant a l'axe en erreur.",
        )
    return (
        str(group["impact"]),
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
    if code == "GLOBAL":
        return "error" if count >= 8 or ratio >= 0.15 else "warning"
    if code == "T5_WIDTH":
        return "error" if c9_massive else "warning"
    if belt == "T2" and code == "-88":
        return "error" if count >= 3 else "warning"
    if belt == "T3" and code == "-43":
        return "error" if count >= 2 else "warning"
    if belt == "T3" and code == "-48":
        return "warning" if count > 1 else "info"
    if code == "ORIENTATION":
        return "warning"
    if code in {"UNKNOWN", "CAM-NO-READ"}:
        return "warning"
    if code in _DIMENSION_CODES:
        return "warning"
    if str(group["severity"]) == "error" and str(code).startswith("-"):
        return "warning"
    return str(group["severity"])


def _field_priority_score(group: dict[str, object]) -> int:
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
        "CAM-NO-READ": 60,
        "T4_LENGTH": 55,
        "T5_HEIGHT": 55,
        "ORIENTATION": 35,
    }.get(code, 0)
    if belt == "T2" and code == "-88":
        code_bonus = 70
    elif belt == "T3" and code == "-48":
        code_bonus = 20
    return severity_score + code_bonus + min(int(group["occurrence_count"]), 60)


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
        else:
            group["affected_ratio"] = _ratio(count, total_boxes)
            group["affected_label"] = _affected_label(count, total_boxes)
        group["field_explanation"] = explanation
        group["field_impact"] = impact
        group["field_action"] = action
        group["field_priority"] = _field_priority_score(group)


def _priority_score(group: dict[str, object]) -> int:
    severity_score = {"error": 500, "warning": 190, "info": 80}.get(str(group["severity"]), 0)
    code = str(group["code"])
    code_bonus = {
        "C9_WIDTH_INVALID": 95,
        "CUBESTOP_C4_BLOCKED": 100,
        "ALPHA_CARD_RESET": 120,
        "UNKNOWN": 85,
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
        if len(group["incidents"]) < 3:  # type: ignore[arg-type]
            group["incidents"].append(_incident_payload(incident))  # type: ignore[index, union-attr]
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
        group["metric"] = _metric_from_summary(str(group["summary"]), code, int(group["occurrence_count"]))
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
            "GLOBAL", "T5_WIDTH", "UNKNOWN", "CAM-NO-READ",
        }
        important_et = (str(group["belt"]), str(group["code"])) in {("T2", "-88"), ("T3", "-43"), ("T3", "-48")}
        if (important_code or important_et) and key not in keys:
            priority.append(group)
            keys.add(key)
    return priority[:8]


def _zone_summary(grouped: list[dict[str, object]]) -> list[dict[str, object]]:
    order = ["system", "camera", "t2", "t4", "t5", "dimensions", "robot", "other"]
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
            "title": "Intervention terrain prioritaire",
            "text": "La trace contient des problemes terrain massifs ou bloquants. Traiter ces points avant les alertes isolees.",
        }
    if counts["warning"] > 0:
        return {
            "level": "warning",
            "label": "A surveiller",
            "title": "Anomalies actionnables",
            "text": "Aucun critique detecte, mais plusieurs controles terrain sont recommandes.",
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
    }


def build_report_payload(
    incidents: list[DiagnosticIncident],
    frames: list[MachineState] | None = None,
) -> dict[str, object]:
    camera_stats = camera_report_stats(frames) if frames is not None else _empty_camera_stats()
    total_boxes = int(camera_stats.get("total_boxes") or 0)
    grouped = _group_incidents(incidents)
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
    }
    return {
        "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "counts": counts,
        "verdict": _verdict(counts),
        "groups": grouped,
        "priority": _priority_groups(grouped),
        "zones": _zone_summary(grouped),
        "camera": camera_stats,
        "families": [
            {"id": "all", "label": _FAMILY_LABELS["all"]},
            {"id": "critical", "label": _FAMILY_LABELS["critical"]},
            {"id": "system", "label": _FAMILY_LABELS["system"]},
            {"id": "t4", "label": _FAMILY_LABELS["t4"]},
            {"id": "t5", "label": _FAMILY_LABELS["t5"]},
            {"id": "camera", "label": _FAMILY_LABELS["camera"]},
            {"id": "dimensions", "label": _FAMILY_LABELS["dimensions"]},
        ],
    }


def _copy_report_app_assets(output_dir: Path) -> bool:
    index_path = _REPORT_APP_BUILD_DIR / "index.html"
    next_dir = _REPORT_APP_BUILD_DIR / "_next"
    if not index_path.exists() or not next_dir.exists():
        return False
    target_next = output_dir / "_next"
    if target_next.exists():
        shutil.rmtree(target_next)
    shutil.copytree(next_dir, target_next)
    return True


def _react_report_html(payload: dict[str, object]) -> str | None:
    index_path = _REPORT_APP_BUILD_DIR / "index.html"
    if not index_path.exists():
        return None
    template = index_path.read_text(encoding="utf-8")
    data_json = json.dumps(payload, ensure_ascii=False)
    data_script = (
        '<script id="trace-report-data">'
        f"window.__TRACE_REPORT_DATA__={json.dumps(data_json, ensure_ascii=False)};"
        "window.__TRACE_REPORT_DATA__=JSON.parse(window.__TRACE_REPORT_DATA__);"
        "</script>"
    )
    return template.replace("</head>", f"{data_script}</head>", 1)


def write_diagnostic_report(
    incidents: list[DiagnosticIncident],
    output_dir: Path | None = None,
    frames: list[MachineState] | None = None,
) -> Path:
    output_dir = output_dir or reports_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = build_report_payload(incidents, frames=frames)
    data_path = output_dir / f"report_data_{stamp}.json"
    data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    output_path = output_dir / f"diagnostic_report_{stamp}.html"
    if _copy_report_app_assets(output_dir):
        html_text = _react_report_html(payload)
        if html_text:
            output_path.write_text(html_text, encoding="utf-8")
            return output_path

    output_path.write_text(build_diagnostic_report_html(incidents, frames=frames), encoding="utf-8")
    return output_path


def build_diagnostic_report_html(
    incidents: list[DiagnosticIncident],
    frames: list[MachineState] | None = None,
) -> str:
    payload = build_report_payload(incidents, frames=frames)
    data_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Rapport diagnostic TraceAlphaViewer</title>
  <style>{_CSS}</style>
</head>
<body>
  <header class="topbar no-print">
    <div>
      <span class="eyebrow">TraceAlphaViewer</span>
      <h1>Rapport diagnostic terrain</h1>
      <p id="generated" class="muted"></p>
    </div>
    <button type="button" class="primary-btn" onclick="downloadGlobalPdf()">Exporter PDF</button>
  </header>
  <main>
    <section id="verdict" class="verdict"></section>
    <section id="summary" class="summary-grid"></section>
    <section class="layout">
      <aside class="side-panel">
        <h2>Zones a controler</h2>
        <div id="zones"></div>
      </aside>
      <section class="main-panel">
        <div class="section-title">
          <div>
            <span class="eyebrow">A traiter en premier</span>
            <h2>Actions prioritaires</h2>
          </div>
          <span class="hint">Classement terrain: gravite, diagnostic metier, volume.</span>
        </div>
        <div id="priority"></div>
      </section>
    </section>
    <section class="toolbar no-print">
      <div id="quick-filters" class="quick-filters"></div>
      <input id="search" type="search" placeholder="Rechercher zone, code, action, preuve...">
      <span id="visible-count" class="hint"></span>
    </section>
    <section id="camera-section" class="camera-panel">
      <div class="section-title">
        <div>
          <span class="eyebrow">Lecture cameras</span>
          <h2>Performance des cameras</h2>
        </div>
        <span class="hint">Classement de la camera qui lit le plus a celle qui lit le moins.</span>
      </div>
      <div id="camera-chart"></div>
    </section>
    <section class="grouped-panel">
      <div class="section-title">
        <h2>Diagnostics detailles</h2>
        <span class="hint">Ouvrir une carte pour voir causes, controles et preuves.</span>
      </div>
      <div id="groups"></div>
    </section>
  </main>
  <script id="report-data" type="application/json">{html.escape(data_json, quote=False)}</script>
  <script>{_JS}</script>
</body>
</html>
"""


_CSS = r"""
:root {
  color-scheme: light;
  --bg: #f4f6f8;
  --panel: #ffffff;
  --panel-soft: #f8fafc;
  --text: #17212f;
  --muted: #667085;
  --line: #d8dee8;
  --line-strong: #b7c1cf;
  --error: #b4232f;
  --error-bg: #fff1f2;
  --warning: #a15c00;
  --warning-bg: #fff7e6;
  --info: #2563a7;
  --info-bg: #eef6ff;
  --ok: #227950;
  --ok-bg: #ecfdf3;
  --accent: #244f84;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: "Segoe UI", Arial, sans-serif;
  line-height: 1.38;
}
h1, h2, h3, p { margin: 0; }
h1 { font-size: 24px; }
h2 { font-size: 18px; }
h3 { font-size: 15px; }
main { max-width: 1360px; margin: 0 auto; padding: 22px; }
.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  padding: 16px 24px;
  background: rgba(255, 255, 255, .97);
  border-bottom: 1px solid var(--line);
  box-shadow: 0 5px 18px rgba(16, 24, 40, .07);
}
.eyebrow {
  color: var(--muted);
  display: inline-block;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.muted, .hint, .meta { color: var(--muted); }
.primary-btn, input, .filter-btn {
  border: 1px solid var(--line);
  border-radius: 7px;
  font: inherit;
}
.primary-btn {
  background: var(--accent);
  color: #fff;
  cursor: pointer;
  font-weight: 800;
  padding: 10px 14px;
}
input {
  background: var(--panel);
  color: var(--text);
  min-width: 280px;
  padding: 10px 12px;
}
.verdict {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 16px;
  align-items: center;
  margin-bottom: 14px;
  padding: 18px;
  border: 1px solid var(--line);
  border-left: 8px solid var(--info);
  border-radius: 8px;
  background: var(--panel);
}
.verdict.critical { border-left-color: var(--error); background: var(--error-bg); }
.verdict.warning { border-left-color: var(--warning); background: var(--warning-bg); }
.verdict.ok { border-left-color: var(--ok); background: var(--ok-bg); }
.verdict-label {
  padding: 8px 10px;
  border-radius: 6px;
  color: #fff;
  background: var(--accent);
  font-weight: 900;
}
.verdict.critical .verdict-label { background: var(--error); }
.verdict.warning .verdict-label { background: var(--warning); }
.verdict.ok .verdict-label { background: var(--ok); }
.summary-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(130px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}
.stat, .side-panel, .main-panel, .toolbar, .camera-panel, .grouped-panel, .card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
}
.stat {
  padding: 13px 14px;
}
.stat strong {
  display: block;
  font-size: 26px;
  line-height: 1;
}
.layout {
  display: grid;
  grid-template-columns: 330px minmax(0, 1fr);
  gap: 14px;
  margin-bottom: 14px;
}
.side-panel, .main-panel, .toolbar, .camera-panel, .grouped-panel {
  padding: 15px;
}
.section-title {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  align-items: baseline;
  margin-bottom: 12px;
}
.zone-card {
  border-top: 1px solid var(--line);
  padding: 11px 0;
}
.zone-card:first-child { border-top: 0; }
.zone-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-weight: 900;
}
.zone-card p { margin-top: 5px; }
.priority-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.priority-card {
  border: 1px solid var(--line);
  border-left: 6px solid var(--info);
  border-radius: 8px;
  padding: 13px;
  background: var(--panel-soft);
}
.priority-card.error { border-left-color: var(--error); background: var(--error-bg); }
.priority-card.warning { border-left-color: var(--warning); background: var(--warning-bg); }
.priority-card.info { border-left-color: var(--info); background: var(--info-bg); }
.priority-card h3 { margin: 7px 0 6px; }
.badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  border: 1px solid var(--line);
  padding: 4px 7px;
  font-size: 12px;
  font-weight: 900;
}
.severity-error { color: var(--error); background: var(--error-bg); border-color: #f0b7bd; }
.severity-warning { color: var(--warning); background: var(--warning-bg); border-color: #e9ca8d; }
.severity-info { color: var(--info); background: var(--info-bg); border-color: #bdd7f2; }
.family-badge { color: #344054; background: #eef2f7; }
.metric { color: var(--accent); font-weight: 900; }
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-bottom: 14px;
}
.camera-panel {
  margin-bottom: 14px;
}
.camera-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 310px;
  gap: 14px;
}
.camera-bars {
  display: grid;
  gap: 10px;
}
.camera-row {
  display: grid;
  grid-template-columns: 145px minmax(0, 1fr) 84px;
  gap: 10px;
  align-items: center;
}
.camera-label {
  font-weight: 900;
}
.bar-track {
  height: 20px;
  overflow: hidden;
  border-radius: 5px;
  border: 1px solid var(--line);
  background: #eef2f7;
}
.bar-fill {
  height: 100%;
  min-width: 3px;
  border-radius: 5px;
  background: var(--info);
}
.bar-fill.reader-cb1 { background: #2e7d55; }
.bar-fill.reader-cb2 { background: #2563a7; }
.bar-fill.status-zero { background: var(--error); }
.bar-fill.status-weak { background: var(--warning); }
.camera-count {
  font-weight: 900;
  text-align: right;
}
.camera-side {
  display: grid;
  gap: 10px;
}
.reader-stat, .camera-alert {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px;
  background: var(--panel-soft);
}
.camera-alert.zero { background: var(--error-bg); border-color: #f0b7bd; }
.camera-alert.weak { background: var(--warning-bg); border-color: #e9ca8d; }
.quick-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}
.filter-btn {
  background: #fff;
  color: #344054;
  cursor: pointer;
  font-weight: 800;
  padding: 9px 11px;
}
.filter-btn.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
.card {
  margin: 10px 0;
  overflow: hidden;
}
.card-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(170px, auto);
  gap: 12px;
  padding: 14px;
  cursor: pointer;
}
.card-head:hover { background: var(--panel-soft); }
.card-title { margin: 7px 0 5px; }
.card-body {
  display: none;
  border-top: 1px solid var(--line);
  background: #fcfdff;
  padding: 14px;
}
.card.open .card-body { display: block; }
.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.detail-box {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 11px;
  background: #fff;
}
.detail-box h4 {
  margin: 0 0 7px;
  font-size: 13px;
  text-transform: uppercase;
  color: #344054;
}
ul { margin: 6px 0 0 18px; padding: 0; }
li + li { margin-top: 4px; }
.proof-lines {
  margin-top: 8px;
  color: var(--muted);
  font-family: Consolas, monospace;
  font-size: 12px;
}
.sample {
  border-top: 1px solid var(--line);
  margin-top: 10px;
  padding-top: 10px;
}
@media (max-width: 960px) {
  .layout { grid-template-columns: 1fr; }
  .priority-list { grid-template-columns: 1fr; }
  .summary-grid { grid-template-columns: repeat(2, minmax(130px, 1fr)); }
  .card-head { grid-template-columns: 1fr; }
  .detail-grid { grid-template-columns: 1fr; }
  .camera-layout { grid-template-columns: 1fr; }
  .camera-row { grid-template-columns: 1fr; }
  .camera-count { text-align: left; }
  input { min-width: 100%; }
}
@media print {
  .no-print, .toolbar { display: none !important; }
  body { background: #fff; }
  main { padding: 0; }
  .topbar { position: static; box-shadow: none; }
  .card-body { display: block; }
}
"""


_JS = r"""
const data = JSON.parse(document.getElementById('report-data').textContent);
let activeFilter = 'all';

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[ch]));
const fieldSeverity = (group) => group.field_severity || group.severity || 'info';
const fieldSeverityLabel = (group) => group.field_severity_label || group.severity_label || fieldSeverity(group);
const fieldAction = (group) => group.field_action || group.action || group.title || '-';
const fieldImpact = (group) => group.field_impact || group.impact || '-';
const fieldZone = (group) => group.field_zone_label || group.family_label || '-';

document.getElementById('generated').textContent = `Genere le ${data.generated_at}`;

function renderVerdict() {
  const verdict = data.verdict;
  document.getElementById('verdict').className = `verdict ${esc(verdict.level)}`;
  document.getElementById('verdict').innerHTML = `
    <span class="verdict-label">${esc(verdict.label)}</span>
    <div>
      <h2>${esc(verdict.title)}</h2>
      <p class="muted">${esc(verdict.text)}</p>
    </div>
    <strong>${esc(data.counts.types)} type(s)</strong>
  `;
}

function renderSummary() {
  const labels = [
    ['Critiques', data.counts.error],
    ['Alertes', data.counts.warning],
    ['Infos', data.counts.info],
    ['Incidents', data.counts.incidents],
    ['Types', data.counts.types],
  ];
  document.getElementById('summary').innerHTML = labels.map(([label, value]) =>
    `<div class="stat"><strong>${esc(value)}</strong><span class="muted">${esc(label)}</span></div>`
  ).join('');
}

function renderZones() {
  const html = data.zones.length ? data.zones.map(zone => `
    <article class="zone-card">
      <div class="zone-head">
        <span>${esc(zone.label)}</span>
        <span>${esc(zone.groups)} type(s)</span>
      </div>
      <p class="meta">${esc(zone.occurrences)} occurrence(s), ${esc(zone.errors)} critique(s), ${esc(zone.warnings)} alerte(s)</p>
      <p>${esc(zone.top_action || 'Controle terrain recommande')}</p>
    </article>
  `).join('') : '<p>Aucune zone en anomalie.</p>';
  document.getElementById('zones').innerHTML = html;
}

function renderCameraChart() {
  const target = document.getElementById('camera-chart');
  const camera = data.camera || {};
  if (!camera.available) {
    target.innerHTML = '<p class="muted">Donnees cameras indisponibles pour ce rapport.</p>';
    return;
  }
  const chart = camera.chart || [];
  const maxCount = Math.max(1, ...chart.map(item => Number(item.success_count || 0)));
  const bars = chart.length ? chart.map(item => {
    const count = Number(item.success_count || 0);
    const pct = Math.max(0, Math.round((count / maxCount) * 100));
    const readerClass = String(item.reader || '').toLowerCase();
    const statusClass = `status-${esc(item.status || 'ok')}`;
    return `
      <div class="camera-row">
        <div>
          <div class="camera-label">${esc(item.label)}</div>
          <div class="meta">${esc(item.status_label)}</div>
        </div>
        <div class="bar-track" title="${esc(count)} lecture(s) reussie(s)">
          <div class="bar-fill reader-${esc(readerClass)} ${statusClass}" style="width:${pct}%"></div>
        </div>
        <div class="camera-count">${esc(count)} lecture(s)</div>
      </div>
    `;
  }).join('') : '<p class="muted">Aucune reussite camera observee.</p>';

  const readerStats = (camera.reader_stats || []).map(item => `
    <article class="reader-stat">
      <strong>${esc(item.reader)}</strong>
      <p class="meta">Cameras attendues: ${esc(item.expected_cameras)}</p>
      <p>${esc(item.zero_code_label)} lectures a 0 code</p>
    </article>
  `).join('');
  const alerts = (camera.alerts || []).length
    ? (camera.alerts || []).map(item => `
      <article class="camera-alert ${esc(item.status)}">
        <strong>${esc(item.label)}</strong>
        <p>${esc(item.status_label)} (${esc(item.success_count)} reussite(s))</p>
      </article>
    `).join('')
    : '<article class="camera-alert"><strong>Aucune camera a zero</strong><p class="meta">Toutes les cameras attendues contribuent dans cette trace.</p></article>';

  target.innerHTML = `
    <div class="camera-layout">
      <div>
        <p class="meta">${esc(camera.note)} Total boites vues: ${esc(camera.total_boxes)}.</p>
        <div class="camera-bars">${bars}</div>
      </div>
      <aside class="camera-side">
        <div>
          <h3>Lecteurs</h3>
          ${readerStats}
        </div>
        <div>
          <h3>Alertes cameras</h3>
          ${alerts}
        </div>
      </aside>
    </div>
  `;
}

function badges(group) {
  return `
    <div class="badges">
      <span class="badge severity-${esc(fieldSeverity(group))}">${esc(fieldSeverityLabel(group))}</span>
      <span class="badge family-badge">${esc(fieldZone(group))}</span>
      <span class="badge family-badge">${esc(group.belt)} / ${esc(group.code)}</span>
    </div>
  `;
}

function priorityCard(group, index) {
  return `
    <article class="priority-card ${esc(fieldSeverity(group))}">
      ${badges(group)}
      <h3>${esc(index)}. ${esc(fieldAction(group))}</h3>
      <p class="metric">${esc(group.affected_label || group.metric)}</p>
      <p>${esc(fieldImpact(group))}</p>
      <p class="meta">${esc(group.evidence)}</p>
    </article>
  `;
}

function renderPriority() {
  document.getElementById('priority').innerHTML = data.priority.length
    ? `<div class="priority-list">${data.priority.map((group, index) => priorityCard(group, index + 1)).join('')}</div>`
    : '<p>Aucun incident detecte.</p>';
}

function list(items) {
  const values = (items || []).filter(Boolean);
  return values.length ? `<ul>${values.map(item => `<li>${esc(item)}</li>`).join('')}</ul>` : '<p class="muted">Non renseigne.</p>';
}

function samples(group) {
  const incidents = group.incidents || [];
  return incidents.slice(0, 3).map(incident => `
    <article class="sample">
      <strong>${esc(incident.start_time_str)} -> ${esc(incident.end_time_str)}</strong>
      <p class="meta">L.${esc(incident.first_line)} -> L.${esc(incident.last_line)} | ${esc(incident.count)} occurrence(s)</p>
      <p>${esc(incident.summary || '-')}</p>
      <p class="proof-lines">Lignes utiles: ${(incident.event_lines || []).slice(0, 10).map(line => `L.${esc(line)}`).join(', ') || '-'}</p>
    </article>
  `).join('');
}

function groupCard(group, index) {
  const searchText = `${fieldSeverityLabel(group)} ${fieldZone(group)} ${group.belt} ${group.code} ${group.title} ${fieldAction(group)} ${fieldImpact(group)} ${group.field_explanation || ''} ${group.summary} ${(group.business_lines || []).join(' ')}`.toLowerCase();
  return `
    <article class="card"
      data-severity="${esc(fieldSeverity(group))}"
      data-family="${esc(group.family)}"
      data-search="${esc(searchText)}">
      <div class="card-head" onclick="this.parentElement.classList.toggle('open')">
        <div>
          ${badges(group)}
          <h3 class="card-title">${esc(index)}. ${esc(fieldAction(group))}</h3>
          <p>${esc(fieldImpact(group))}</p>
          <p class="meta">${esc(group.evidence)} | ${esc(group.incident_count)} diagnostic(s)</p>
        </div>
        <div class="metric">${esc(group.affected_label || group.metric)}</div>
      </div>
      <div class="card-body">
        <section class="detail-box sample">
          <h4>Lecture terrain</h4>
          <p><strong>${esc(group.field_explanation || fieldImpact(group))}</strong></p>
          <p>${esc(fieldAction(group))}</p>
        </section>
        <div class="detail-grid">
          <section class="detail-box">
            <h4>Constat</h4>
            ${list(group.business_lines)}
          </section>
          <section class="detail-box">
            <h4>Impact probable</h4>
            <p>${esc(fieldImpact(group))}</p>
          </section>
          <section class="detail-box">
            <h4>Causes probables</h4>
            ${list(group.probable_causes)}
          </section>
          <section class="detail-box">
            <h4>Controles a faire</h4>
            ${list(group.checks)}
          </section>
        </div>
        <section class="detail-box sample">
          <h4>Preuves trace</h4>
          ${samples(group)}
        </section>
      </div>
    </article>
  `;
}

function renderFilters() {
  const target = document.getElementById('quick-filters');
  target.innerHTML = data.families.map(item =>
    `<button type="button" class="filter-btn ${item.id === activeFilter ? 'active' : ''}" data-filter="${esc(item.id)}">${esc(item.label)}</button>`
  ).join('');
  target.querySelectorAll('.filter-btn').forEach(button => {
    button.addEventListener('click', () => {
      activeFilter = button.dataset.filter;
      renderFilters();
      applyFilters();
      if (activeFilter === 'camera') {
        document.getElementById('camera-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });
}

function renderGroups() {
  document.getElementById('groups').innerHTML =
    data.groups.map((group, index) => groupCard(group, index + 1)).join('');
  applyFilters();
}

function applyFilters() {
  const text = document.getElementById('search').value.trim().toLowerCase();
  let visible = 0;
  document.querySelectorAll('#groups .card').forEach(card => {
    const quickOk = activeFilter === 'all'
      || (activeFilter === 'critical' && card.dataset.severity === 'error')
      || card.dataset.family === activeFilter;
    const textOk = !text || card.dataset.search.includes(text);
    const ok = quickOk && textOk;
    card.style.display = ok ? '' : 'none';
    if (ok) visible += 1;
  });
  document.getElementById('visible-count').textContent = `${visible} diagnostic(s) visible(s)`;
}

document.getElementById('search').addEventListener('input', applyFilters);

function pdfEscape(text) {
  return String(text ?? '')
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^\x20-\x7E]/g, ' ')
    .replace(/\\/g, '\\\\')
    .replace(/\(/g, '\\(')
    .replace(/\)/g, '\\)');
}

function wrapText(text, maxChars) {
  const words = String(text ?? '').replace(/\s+/g, ' ').trim().split(' ');
  const lines = [];
  let line = '';
  words.forEach(word => {
    if (!word) return;
    const candidate = line ? `${line} ${word}` : word;
    if (candidate.length > maxChars && line) {
      lines.push(line);
      line = word;
    } else {
      line = candidate;
    }
  });
  if (line) lines.push(line);
  return lines.length ? lines : [''];
}

function pdfTextLine(text, x, y, size = 10, bold = false) {
  const font = bold ? 'F2' : 'F1';
  return `BT /${font} ${size} Tf ${x} ${y} Td (${pdfEscape(text)}) Tj ET\n`;
}

function pdfRect(x, y, w, h, color = '0.97 0.98 0.99', stroke = '0.80 0.84 0.88') {
  return `q ${color} rg ${stroke} RG ${x} ${y} ${w} ${h} re B Q\n`;
}

function pdfRule(x, y, w, color = '0.72 0.76 0.80') {
  return `q ${color} RG ${x} ${y} m ${x + w} ${y} l S Q\n`;
}

function pdfSeverityColor(severity) {
  if (severity === 'error') return '1 0.93 0.94';
  if (severity === 'warning') return '1 0.97 0.88';
  return '0.93 0.96 1';
}

function pdfLines() {
  const lines = [
    { kind: 'hero', text: `${data.verdict.label} - ${data.verdict.title}`, size: 16, bold: true, gap: 54 },
    { text: data.verdict.text, size: 10, gap: 18 },
    { text: `Critiques: ${data.counts.error} | Alertes: ${data.counts.warning} | Infos: ${data.counts.info} | Types: ${data.counts.types} | Incidents: ${data.counts.incidents}`, size: 10, bold: true, gap: 26 },
    { kind: 'section', text: 'Actions prioritaires', size: 13, bold: true, gap: 24 },
  ];
  const addGroup = (group, index) => {
    lines.push({ kind: 'group', severity: fieldSeverity(group), text: `${index}. [${fieldSeverityLabel(group)}] ${fieldZone(group)} - ${fieldAction(group)}`, size: 10, bold: true, gap: 24 });
    lines.push({ text: `${group.affected_label || group.metric} | ${group.evidence}`, size: 9, gap: 12 });
    wrapText(fieldImpact(group), 92).forEach(line => lines.push({ text: line, size: 9, gap: 10 }));
    wrapText(group.field_explanation || fieldAction(group), 92).forEach(line => lines.push({ text: line, size: 9, gap: 10 }));
    (group.checks || []).slice(0, 3).forEach(check => {
      wrapText(`Controle: ${check}`, 90).forEach(line => lines.push({ text: line, size: 9, gap: 10 }));
    });
    lines.push({ text: '', size: 9, gap: 7 });
  };
  if (data.priority.length) {
    data.priority.forEach((group, index) => addGroup(group, index + 1));
  } else {
    lines.push({ text: 'Aucun incident detecte.', size: 10, gap: 16 });
  }
  if (data.camera && data.camera.available) {
    lines.push({ kind: 'section', text: 'Lecture cameras', size: 13, bold: true, gap: 24 });
    (data.camera.chart || []).slice(0, 8).forEach(item => {
      lines.push({
        text: `${item.label}: ${item.success_count} lecture(s) reussie(s) - ${item.status_label}`,
        size: 9,
        gap: 11,
      });
    });
    (data.camera.reader_stats || []).forEach(item => {
      lines.push({
        text: `${item.reader}: ${item.zero_code_label} lectures a 0 code, cameras ${item.expected_cameras}`,
        size: 9,
        gap: 11,
      });
    });
  }
  lines.push({ kind: 'section', text: 'Diagnostics par zone', size: 13, bold: true, gap: 24 });
  data.groups.forEach((group, index) => addGroup(group, index + 1));
  return lines;
}

function buildPdf(lines) {
  const pageWidth = 595;
  const pageHeight = 842;
  const marginLeft = 42;
  const marginTop = 770;
  const bottom = 58;
  const pages = [];
  let y = marginTop;
  let content = '';
  let pageNo = 1;

  const footer = () => {
    content += pdfRule(42, 52, 511, '0.82 0.85 0.88');
    content += pdfTextLine(`TraceAlphaViewer - page ${pageNo}`, 42, 35, 8, false);
  };
  const newPage = () => {
    footer();
    pages.push(content);
    content = pdfTextLine('Rapport diagnostic terrain', 42, 808, 14, true);
    y = marginTop;
    pageNo += 1;
  };

  content += pdfRect(36, 782, 523, 48, '0.93 0.96 1', '0.72 0.80 0.90');
  content += pdfTextLine('Rapport diagnostic terrain TraceAlphaViewer', 48, 808, 16, true);
  content += pdfTextLine(`Genere le ${data.generated_at}`, 48, 792, 9, false);

  lines.forEach(item => {
    if (item.kind === 'hero') {
      if (y - 54 < bottom) newPage();
      content += pdfRect(42, y - 38, 511, 42, '0.98 0.99 1', '0.78 0.82 0.88');
      content += pdfTextLine(item.text, 54, y - 12, item.size, true);
      y -= item.gap;
      return;
    }
    if (item.kind === 'section') {
      if (y - 30 < bottom) newPage();
      content += pdfRule(42, y + 6, 511);
      content += pdfTextLine(item.text, 42, y - 10, item.size, true);
      y -= item.gap;
      return;
    }
    if (item.kind === 'group') {
      if (y - 54 < bottom) newPage();
      content += pdfRect(42, y - 42, 511, 46, pdfSeverityColor(item.severity), '0.78 0.82 0.88');
      content += pdfTextLine(item.text, 54, y - 12, item.size, true);
      y -= item.gap;
      return;
    }
    wrapText(item.text, item.size >= 13 ? 70 : 96).forEach((line, idx, arr) => {
      const gap = idx === arr.length - 1 ? item.gap : Math.max(10, item.size + 2);
      if (y - gap < bottom) newPage();
      content += pdfTextLine(line, marginLeft, y, item.size, item.bold);
      y -= gap;
    });
  });
  if (content) {
    footer();
    pages.push(content);
  }

  const objects = [];
  const addObject = body => {
    objects.push(body);
    return objects.length;
  };
  const fontRegularId = addObject('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>');
  const fontBoldId = addObject('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>');
  const pageIds = [];
  const pagePlaceholders = [];

  pages.forEach(pageContent => {
    const stream = `<< /Length ${pageContent.length} >>\nstream\n${pageContent}endstream`;
    const contentId = addObject(stream);
    const placeholder = `__PARENT_${pageIds.length}__`;
    const pageId = addObject(
      `<< /Type /Page /Parent ${placeholder} 0 R /MediaBox [0 0 ${pageWidth} ${pageHeight}] ` +
      `/Resources << /Font << /F1 ${fontRegularId} 0 R /F2 ${fontBoldId} 0 R >> >> ` +
      `/Contents ${contentId} 0 R >>`
    );
    pageIds.push(pageId);
    pagePlaceholders.push(placeholder);
  });

  const pagesId = addObject(`<< /Type /Pages /Kids [${pageIds.map(id => `${id} 0 R`).join(' ')}] /Count ${pageIds.length} >>`);
  const catalogId = addObject(`<< /Type /Catalog /Pages ${pagesId} 0 R >>`);
  pagePlaceholders.forEach((placeholder, idx) => {
    const pageObjectId = pageIds[idx];
    objects[pageObjectId - 1] = objects[pageObjectId - 1].replace(placeholder, String(pagesId));
  });

  let pdf = '%PDF-1.4\n';
  const offsets = [0];
  objects.forEach((body, idx) => {
    offsets.push(pdf.length);
    pdf += `${idx + 1} 0 obj\n${body}\nendobj\n`;
  });
  const xref = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (let idx = 1; idx <= objects.length; idx += 1) {
    pdf += `${String(offsets[idx]).padStart(10, '0')} 00000 n \n`;
  }
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root ${catalogId} 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return pdf;
}

function downloadGlobalPdf() {
  const pdf = buildPdf(pdfLines());
  const blob = new Blob([pdf], { type: 'application/pdf' });
  const stamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '');
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `diagnostic_terrain_${stamp}.pdf`;
  document.body.appendChild(link);
  link.click();
  setTimeout(() => {
    URL.revokeObjectURL(link.href);
    link.remove();
  }, 1000);
}

renderVerdict();
renderSummary();
renderZones();
renderPriority();
renderCameraChart();
renderFilters();
renderGroups();
"""
