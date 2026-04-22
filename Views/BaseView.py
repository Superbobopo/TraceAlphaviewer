import customtkinter as ctk


class BaseView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        kwargs.setdefault('fg_color', '#12121f')
        kwargs.setdefault('corner_radius', 0)
        super().__init__(master, **kwargs)
        self.master = master

    def show(self) -> None:
        self.pack(fill='both', expand=True)

    def hide(self) -> None:
        self.pack_forget()