"""Construit l'executable Windows autonome avec le logo et le rapport web."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    if sys.platform != 'win32':
        raise SystemExit('La construction du .exe doit etre lancee sous Windows')
    try:
        import tkinter
        interpreter = tkinter.Tcl()
        interpreter.eval('info library')
    except Exception as exc:
        raise SystemExit(f'Tcl/Tk inaccessible : construction abandonnee pour eviter un .exe incomplet. {exc}')
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--distpath', str(ROOT / 'dist'), '--workpath', str(ROOT / 'build'),
        str(ROOT / 'TraceAlphaViewer.spec'),
    ], cwd=ROOT, check=True)
    executable = ROOT / 'dist' / 'TraceAlphaViewer.exe'
    subprocess.run([str(executable), '--validate-startup'], cwd=ROOT,
                   check=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    print(f'Executable construit et demarrage masque valide : {executable}')


if __name__ == '__main__':
    main()
