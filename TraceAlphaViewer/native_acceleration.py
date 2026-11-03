"""Charge les calculs compiles seulement s'ils correspondent aux sources courantes."""
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import sysconfig


MODULES = (
    'Parser.trace_parser', 'Parser.trace_source',
    'Models.state', 'Models.frame_store', 'Models.health_radar',
    'Models.reference_index', 'Models.measurement_analysis', 'Models.segment_collector',
    'Models.identification_analysis', 'Models.trace_calendar', 'Models.robot_drain',
    'Models.c2_analysis', 'Models.c5_analysis', 'Models.trace_observations',
    'Models.t5_drive_analysis', 'Models.diagnostic', 'Models.diagnostic_parallel',
)
CYTHON_VERSION = '3.3.0'
ZIG_VERSION = '0.16.0'
DIRECTIVES = {'language_level': 3, 'annotation_typing': False, 'infer_types': False,
              'binding': True, 'embedsignature': True}


def file_digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def interpreter_tag():
    return {'implementation': sys.implementation.name, 'cache_tag': sys.implementation.cache_tag,
            'extension': sysconfig.get_config_var('EXT_SUFFIX'), 'platform': sys.platform,
            'bits': 64 if sys.maxsize > 2**32 else 32,
            'gil_disabled': bool(sysconfig.get_config_var('Py_GIL_DISABLED'))}


def inspect_build(root, *, verify_sources=True):
    """Verifie tout le lot avant d'autoriser le premier import natif."""
    root = Path(root).resolve()
    base = root / 'bin' / 'python-acceleration'
    try:
        active = json.loads((base / 'active.json').read_text(encoding='utf-8'))
        if not isinstance(active, dict):
            raise ValueError('Pointeur de compilation invalide')
        build_id = active['build_id']
        if not isinstance(build_id, str) or not re.fullmatch('[0-9a-f]{64}', build_id):
            raise ValueError('Identifiant de construction invalide')
        directory = base / build_id
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        if not isinstance(manifest, dict):
            raise ValueError('Manifeste de compilation invalide')
        if manifest.get('version') != 1 or manifest.get('interpreter') != interpreter_tag():
            raise ValueError('Version Python ou format de compilation incompatible')
        if manifest.get('compiler') != {'cython': CYTHON_VERSION, 'zig': ZIG_VERSION, 'directives': DIRECTIVES}:
            raise ValueError('Recette de compilation incompatible')
        if manifest.get('build_id') != build_id or set(manifest.get('modules', {})) != set(MODULES):
            raise ValueError('Lot de calculs compile incomplet')
        for name in MODULES:
            entry = manifest['modules'][name]
            relative = Path(*name.split('.'))
            artifact = directory / relative.with_suffix(interpreter_tag()['extension'])
            if file_digest(artifact) != entry['binary_sha256']:
                raise ValueError('Extension compilee modifiee : ' + name)
            if verify_sources and file_digest(root / relative.with_suffix('.py')) != entry['source_sha256']:
                raise ValueError('Sources modifiees depuis la compilation : ' + name)
        return {'mode': 'native', 'directory': directory, 'manifest': manifest, 'reason': ''}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'mode': 'python', 'directory': None, 'manifest': None, 'reason': str(exc)}


@lru_cache(maxsize=4)
def acceleration_status(root):
    if os.environ.get('TRACE_ALPHA_ACCELERATION', 'auto').lower() == 'python':
        return {'mode': 'python', 'directory': None, 'manifest': None, 'reason': 'Mode Python explicite'}
    return inspect_build(root, verify_sources=not getattr(sys, 'frozen', False))


def enable_package(name, package_path, root):
    status = acceleration_status(str(Path(root).resolve()))
    if status['mode'] == 'native':
        directory = str(status['directory'] / name)
        if directory not in package_path:
            package_path.insert(0, directory)


def bundled_files(root):
    """Le packaging controle les sources avant d'embarquer un lot exact."""
    root = Path(root).resolve()
    base = root / 'bin' / 'python-acceleration'
    if not (base / 'active.json').exists():
        return [], []
    status = inspect_build(root)
    if status['mode'] != 'native':
        raise RuntimeError(status['reason'] + ' ; relancer Tools/build_acceleration.py')
    directory = status['directory']
    destination = Path('bin/python-acceleration') / directory.name
    binaries = [(str(directory / Path(*name.split('.')).with_suffix(interpreter_tag()['extension'])),
                 str(destination / name.split('.')[0])) for name in MODULES]
    data = [(str(directory / 'manifest.json'), str(destination)),
            (str(base / 'active.json'), 'bin/python-acceleration')]
    return binaries, data
