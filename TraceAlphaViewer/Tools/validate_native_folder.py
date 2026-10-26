"""Verifie le protocole et le cycle de vie du moteur dossier sur donnees fictives."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TraceAlphaViewer'))

from Models.native_folder import engine_path, run_native, _ProcessLifetime


def trace(day, alpha='031', pharmacy='LAHLOU', frames=3, active=False):
    prefix = (f'creation de la trace le {day:02}/05/2026\n'
              f'* {day:02}|08:00:00.0 OUVERTURE DE LA TRACE le {day:02}/05/2026\n'
              f'  {day:02}|08:00:00.1 ouverture de la base C:\\APOTEKA\\BASEALPHA_#2025.{alpha}.MDB\n'
              f'  {day:02}|08:00:00.2 ouverture de la base C:\\APOTEKA\\BASEFIC1560{pharmacy}.MDB\n')
    lines = [prefix]
    if active:
        lines.append(f'  {day:02}|08:00:00.3 T4: eT:0 pT4:0 C6:1\n')
    for index in range(frames):
        minutes, seconds = divmod(index, 60)
        lines.append(f'  {day:02}|08:{minutes:02}:{seconds:02}.9 fin de traitement fictif\n')
    return ''.join(lines)


def command(binary, request, expected=0):
    result = subprocess.run([str(binary), '--request', str(request)], capture_output=True,
                            text=True, encoding='utf-8', timeout=30,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode == expected, f'Code retour moteur : {result.returncode}'
    return [json.loads(line) for line in result.stdout.splitlines()]


def main():
    import msgpack

    binary = engine_path()
    clean_environment = dict(os.environ, PATH=os.environ.get('SystemRoot', 'C:/Windows') + '/System32')
    version = json.loads(subprocess.check_output([str(binary), '--version'], env=clean_environment,
                                               text=True, encoding='utf-8', timeout=10,
                                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)))
    assert version['protocol_version'] == 1
    (ROOT / 'build').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / 'build', prefix='native-folder-validation-') as directory:
        directory = Path(directory)
        inputs = directory / 'traces'
        inputs.mkdir()
        (inputs / 'jour1.old').write_text(trace(1, frames=510, active=True), encoding='latin-1')
        (inputs / 'jour2.old').write_text(trace(2), encoding='latin-1')
        (inputs / 'motte.txt').write_text(trace(1, alpha='009', pharmacy='MOTTE'), encoding='latin-1')
        (inputs / 'copie.old').write_bytes((inputs / 'jour2.old').read_bytes())
        (inputs / 'document.txt').write_text('Document ordinaire, sans horodatage', encoding='latin-1')
        nested = inputs / '.trace_work'
        nested.mkdir()
        (nested / 'ignore.old').write_text(trace(3), encoding='latin-1')
        progress = []
        catalog = run_native('catalog', inputs, directory / 'catalog', on_message=lambda *row: progress.append(row))
        assert catalog['files'] == 4 and catalog['ignored_files'] >= 2
        assert len(catalog['groups']) == 2
        group = next(item for item in catalog['groups'] if item['label'] == 'Alpha 031 — Pharmacie Lahlou')
        assert len(group['sources']) == 2 and len(group['duplicates']) == 1
        result = run_native('parse_group', inputs, directory / 'parse', group['sources'])
        assert len(result['sources']) == 2
        for source in result['sources']:
            count = 0
            for filename in source['blocks']:
                frames = msgpack.unpackb((Path(source['store']) / filename).read_bytes(), raw=False)
                assert 0 < len(frames) <= 500
                count += len(frames)
            assert count == source['frame_count']
        assert result['sources'][0]['frame_count'] > 500
        second = result['sources'][1]
        first_frame = msgpack.unpackb((Path(second['store']) / second['blocks'][0]).read_bytes(), raw=False)[0]
        assert first_frame['timestamp'] == 0 and first_frame['C6'] == 0

        changed = Path(group['sources'][0]['filepath'])
        original = changed.read_bytes()
        changed.write_bytes(original.replace(b'BASEFIC1560LAHLOU', b'BASEFIC1560MOTTE_'))
        try:
            run_native('parse_group', inputs, directory / 'changed', group['sources'])
        except OSError as error:
            assert 'chang' in str(error) and 'dossier' in str(error)
        else:
            raise AssertionError('Une source modifiee apres le catalogue doit etre refusee')
        changed.write_bytes(original)

        invalid = directory / 'invalid.json'
        invalid.write_text(json.dumps({'protocol_version': 999, 'job_id': 'invalid',
                                      'operation': 'catalog', 'path': str(inputs)}), encoding='utf-8')
        events = command(binary, invalid, expected=1)
        assert events[-1]['kind'] == 'error' and events[-1]['job_id'] == 'invalid'
        assert all(row['protocol_version'] == 1 for row in events)

        long = directory / 'long.old'
        with long.open('w', encoding='latin-1') as output:
            output.write(trace(1))
            output.write('  01|09:00:00.0 ligne fictive pour annulation\n' * 200_000)
        pending = directory / 'pending.json'
        pending.write_text(json.dumps({'protocol_version': 1, 'job_id': 'cancel', 'operation': 'parse_group',
                                      'session': str(directory / 'cancel'), 'sources': [{'filepath': str(long)}]}), encoding='utf-8')
        process = subprocess.Popen([str(binary), '--request', str(pending)], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        lifetime = _ProcessLifetime(process)
        if sys.platform == 'win32':
            lifetime.close()
        else:
            process.terminate()
        process.wait(timeout=10)
        assert process.returncode is not None
        # La fermeture des handles doit permettre le nettoyage immediat des sources.
        long.unlink()
    print('Moteur dossier : protocole, catalogue, blocs, segments, annulation et runtime autonome valides.')


if __name__ == '__main__':
    main()
