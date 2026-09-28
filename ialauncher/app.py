"""The application: every service, wired together (the composition root builds it)."""
from dataclasses import dataclass

from . import config
from .infra import gpu
from .infra.windows import KeepAwake
from .services.catalog import Catalog
from .services.downloads import Downloads
from .services.hub import HubAdvisor
from .services.library import Library
from .services.model_editor import ModelEditor
from .services.registry import Registry
from .services.settings import Settings
from .services.supervisor import Supervisor
from .services.updates import Updates


@dataclass
class App:
    settings: Settings
    registry: Registry
    updates: Updates
    supervisor: Supervisor
    editor: ModelEditor
    downloads: Downloads
    library: Library
    catalog: Catalog
    hub: HubAdvisor


def build():
    # first: sets the language of every message; the models folder can't move during a download
    settings = Settings(config.SETTINGS_FILE, models_busy=lambda: downloads.any_running())
    models_dir = settings.models_dir
    registry = Registry(config.ENGINES_FILE, config.MODELS_FILE, listen_port=config.LISTEN_PORT)
    updates = Updates(registry, config.LOG_DIR)
    supervisor = Supervisor(registry, updates, gpu=gpu.query, keep_awake=KeepAwake(), log_dir=config.LOG_DIR,
                            models_dir=models_dir, default_baseline_mib=config.DEFAULT_BASELINE_MIB)
    downloads = Downloads(models_dir, config.LOG_DIR)
    library = Library(models_dir, registry, downloads)
    catalog = Catalog(config.CATALOG_DIR, registry, config.LOG_DIR, models_dir)
    hub = HubAdvisor(registry, catalog, library, gpu=gpu.query, baseline_mib=supervisor.baseline_mib)
    return App(settings, registry, updates, supervisor, ModelEditor(registry, supervisor), downloads, library,
               catalog, hub)
