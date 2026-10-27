from pathlib import Path
import sys

# Le worker doit demarrer avant tout import de l'interface.
if __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] == '--loading-worker':
    from Models.loading_worker import main
    main(sys.argv[2])
    raise SystemExit(0)

import customtkinter as ctk
from Views.BaseView import BaseView
from Views.accueilView import AccueilView

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class TraceAlphaViewer(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("TraceAlpha Viewer")
        self.iconbitmap(str(Path(__file__).resolve().parent / 'assets' / 'trace-alpha.ico'))
        self._fit_screen_limits()
        self._apply_view_geometry()
        self.configure(fg_color='#12121f')

        self.main_view: BaseView = AccueilView(self)
        self.main_view.show()

    def _fit_screen_limits(self):
        scale = self._get_window_scaling()
        home = isinstance(getattr(self, 'main_view', None), AccueilView) or not hasattr(self, 'main_view')
        minimum = (820, 750) if home else (1300, 750)
        self.minsize(min(minimum[0], int((self.winfo_screenwidth() - 40) / scale)),
                     min(minimum[1], int((self.winfo_screenheight() - 100) / scale)))

    def _apply_view_geometry(self):
        self._fit_screen_limits()
        scale = self._get_window_scaling()
        home = isinstance(getattr(self, 'main_view', None), AccueilView) or not hasattr(self, 'main_view')
        width, height = (900, 860) if home else (1500, 860)
        width = min(width, int((self.winfo_screenwidth() - 40) / scale))
        height = min(height, int((self.winfo_screenheight() - 100) / scale))
        self.state('normal')
        self.geometry(f'{width}x{height}')

    def _set_scaling(self, *args, **kwargs):
        super()._set_scaling(*args, **kwargs)
        self._fit_screen_limits()

    def switch_view(self, new_view: BaseView) -> None:
        previous = self.main_view
        previous.hide()
        self.main_view = new_view
        self._apply_view_geometry()
        if getattr(new_view, '_return_view', None) is not previous:
            previous.destroy()
        self.main_view.show()


if __name__ == '__main__':
    app = TraceAlphaViewer()
    if sys.argv[1:] == ['--validate-startup']:
        app.withdraw()
        app.after(300, app.destroy)
    app.mainloop()
