# Construction Windows autonome, sans traces locales ni console.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH)
app = root / 'TraceAlphaViewer'
report = app / 'report_app' / 'out'
if not (report / 'index.html').is_file():
    raise RuntimeError('Construire le rapport avec npm install puis npm run build avant le .exe')

analysis = Analysis(
    [str(app / 'Main.py')],
    pathex=[str(app)],
    datas=collect_data_files('customtkinter') + [
        (str(app / 'assets' / 'trace-alpha.ico'), 'assets'),
        (str(app / 'assets' / 'trace-alpha.png'), 'assets'),
        (str(report), 'report_app/out'),
        (str(app / 'report_app' / 'public'), 'report_app/public'),
    ],
    hiddenimports=['Models.loading_worker'],
    excludes=['numpy'],
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive, analysis.scripts, analysis.binaries, analysis.datas, [],
    name='TraceAlphaViewer',
    console=False,
    icon=str(app / 'assets' / 'trace-alpha.ico'),
    upx=False,
)
