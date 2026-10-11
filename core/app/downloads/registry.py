from __future__ import annotations

import importlib.util
import inspect
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import structlog

from app.downloads.base import DownloadClient, SearchSource, _Plugin
from app.downloads.clients.jdownloader import JDownloaderClient
from app.downloads.clients.myjdownloader import MyJDownloaderClient
from app.downloads.clients.qbittorrent import QBittorrentClient
from app.downloads.clients.transmission import TransmissionClient

logger = structlog.get_logger(__name__)

PluginKind = Literal["client", "source"]

BUILTIN_PLUGINS: list[type[_Plugin]] = [
    QBittorrentClient,
    TransmissionClient,
    MyJDownloaderClient,
    JDownloaderClient,
]

PLUGINS_README = """AnimeWatcherPlus -- eigene Download-Plugins
==========================================

Jede .py-Datei in diesem Ordner wird beim Start der App geladen. Jede darin
definierte Unterklasse von DownloadClient oder SearchSource steht danach auf
der Download-Seite unter "Einrichtung" zur Verfügung.

Vorlagen mit Erklärungen: core/plugin_examples/ im Quellcode-Repository.
Die Schnittstelle selbst ist in core/app/downloads/base.py dokumentiert.

Nach dem Hinzufügen oder Ändern einer Datei die App neu starten.


AnimeWatcherPlus -- your own download plugins
==============================================

Every .py file in this folder is loaded when the app starts. Each subclass
of DownloadClient or SearchSource defined in it becomes available on the
download page under "Einrichtung".

Annotated templates: core/plugin_examples/ in the source repository. The
plugin interface is documented in core/app/downloads/base.py.

Restart the app after adding or changing a file.
"""


def kind_of(plugin_class: type[_Plugin]) -> PluginKind:
    return "client" if issubclass(plugin_class, DownloadClient) else "source"


@dataclass
class PluginLoadError:
    file: str
    error: str


@dataclass
class DownloadPluginRegistry:
    """Every plugin class the app knows: the built-in ones plus whatever the
    plugins folder holds. Classes only -- configured instances live in the
    database (DownloadIntegration) and are created per use."""

    classes: dict[str, type[_Plugin]] = field(default_factory=dict)
    builtin_ids: set[str] = field(default_factory=set)
    load_errors: list[PluginLoadError] = field(default_factory=list)

    def register(self, plugin_class: type[_Plugin], *, builtin: bool = False) -> None:
        plugin_id = getattr(plugin_class, "id", None)
        if not isinstance(plugin_id, str) or not plugin_id:
            raise ValueError(f"{plugin_class.__name__} hat keine 'id'")
        if not isinstance(getattr(plugin_class, "name", None), str):
            raise ValueError(f"{plugin_class.__name__} hat keinen 'name'")
        if plugin_id in self.classes:
            raise ValueError(f"Plugin-ID '{plugin_id}' ist bereits vergeben")
        self.classes[plugin_id] = plugin_class
        if builtin:
            self.builtin_ids.add(plugin_id)

    def get(self, plugin_id: str) -> type[_Plugin] | None:
        return self.classes.get(plugin_id)

    def load_folder(self, folder: Path) -> None:
        """Imports every .py file in `folder` and registers the plugin
        classes defined in it. A broken file is recorded and skipped -- it
        must never keep the app from starting."""
        folder.mkdir(parents=True, exist_ok=True)
        readme = folder / "LIESMICH.txt"
        if not readme.exists():
            readme.write_text(PLUGINS_README, encoding="utf-8")

        for path in sorted(folder.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                found = self._load_file(path)
            except Exception as exc:
                logger.exception("download_plugin_load_failed", file=str(path))
                self.load_errors.append(PluginLoadError(file=path.name, error=f"{type(exc).__name__}: {exc}"))
                continue
            if not found:
                self.load_errors.append(
                    PluginLoadError(file=path.name, error="Keine DownloadClient-/SearchSource-Klasse gefunden")
                )

    def _load_file(self, path: Path) -> int:
        module_name = f"awp_plugin_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError("Datei kann nicht geladen werden")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        found = 0
        for _, obj in inspect.getmembers(module, inspect.isclass):
            # Only classes defined in this file -- not the base classes or
            # other plugins it imports.
            if obj.__module__ != module_name or inspect.isabstract(obj):
                continue
            if issubclass(obj, (DownloadClient, SearchSource)):
                self.register(obj)
                found += 1
                logger.info("download_plugin_loaded", plugin_id=obj.id, file=path.name)
        return found


def build_registry(plugins_folder: Path | None) -> DownloadPluginRegistry:
    registry = DownloadPluginRegistry()
    for plugin_class in BUILTIN_PLUGINS:
        registry.register(plugin_class, builtin=True)
    if plugins_folder is not None:
        registry.load_folder(plugins_folder)
    return registry
