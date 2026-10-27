"""Transfere les rapports existants, sans changer leur contenu ni leurs dates."""
from pathlib import Path
from datetime import datetime
import argparse
import json
import html
import os
import re
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Models.report_storage import (desktop_reports_dir, pharmacy_directory,
    UNKNOWN_PHARMACY, file_digest, copy_verified)


def inventory(source):
    result = []
    for path in sorted(Path(source).glob('diagnostic_report_*.html')):
        data = path.with_name(path.name.replace('diagnostic_report_', 'report_data_')).with_suffix('.json')
        try:
            payload = json.loads(data.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            payload = {}
        result.append((path.name, payload))
    return result


def migrate(source, root):
    source, root = Path(source).resolve(), Path(root).resolve()
    if not source.is_dir():
        return {'reports': 0, 'pharmacies': {}}
    if source == root or source.is_relative_to(root) or root.is_relative_to(source):
        raise ValueError('Les dossiers source et destination doivent etre distincts')
    rows = inventory(source)
    hashes = {}
    for path in source.rglob('*'):
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError('Ressource hors du dossier de rapports')
        if path.is_file():
            hashes[path.relative_to(source)] = file_digest(path)
    root.mkdir(parents=True, exist_ok=True)
    archive = root / UNKNOWN_PHARMACY
    if archive.exists():
        archive = root / (UNKNOWN_PHARMACY + ' - import ' + datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f'))
    if not archive.resolve().is_relative_to(root) or archive.exists():
        raise ValueError('Destination d import non disponible')
    # Le dossier complet conserve aussi les anciens rapports sans JSON ni manifeste.
    shutil.move(str(source), str(archive))
    for relative, digest in hashes.items():
        if file_digest(archive / relative) != digest:
            raise OSError('Verification du transfert non conforme ; import conserve')
    counts = {}
    for filename, payload in rows:
        destination = pharmacy_directory(root, payload)
        if destination.name == UNKNOWN_PHARMACY:
            counts[archive.name] = counts.get(archive.name, 0) + 1
            continue
        related = [archive / filename,
            archive / filename.replace('diagnostic_report_', 'report_data_').replace('.html', '.json'),
            (archive / filename).with_suffix('.manifest.json')]
        # Les ressources React peuvent importer d'autres fichiers que ceux du manifeste.
        assets = list((archive / '_next').rglob('*')) if (archive / '_next').is_dir() else []
        for asset in assets:
            if asset.is_file():
                copy_verified(asset, destination / asset.relative_to(archive))
        for path in related:
            if path.exists():
                copy_verified(path, destination / path.name)
        for path in related:
            if path.exists():
                path.unlink()
        counts[destination.name] = counts.get(destination.name, 0) + 1
    return {'reports': len(rows), 'pharmacies': counts}


def repair_missing_assets(root):
    """Restaurer le rendu seulement, avec le JSON historique et une copie originale."""
    from Models.diagnostic_report import build_diagnostic_report_html
    repaired = 0
    marker = '<!-- Alpha reports : rendu historique restaure v3 -->'
    for path in Path(root).rglob('diagnostic_report_*.html'):
        text = path.read_text(encoding='utf-8')
        assets = re.findall(r'(?:src|href)=[\"\']([^\"\']*_next/[^\"\']+)', text)
        backup = path.with_suffix('.html.original')
        missing = any(not (path.parent / html.unescape(asset).split('?', 1)[0]).is_file() for asset in assets)
        if not missing and (not backup.exists() or marker in text):
            continue
        data = path.with_name(path.name.replace('diagnostic_report_', 'report_data_')).with_suffix('.json')
        payload = json.loads(data.read_text(encoding='utf-8'))
        # Ces valeurs vides rendent les anciens schemas affichables, sans recalcul metier.
        identifiers = {}
        for group in payload.get('groups', []) + payload.get('priority', []):
            key = tuple(group.get(field) for field in ('severity', 'belt', 'code', 'title'))
            group.setdefault('id', identifiers.setdefault(key, f'archive-{len(identifiers)}'))
            group.setdefault('examples', [])
            group.setdefault('series', [])
        rendered = build_diagnostic_report_html([], payload=payload) + '\n' + marker
        if not backup.exists():
            copy_verified(path, backup)
        manifest = path.with_suffix('.manifest.json')
        if manifest.exists() and not manifest.with_suffix('.json.original').exists():
            copy_verified(manifest, manifest.with_suffix('.json.original'))
        path.write_text(rendered, encoding='utf-8')
        manifest.write_text(json.dumps([path.name, data.name]), encoding='utf-8')
        repaired += 1
    return repaired


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'TraceAlphaViewer/reports')
    parser.add_argument('--destination', type=Path, default=desktop_reports_dir())
    parser.add_argument('--apply', action='store_true', help='Effectuer le transfert apres verification des destinations')
    parser.add_argument('--repair-missing-assets', action='store_true', help='Restaurer les rendus incomplets depuis les JSON historiques, avec sauvegarde des HTML')
    args = parser.parse_args()
    if args.apply:
        result = migrate(args.source, args.destination)
        if args.repair_missing_assets:
            result['repaired'] = repair_missing_assets(args.destination)
        print(json.dumps(result, ensure_ascii=True))
    else:
        counts = {}
        for _, payload in inventory(args.source):
            name = pharmacy_directory(args.destination, payload).name
            counts[name] = counts.get(name, 0) + 1
        print(json.dumps({'source': str(args.source), 'destination': str(args.destination), 'pharmacies': counts}, ensure_ascii=True))


if __name__ == '__main__':
    main()
