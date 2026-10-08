import customtkinter as ctk
from Views.BaseView import BaseView
from Views.accueilView import AccueilView

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class TraceAlphaViewer(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("TraceAlpha Viewer")
        self.geometry("1500x860")
        self.minsize(1300, 720)
        self.configure(fg_color='#12121f')

        self.main_view: BaseView = AccueilView(self)
        self.main_view.show()

    def switch_view(self, new_view: BaseView) -> None:
        previous = self.main_view
        previous.hide()
        self.main_view = new_view
        if getattr(new_view, '_return_view', None) is not previous:
            previous.destroy()
        self.main_view.show()


if __name__ == '__main__':
    app = TraceAlphaViewer()
    app.mainloop()
