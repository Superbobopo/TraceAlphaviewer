"""Construit l'executable Windows autonome avec le logo et le rapport web."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    if sys.platform != 'win32':
        raise SystemExit('La construction du .exe doit etre lancee sous Windows')
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--noconfirm',
        '--distpath', str(ROOT / 'dist'), '--workpath', str(ROOT / 'build'),
        str(ROOT / 'TraceAlphaViewer.spec'),
    ], cwd=ROOT, check=True)
    print(f'Executable : {ROOT / "dist" / "TraceAlphaViewer.exe"}')


if __name__ == '__main__':
    main()
