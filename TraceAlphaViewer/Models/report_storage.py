"""Rangement local des rapports par pharmacie sur le Bureau."""
from pathlib import Path
import ctypes
import hashlib
import os
import re
import shutil
import json

UNKNOWN_PHARMACY = 'Pharmacie non identifiée'


def desktop_reports_dir():
    if os.name == 'nt':
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer):
            raise OSError('Impossible de trouver le Bureau Windows')
        desktop = Path(buffer.value)
    else:
        desktop = Path.home() / 'Desktop'
    return desktop / 'Alpha reports'


def pharmacy_directory(root, payload):
    identity = payload.get('source', {}).get('identity') or {}
    name = str(identity.get('pharmacy') or UNKNOWN_PHARMACY).strip() or UNKNOWN_PHARMACY
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).rstrip(' .')[:80]
    if not clean or clean.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
            *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        clean = 'Pharmacie_' + clean
    if clean != name:
        clean += '_' + hashlib.sha256(name.encode('utf-8')).hexdigest()[:8]
    root = Path(root).resolve()
    destination = (root / clean).resolve()
    if not destination.is_relative_to(root):
        raise ValueError('Le dossier pharmacie doit rester dans Alpha reports')
    return destination


def file_digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def copy_verified(source, destination):
    """Ne jamais remplacer une ressource differente deja presente."""
    source, destination = Path(source), Path(destination)
    if destination.exists():
        if file_digest(source) != file_digest(destination):
            raise FileExistsError(f'Fichier different deja present : {destination.name}')
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if file_digest(source) != file_digest(destination):
            raise OSError(f'Copie non conforme : {destination.name}')


def retain_prepared_report(path, root=None):
    """Conserve les octets prepares et publie le manifeste en dernier."""
    from Models.diagnostic_report import report_files_available
    path = Path(path).resolve()
    if not report_files_available(path):
        raise OSError('Rapport temporaire incomplet')
    manifest = path.with_suffix('.manifest.json')
    names = json.loads(manifest.read_text(encoding='utf-8'))
    data_name = next(name for name in names if Path(name).name.startswith('report_data_') and name.endswith('.json'))
    payload = json.loads((path.parent / data_name).read_text(encoding='utf-8'))
    destination = pharmacy_directory(root or desktop_reports_dir(), payload)
    resources = path.parent / '_next'
    extra = [str(item.relative_to(path.parent)) for item in resources.rglob('*') if item.is_file()]
    sources = []
    for name in dict.fromkeys(names + extra):
        source = (path.parent / name).resolve()
        target = (destination / name).resolve()
        if not source.is_relative_to(path.parent) or not target.is_relative_to(destination):
            raise ValueError('Ressource hors du rapport')
        sources.append((source, target))
    for source, target in sources:
        copy_verified(source, target)
    copy_verified(manifest, destination / manifest.name)
    result = destination / path.name
    if not report_files_available(result):
        raise OSError('Rapport conserve incomplet')
    return result
