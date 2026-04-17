from pathlib import Path
import sys


def _prefer_binja_bundled_pyside():
    try:
        import binaryninja
    except Exception:
        return

    binaryninja_file = getattr(binaryninja, "__file__", None)
    if not binaryninja_file:
        return

    bn_root = Path(binaryninja_file).resolve().parents[2]
    bundled_python3 = bn_root / "python3"
    if not bundled_python3.exists():
        return

    bundled_python3_str = str(bundled_python3)
    sys.path[:] = [path for path in sys.path if path != bundled_python3_str]
    sys.path.insert(0, bundled_python3_str)


def _prefer_pinned_binsync_root():
    # Local CLI installs can pin a checkout root here so BN loads the fork before site-packages.
    plugin_dir = Path(__file__).resolve().parent
    source_root_file = plugin_dir / "binsync_source_root.txt"
    if not source_root_file.exists():
        return

    try:
        source_root = Path(source_root_file.read_text(encoding="utf-8").strip()).expanduser()
    except OSError:
        return

    if not source_root.exists():
        return

    source_root_str = str(source_root.resolve())
    if source_root_str not in sys.path:
        sys.path.insert(0, source_root_str)


_prefer_binja_bundled_pyside()
_prefer_pinned_binsync_root()

from binsync import create_plugin

create_plugin()
