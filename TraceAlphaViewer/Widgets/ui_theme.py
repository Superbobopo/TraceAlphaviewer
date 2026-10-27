"""Palette commune ; les composants partages gardent leur style hors viewer."""

UI_COLORS = {
    'background': '#0c1420',
    'panel': '#121e2c',
    'surface': '#172637',
    'control': '#26394e',
    'hover': '#344e69',
    'border': '#30475e',
    'text': '#e7eff8',
    'muted': '#93a9be',
    'dim': '#8097ad',
    'accent': '#59dec3',
    'accent_hover': '#7ae9d2',
    'accent_text': '#092721',
    'selected': '#23443f',
    'selected_hover': '#2e5c53',
    'selected_text': '#b2f5df',
}


def palette(widget):
    while widget is not None:
        values = vars(widget)
        if '_ui_palette' in values:
            return values['_ui_palette']
        widget = values.get('master')
    return None


def ui_color(widget, role, original):
    colors = palette(widget)
    return colors[role] if colors is not None else original


def control_colors(widget):
    if palette(widget) is None:
        return {}
    return dict(fg_color=UI_COLORS['control'], hover_color=UI_COLORS['hover'],
                text_color=UI_COLORS['text'])


def slider_colors(widget):
    if palette(widget) is None:
        return {}
    return dict(fg_color=UI_COLORS['control'], progress_color=UI_COLORS['selected_hover'],
                button_color=UI_COLORS['accent'], button_hover_color=UI_COLORS['accent_hover'])


def scrollbar_colors(widget):
    if palette(widget) is None:
        return {}
    return dict(bg=UI_COLORS['control'], activebackground=UI_COLORS['hover'],
                troughcolor=UI_COLORS['background'])


def scrollable_colors(widget):
    if palette(widget) is None:
        return {}
    return dict(scrollbar_fg_color=UI_COLORS['panel'], scrollbar_button_color=UI_COLORS['control'],
                scrollbar_button_hover_color=UI_COLORS['hover'])
