"""Lance tous les controles metier et les regressions du viewer."""
from pathlib import Path
import argparse
import os
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--visual', action='store_true', help='Autoriser les controles avec fenetres visibles')
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    failures = []
    for script in sorted(directory.glob('validate_*.py')):
        if script.name == Path(__file__).name:
            continue
        if script.name == 'validate_diagnostic_layout.py' and not args.visual:
            print('Controle visuel separe : validate_diagnostic_layout.py (option --visual)', flush=True)
            continue
        print(f'Controle : {script.name}', flush=True)
        environment = dict(os.environ, TRACE_ALPHA_BACKGROUND_VALIDATION='0' if args.visual else '1')
        result = subprocess.run([sys.executable, str(script)], cwd=directory.parents[1], env=environment)
        if result.returncode:
            failures.append(script.name)
    if failures:
        print('Controles en echec : ' + ', '.join(failures))
        raise SystemExit(1)
    print('Tous les controles disponibles ont reussi.')


if __name__ == '__main__':
    main()
