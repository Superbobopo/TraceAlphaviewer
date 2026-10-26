"""Commandes communes pour les listes de 500 elements."""
import customtkinter as ctk
from Models.list_navigation import PAGE_SIZE


class Pagination(ctk.CTkFrame):
    def __init__(self, master, on_change):
        super().__init__(master, fg_color='#1e1e30', corner_radius=0, height=26)
        self._on_change = on_change
        self.page = 0
        self.pages = 1
        self._previous = ctk.CTkButton(self, text='<', width=28, height=22,
            command=lambda: self._on_change(self.page - 1))
        self._previous.pack(side='left', padx=4, pady=2)
        self._label = ctk.CTkLabel(self, text='', font=('Consolas', 10), height=22)
        self._label.pack(side='left', expand=True)
        self._next = ctk.CTkButton(self, text='>', width=28, height=22,
            command=lambda: self._on_change(self.page + 1))
        self._next.pack(side='right', padx=4, pady=2)

    def update_page(self, count, page):
        self.pages = max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page = min(max(0, page), self.pages - 1)
        first = self.page * PAGE_SIZE + 1 if count else 0
        last = min(count, (self.page + 1) * PAGE_SIZE)
        self._label.configure(text=f'Page {self.page + 1}/{self.pages} · {first}–{last} / {count}')
        self._previous.configure(state='normal' if self.page else 'disabled')
        self._next.configure(state='normal' if self.page + 1 < self.pages else 'disabled')
        return self.page
