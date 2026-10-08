"""Lance tous les controles metier et les regressions du viewer."""
from pathlib import Path
import subprocess
import sys


def main() -> None:
    directory = Path(__file__).resolve().parent
    failures = []
    for script in sorted(directory.glob('validate_*.py')):
        if script.name == Path(__file__).name:
            continue
        print(f'Controle : {script.name}', flush=True)
        result = subprocess.run([sys.executable, str(script)], cwd=directory.parents[1])
        if result.returncode:
            failures.append(script.name)
    if failures:
        print('Controles en echec : ' + ', '.join(failures))
        raise SystemExit(1)
    print('Tous les controles disponibles ont reussi.')


if __name__ == '__main__':
    main()
