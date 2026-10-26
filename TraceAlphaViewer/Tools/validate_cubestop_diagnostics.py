from __future__ import annotations

import sys
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "TraceAlphaViewer"))

from Models.diagnostic import build_diagnostics
from Parser.trace_parser import parse_file


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _events_for(frames) -> list:
    events = []
    seen = set()
    for frame in frames:
        for event in frame.events:
            key = (event.line_num, event.kind, event.title)
            if key in seen:
                continue
            seen.add(key)
            events.append(event)
    return sorted(events, key=lambda event: (event.line_num, event.kind, event.title))


def _diagnostics_for(path: Path):
    frames = parse_file(str(path), min_dt=0.0)
    events = _events_for(frames)
    return frames, build_diagnostics(frames, events)


def _validate_fixtures() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / 'fictive.old'
        prefix = [
            'CubeStop:Y',
            'mvt CubeStop vers le BAS',
            'mvt CubeStop vers le HAUT',
            'tEA-T3: DEM-TRSF C4:1 C5:0 fgBfinT3:0 eT3:49 pT3:-210mm',
            'tEA-T3: WAIT-FIN-TRSF C4:1 C5:0 fgBfinT3:0 eT3:44 pT3:-300mm',
        ]

        def run(rows):
            path.write_text(''.join(f'  01|09:00:{i:02d}.0 {text}\n'
                                    for i, text in enumerate(rows)), encoding='latin-1')
            return _diagnostics_for(path)

        frames, incidents = run(prefix + [
            'tEA-T3: WAIT-FIN-TRSF C4:0 C5:1 fgBfinT3:0 eT3:44 pT3:-468mm',
            'le transfert (EA->T3) est termine',
        ])
        positions = {frame.cubestop_position for frame in frames if frame.cubestop_present}
        _check({'BAS', 'HAUT'} <= positions, 'Positions CubeStop fictives absentes')
        _check(not any(i.code == 'CUBESTOP_C4_BLOCKED' for i in incidents),
               'Faux positif sur transfert fictif reussi')

        _, incidents = run(prefix + [
            'tEA-T3: WAIT-FIN-TRSF C4:1 C5:0 fgBfinT3:0 eT3:44 pT3:-468mm',
            'tEA-T3: ERREUR transfert EA->T3 -43',
            "tEA-T3: boite coincée sur C4 après x éjections d'EA",
        ])
        blocked = [i for i in incidents if i.code == 'CUBESTOP_C4_BLOCKED']
        _check(len(blocked) == 1 and blocked[0].severity == 'error',
               'Blocage fictif absent ou non critique')
        _check(8 in blocked[0].event_lines, 'Preuve explicite fictive absente')

        frames, incidents = run([
            'CubeStop:N',
            'tEA-T3: DEM-TRSF C4:1 C5:0 fgBfinT3:0 eT3:49 pT3:-210mm',
            'tEA-T3: WAIT-FIN-TRSF C4:1 C5:0 fgBfinT3:0 eT3:44 pT3:-468mm',
            'tEA-T3: ERREUR transfert EA->T3 -43',
            "tEA-T3: boite coincée sur C4 après x éjections d'EA",
        ])
        _check(not any(f.cubestop_present for f in frames), 'CubeStop fictif affiche malgre N')
        _check(not any(i.code == 'CUBESTOP_C4_BLOCKED' for i in incidents),
               'Diagnostic CubeStop fictif present malgre N')


def main() -> None:
    _validate_fixtures()

    for name in ('TracAlpha1.txt', 'TracAlpha1_017.old'):
        blocked_path = ROOT / 'TraceAlphaViewer' / name
        if not blocked_path.exists():
            print(f'Controle terrain ignore : {name} absent')
            continue
        with blocked_path.open(encoding='latin-1') as source:
            proof_lines = {n for n, text in enumerate(source, 1)
                           if re.search(r'boite\s+coinc\S*\s+sur\s+C4\s+apr\S*s.*ject', text, re.I)}
        _check(proof_lines, f'Preuve explicite absente de {name} : revoir le controle terrain')
        _, incidents = _diagnostics_for(blocked_path)
        cubestop = [
            incident for incident in incidents
            if incident.code == "CUBESTOP_C4_BLOCKED"
        ]
        _check(cubestop, "diagnostic CUBESTOP_C4_BLOCKED absent")
        incident = cubestop[0]
        _check(incident.severity == "error", "diagnostic CubeStop non critique")
        joined = " ".join([
            incident.title,
            incident.summary,
            incident.symptom,
            " ".join(incident.probable_causes),
            " ".join(incident.checks),
        ])
        for token in ("CubeStop", "C4", "C5", "EA->T3"):
            _check(token in joined, f"diagnostic CubeStop incomplet: {token}")
        _check(bool(proof_lines.intersection(incident.event_lines)), "preuve ligne blocage C4 absente")

    no_cubestop_path = ROOT / "TraceAlphaViewer" / "TracAlpha1_005.old"
    if no_cubestop_path.exists():
        frames, incidents = _diagnostics_for(no_cubestop_path)
        _check(
            not any(frame.cubestop_present for frame in frames),
            "CubeStop affiche present malgre CubeStop:N",
        )
        _check(
            not any(incident.code == "CUBESTOP_C4_BLOCKED" for incident in incidents),
            "diagnostic CubeStop present sur trace CubeStop:N",
        )
    else:
        print('Controle terrain ignore : TracAlpha1_005.old absent')

    print("Diagnostic CubeStop: validation OK")


if __name__ == "__main__":
    main()
