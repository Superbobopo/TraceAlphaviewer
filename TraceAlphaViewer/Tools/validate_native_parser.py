"""Compare les frames et analyses Rust aux resultats du parser Python."""
from __future__ import annotations

import argparse
from dataclasses import fields, is_dataclass
import gc
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))

from Models.native_folder import engine_path, native_frames
from Models.state import MachineState
from Parser.trace_parser import parse_file


def _equal(actual, expected, location='frame'):
    if actual == expected:
        return
    if is_dataclass(actual) and is_dataclass(expected):
        for item in fields(actual):
            _equal(getattr(actual, item.name), getattr(expected, item.name), f'{location}.{item.name}')
    elif isinstance(actual, dict) and isinstance(expected, dict):
        if set(actual) != set(expected):
            raise AssertionError(f'{location}: cles differentes')
        for key in actual:
            _equal(actual[key], expected[key], f'{location}.{key}')
    elif isinstance(actual, (tuple, list)) and isinstance(expected, (tuple, list)):
        if len(actual) != len(expected):
            raise AssertionError(f'{location}: tailles {len(actual)} / {len(expected)}')
        for index, (left, right) in enumerate(zip(actual, expected)):
            _equal(left, right, f'{location}[{index}]')
    elif actual != expected:
        # Le contenu des traces terrain reste local.
        raise AssertionError(f'{location}: valeur differente ({type(actual).__name__})')


def _synthetic(folder):
    texts = [
        'CubeStop:Y', 'mvt CubeStop vers le BAS (transfert T2)',
        'T0: AUTO eT0:0 C0:0', 'T1: AUTO eT1:0', 'T2: AUTO eT2:0 eT3:0 C2:0 C3:0 C4:0',
        'T2: AUTO eT2:20 eT3:0 C2:1 C3:0 C4:1', 'CB1: ajout Hist_LectCB test 1code(s) lu(s)',
        'Rech. infos pour ALPHA-INC-001', 'idCB1: --> Ref:ALPHA-INC-001 lot: TEST',
        'mvt CubeStop vers le HAUT (EA vers T3)', 'le transfert (EA->T3) est termine',
        'tEA-T3: AUTO C4:0 C5:1 fgBfinT3:0 eT3:3 pT3:150mm IdCB1:OK',
        'CB2: ajout Hist_LectCB test 2code(s) lu(s)', 'Rech. infos pour DEMO001', '--> Produit fictif 76x62x110 10,5g',
        'idCB2: --> Ref:DEMO001 lot: LOT001', 'idCB2: (Nboite= 3)',
        "idCB2: Identif. sur le lecteur1 Ok 'DEMO001' (Nboite=3)",
        'tT3/T4: AUTO eT4:41 C5:0 C6:1 pT3:0mm pT4:410mm LgBtT4:110,5mm',
        'tT3/T4: AUTO eT4:42 C5:0 C6:1 pT3:0mm pT4:405mm LgBtT4:110,5mm',
        'tT3/T4: AUTO eT4:43 C5:0 C6:1 pT3:0mm pT4:404mm LgBtT4:110,5mm',
        'transfert T3->T4 termine longueur=110,5 mm idB=3',
        'tT3/T4: AUTO eT4:46 C5:0 C6:0 pT3:0mm pT4:300mm LgBtT4:110,5mm',
        "Demande le transfert (physique) T4 vers T5 'DEMO001'", 'la boite est rendu (physiquement) sur T5',
        "BdD: Création de la boite 'DEMO001' Produit fictif x=4125 (76x62x110) IdA:123",
        'AjoutBtT5.idA123.idB3', 'longueur boite (BdD)=110 (T2T)=109 (T4C)=111 (T4T)=112 diffT4=1mm',
        'T5: AUTO eT5=10 larg:76 C9:0 pT5:100 eT5useO:0 eT5useA:0',
        'MAJ (BUTEE-T5) boite Id:123 ref:DEMO001 nvlle dim:76x62 X:4125',
        'T5: AUTO eT5=12 larg:76 C9:1 pT5:110 eT5useO:0 eT5useA:0',
        'T5: AUTO eT5=12 larg:76 C9:1 pT5:160 eT5useO:0 eT5useA:0',
        'Déplace toutes les boites sur 50 mm',
        "MAJ (APRES-MESURE-LARG) bt IdA:123 'DEMO001' nvlle lxH:77x65 [x111] X:4275 (BdD:76x62x110)",
        'largeur lue sur T5 < 2mm et C9=1', 'FlagPoubellePleine=vrai LzB=65 capteurC1=1',
        'T2: AUTO eT2:-88 eT3:-4 C2:1 C3:0 C4:1 erreur',
        'T2: AUTO eT2:0 eT3:0 C2:0 C3:0 C4:0', 'T2: AUTO eT2:-88 C2:0 C3:0 C4:0',
        'supp. de T5 la boite Id:123 ref:DEMO001', 'T2: une boite est charg',
        'le transfert (EA->T3) est termine', 'transfert T3->T4 termine longueur=23,5 mm idB=4',
        "Demande le transfert (physique) T4 vers T5 ''", 'la boite est rendu (physiquement) sur T5',
        "BdD: Création de la boite '' Anonyme x=1060 (0x0x0) IdA:124", 'AjoutBtT5.idA124.idB-1',
        '-suppression de la boite ID:124', 'sur T5: DEMO002 Produit lot:L cb x=1100',
        "MAJ (APRES-MESURE-LARG) bt IdA:125 'DEMO002' nvlle lxH:40x60 [x100] X:1150",
        'Suppr. la boite IdA:125', 'CubeStop:N', 'version logiciel VBalpha: 1.0',
        'idCB2: (Nboite= 99)', "idCB2: Identif. sur le lecteur1 Ok 'DEMO003' (Nboite=99)",
        'capteurC1=0 FlagPoubellePleine=faux LzB:0',
    ]
    values = ['126', '', 'DEMO004', 'Produit quatre', '76', '62', '110', '', 'LOT', '', '', '', '', '1300', 'X990', '80', '0']
    texts += ['ALPHA:T5-LIST-PACK@<Dc2>' + '<Dc2>'.join(values) + '@FP',
              'ALPHA:T5-LIST-PACK@¶' + '¶'.join(values) + '@FP', 'ALPHA:T5-LIST-PACK@FP']
    lines = ['OUVERTURE DE LA TRACE le 31/12/2025',
             r'C:\APOTEKA\BASEALPHA_#2025.031.MDB C:\APOTEKA\BASEFIC1560LAHLOU.MDB']
    for index, text in enumerate(texts):
        lines.append(f' 31|23:59:{index // 10:02}.{index % 10}  {text}')
    # Les timestamp et en-tetes doivent etre strictement identiques avant exclusion.
    duplicate = ['OUVERTURE DE LA TRACE le 01/01/2026'] + [f' 01|00:00:0{i}.0  T0: AUTO eT0:0 C0:{i % 2}' for i in range(4)]
    lines += duplicate + duplicate + [' 01|00:00:10.0  fin de fichier']
    path = folder / 'parite-fictive.old'
    path.write_bytes(('\r\n'.join(lines) + '\r\n').encode('latin-1'))
    return path


def validate(path, workspace, analyses=False):
    request = workspace / 'request.json'
    session = workspace / 'native'
    request.write_text(json.dumps({'protocol_version': 1, 'job_id': 'parity', 'operation': 'parse_group',
        'session': str(session), 'sources': [{'filepath': str(path)}]}), encoding='utf-8')
    start = time.perf_counter()
    result = subprocess.run([str(engine_path()), '--request', str(request)], capture_output=True,
                            encoding='utf-8', check=True)
    native_seconds = time.perf_counter() - start
    messages = [json.loads(row) for row in result.stdout.splitlines()]
    source = next(row['payload']['sources'][0] for row in messages if row['kind'] == 'result')
    metadata = {}
    start = time.perf_counter()
    python_frames = parse_file(str(path), min_dt=0.0, source_metadata_output=metadata)
    python_seconds = time.perf_counter() - start
    _equal(source['duplicate_ranges'], metadata['duplicate_ranges'], 'copies')
    assert source['frame_count'] == len(python_frames), 'Nombre de frames different'
    rust_frames = [] if analyses else None
    iterator = iter(native_frames(source))
    conversion_seconds = 0.0
    for index, expected in enumerate(python_frames):
        start = time.perf_counter()
        native = next(iterator)
        conversion_seconds += time.perf_counter() - start
        assert isinstance(native, MachineState)
        _equal(native, expected, f'frame[{index}]')
        if analyses:
            rust_frames.append(native)
    if analyses:
        from Models.diagnostic import build_diagnostics
        from Models.reference_index import build_reference_records
        from Models.diagnostic_report import build_report_payload
        results = []
        for frames in (python_frames, rust_frames):
            events = [event for frame in frames for event in frame.events]
            incidents = build_diagnostics(frames, events)
            references = build_reference_records(frames, events)
            payload = build_report_payload(incidents, frames=frames)
            payload.pop('generated_at', None)
            results.append((incidents, references, payload))
        _equal(results[0], results[1], 'analyses')
    assert next(iterator, None) is None, 'Frames Rust excedentaires'
    print(f'Parite OK : {path.name}, {len(python_frames)} frames, Rust {native_seconds:.3f}s, '
          f'conversion {conversion_seconds:.3f}s, Python {python_seconds:.3f}s')
    del python_frames, rust_frames
    gc.collect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', nargs='*', type=Path)
    parser.add_argument('--all-local', action='store_true')
    parser.add_argument('--analyses', action='store_true')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='native-parity-', dir=ROOT / 'build') as name:
        workspace = Path(name)
        validate(_synthetic(workspace), workspace, analyses=True)
        sources = args.sources
        if args.all_local:
            sources += sorted((ROOT / 'TraceAlphaViewer').glob('*.old')) + sorted((ROOT / 'TraceAlphaViewer').glob('*.txt'))
        for path in sources:
            with tempfile.TemporaryDirectory(prefix='native-parity-', dir=ROOT / 'build') as local:
                validate(path.resolve(), Path(local), args.analyses)


if __name__ == '__main__':
    main()
