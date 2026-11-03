from pathlib import Path
from native_acceleration import enable_package

enable_package(__name__, __path__, Path(__file__).resolve().parents[1])
