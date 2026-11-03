"""Espacement temporaire des collectes dans un processus de calcul autonome."""
from contextlib import contextmanager
import gc


@contextmanager
def loading_collections():
    """Laisse le GC actif et restaure exactement ses seuils, meme sur erreur."""
    thresholds = gc.get_threshold()
    changed = gc.isenabled() and 0 < thresholds[0] < 500_000
    if changed:
        gc.set_threshold(500_000, *thresholds[1:])
    try:
        yield
    finally:
        if changed:
            gc.set_threshold(*thresholds)
