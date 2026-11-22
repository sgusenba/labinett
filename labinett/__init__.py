"""labinett – Auswertung der Nikolo-Glücksscheibe."""

try:
    # Vom Release-Build (GitHub Action) geschrieben, z. B. "0.1.12"
    from ._version import __version__
except ImportError:  # Entwicklung / lokaler Build
    __version__ = "0.1.0.dev0"
