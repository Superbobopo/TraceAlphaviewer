"""Construit le moteur Rust des dossiers avec une chaine locale au projet."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
CRATE = ROOT / 'native' / 'folder_engine'
LOCAL = ROOT / 'build' / 'rust-toolchain'
OUTPUT = ROOT / 'TraceAlphaViewer' / 'bin'
BINARY_NAME = 'tracealpha-folder-worker.exe' if os.name == 'nt' else 'tracealpha-folder-worker'


def rust_environment():
    env = os.environ.copy()
    env['RUSTUP_HOME'] = str(LOCAL / 'rustup')
    env['CARGO_HOME'] = str(LOCAL / 'cargo')
    env['CARGO_TARGET_DIR'] = str(ROOT / 'build' / 'folder-engine')
    local_cargo = LOCAL / 'cargo' / 'bin' / ('cargo.exe' if os.name == 'nt' else 'cargo')
    if not local_cargo.is_file():
        env.pop('RUSTUP_HOME')
        env.pop('CARGO_HOME')
        return shutil.which('cargo'), env
    paths = [str(local_cargo.parent)]
    if os.name == 'nt':
        toolchain = LOCAL / 'rustup' / 'toolchains' / 'stable-x86_64-pc-windows-gnu'
        compiler = toolchain / 'lib' / 'rustlib' / 'x86_64-pc-windows-gnu' / 'bin' / 'self-contained'
        paths.extend([str(toolchain / 'bin'), str(compiler)])
        if (compiler / 'x86_64-w64-mingw32-gcc.exe').is_file():
            env['CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER'] = str(compiler / 'x86_64-w64-mingw32-gcc.exe')
            env['RUSTFLAGS'] = '-C target-feature=+crt-static'
    env['PATH'] = os.pathsep.join(paths + [env.get('PATH', '')])
    return str(local_cargo), env


def bootstrap():
    if os.name != 'nt':
        raise SystemExit('Installer Rust/Cargo puis relancer cette commande.')
    LOCAL.mkdir(parents=True, exist_ok=True)
    installer = LOCAL / 'rustup-init.exe'
    if not installer.is_file():
        urllib.request.urlretrieve(
            'https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-gnu/rustup-init.exe', installer)
    env = os.environ.copy()
    env.update(RUSTUP_HOME=str(LOCAL / 'rustup'), CARGO_HOME=str(LOCAL / 'cargo'))
    subprocess.run([str(installer), '-y', '--no-modify-path', '--profile', 'minimal',
                    '--default-host', 'x86_64-pc-windows-gnu', '--default-toolchain', 'stable'],
                   env=env, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bootstrap', action='store_true', help='Installer Rust localement sous build/, sans modifier le PATH utilisateur.')
    parser.add_argument('--test', action='store_true', help='Executer aussi les tests Rust.')
    args = parser.parse_args()
    cargo, env = rust_environment()
    if not cargo and args.bootstrap:
        bootstrap()
        cargo, env = rust_environment()
    if not cargo:
        raise SystemExit('Rust/Cargo absent. Relancer avec --bootstrap pour preparer la chaine locale.')
    command = [cargo, '--manifest-path', str(CRATE / 'Cargo.toml')]
    # Cargo attend la sous-commande avant les options du manifeste.
    if args.test:
        subprocess.run([cargo, 'test', *command[1:]], cwd=ROOT, env=env, check=True)
    subprocess.run([cargo, 'build', '--release', '--locked', *command[1:]], cwd=ROOT, env=env, check=True)
    source = Path(env['CARGO_TARGET_DIR']) / 'release' / BINARY_NAME
    OUTPUT.mkdir(parents=True, exist_ok=True)
    destination = OUTPUT / BINARY_NAME
    shutil.copy2(source, destination)
    version = json.loads(subprocess.check_output([str(destination), '--version'], text=True, encoding='utf-8'))
    if version.get('protocol_version') != 1:
        raise SystemExit('Version du protocole du moteur compile incompatible.')
    print(f'Moteur dossier : {destination} (protocole {version["protocol_version"]})')


if __name__ == '__main__':
    main()
