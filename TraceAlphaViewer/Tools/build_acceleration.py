"""Compile les calculs Python en extensions locales, sans reconstruire le viewer .exe."""
from pathlib import Path
import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import uuid

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'TraceAlphaViewer'
LOCAL = ROOT / 'build' / 'python-acceleration'
sys.path.insert(0, str(APP))
from native_acceleration import (MODULES, CYTHON_VERSION, ZIG_VERSION, DIRECTIVES,
                                 file_digest, inspect_build, interpreter_tag)


def prepare_toolchain(bootstrap):
    tooling = LOCAL / 'tooling'
    zig = tooling / 'ziglang' / 'zig.exe'
    if not (tooling / 'Cython' / '__init__.py').is_file() or not zig.is_file():
        if not bootstrap:
            raise RuntimeError('Chaine locale absente : relancer avec --bootstrap')
        packages = LOCAL / 'packages'
        packages.mkdir(parents=True, exist_ok=True)
        requirements = [f'Cython=={CYTHON_VERSION}', f'ziglang=={ZIG_VERSION}']
        subprocess.run([sys.executable, '-m', 'pip', 'download', '--no-deps', '--only-binary=:all:',
                        '--dest', str(packages), *requirements], check=True)
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--no-deps',
                        '--find-links', str(packages), '--target', str(tooling), '--upgrade',
                        *requirements], check=True)
    sys.path.insert(0, str(tooling))
    cython = importlib.import_module('Cython')
    version = subprocess.check_output([str(zig), 'version'], text=True).strip()
    if cython.__version__ != CYTHON_VERSION or version != ZIG_VERSION:
        raise RuntimeError('Versions de la chaine locale incompatibles avec cette construction')
    return zig


def build(bootstrap=False, force=False):
    tag = interpreter_tag()
    if tag['implementation'] != 'cpython' or tag['platform'] != 'win32' or tag['bits'] != 64 or tag['gil_disabled']:
        raise RuntimeError('Cette construction qualifie CPython Windows 64 bits avec GIL')
    status = inspect_build(APP)
    if status['mode'] == 'native' and not force:
        print('Calculs compiles deja a jour : ' + status['directory'].name)
        return
    zig = prepare_toolchain(bootstrap)
    from Cython.Compiler.Main import CompilationOptions, default_options, compile

    build_id = uuid.uuid4().hex + uuid.uuid4().hex
    stage = LOCAL / ('stage-' + build_id)
    artifacts = stage / 'artifacts'
    artifacts.mkdir(parents=True)
    environment = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(LOCAL / 'zig-cache'),
                       ZIG_LOCAL_CACHE_DIR=str(LOCAL / 'zig-local'))
    sources = {name: APP / Path(*name.split('.')).with_suffix('.py') for name in MODULES}
    hashes = {name: file_digest(source) for name, source in sources.items()}
    previous = inspect_build(APP, verify_sources=False)
    entries = {}
    library = Path(sys.base_prefix) / 'libs' / f'python{sys.version_info.major}{sys.version_info.minor}.lib'
    for name, source in sources.items():
        target = artifacts / Path(*name.split('.')).with_suffix(tag['extension'])
        target.parent.mkdir(parents=True, exist_ok=True)
        if not force and previous['mode'] == 'native':
            entry = previous['manifest']['modules'][name]
            if entry['source_sha256'] == hashes[name]:
                existing = previous['directory'] / Path(*name.split('.')).with_suffix(tag['extension'])
                shutil.copy2(existing, target)
                entries[name] = dict(entry)
                print('Extension inchangee verifiee : ' + name, flush=True)
                continue
        generated = stage / (name.replace('.', '_') + '.c')
        result = compile(str(source), full_module_name=name, options=CompilationOptions(
            default_options, output_file=str(generated), compiler_directives=DIRECTIVES))
        if result.num_errors:
            raise RuntimeError('Compilation Cython impossible : ' + name)
        print('Compilation : ' + name, flush=True)
        subprocess.run([str(zig), 'cc', '-target', 'x86_64-windows-gnu', '-shared', '-O3',
                        '-fwrapv', '-DNDEBUG', '-I' + sysconfig.get_path('include'),
                        str(generated), str(library), '-o', str(target)], env=environment, check=True)
        entries[name] = {'source_sha256': hashes[name], 'binary_sha256': file_digest(target)}
    if any(file_digest(source) != hashes[name] for name, source in sources.items()):
        raise RuntimeError('Les sources ont change pendant la compilation ; lot non active')

    # Le processus de verification ne charge aucune extension dans le constructeur.
    probe = """import importlib, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import Models, Parser
directory = Path(sys.argv[2]).resolve()
for package in (Models, Parser):
    package.__path__.insert(0, str(directory / package.__name__))
for name in sys.argv[3:]:
    module = importlib.import_module(name)
    if not Path(module.__file__).resolve().is_relative_to(directory):
        raise RuntimeError('Extension non chargee : ' + name)
"""
    probe_env = dict(environment, TRACE_ALPHA_ACCELERATION='python')
    subprocess.run([sys.executable, '-c', probe, str(APP), str(artifacts), *MODULES],
                   env=probe_env, check=True, stdout=subprocess.DEVNULL)
    manifest = {'version': 1, 'build_id': build_id, 'interpreter': tag,
                'compiler': {'cython': CYTHON_VERSION, 'zig': ZIG_VERSION, 'directives': DIRECTIVES},
                'modules': entries}
    (artifacts / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    base = APP / 'bin' / 'python-acceleration'
    base.mkdir(parents=True, exist_ok=True)
    destination = base / build_id
    shutil.copytree(artifacts, destination)
    if any(file_digest(source) != hashes[name] for name, source in sources.items()):
        raise RuntimeError('Les sources ont change avant activation ; lot non active')
    pointer = base / ('active-' + build_id + '.tmp')
    pointer.write_text(json.dumps({'build_id': build_id}), encoding='utf-8')
    pointer.replace(base / 'active.json')
    print('Calculs compiles actifs : ' + str(destination))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bootstrap', action='store_true', help='Installer Cython et Zig sous build/, sans installation globale')
    parser.add_argument('--force', action='store_true', help='Creer un nouveau lot meme si les sources sont identiques')
    parser.add_argument('--check', action='store_true', help='Verifier le lot actif sans compiler ni telecharger')
    args = parser.parse_args()
    if args.check:
        status = inspect_build(APP)
        print('Calculs compiles a jour' if status['mode'] == 'native' else status['reason'])
        raise SystemExit(0 if status['mode'] == 'native' else 1)
    try:
        build(args.bootstrap, args.force)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == '__main__':
    main()
