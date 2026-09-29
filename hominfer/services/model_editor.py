"""Model edits from the page (form, profiles): written to models.json through the registry."""
from ..errors import LaunchError
from ..i18n import tr

PROFILE_NAME_MAX = 80


class ModelEditor:
    def __init__(self, registry, supervisor):
        self.registry, self.supervisor = registry, supervisor

    def _not_running(self, mid):
        if self.supervisor.is_running(mid):
            raise LaunchError(tr("err.model_running"))

    def save(self, mid, fields):
        """Create or update; fields absent from the form (extra_args, conflicts...) are kept."""
        self._not_running(mid)
        self.registry.edit_models(lambda cfg: cfg.__setitem__(mid, {**cfg.get(mid, {}), **fields}))

    def delete(self, mid):
        self._not_running(mid)
        self.registry.edit_models(lambda cfg: cfg.pop(mid, None))

    def set_profile(self, mid, name, opts):
        """opts None deletes the profile."""
        name = str(name or "").strip()[:PROFILE_NAME_MAX]
        if not name:
            raise LaunchError(tr("prof.empty"))

        def change(cfg):
            profiles = cfg[mid].setdefault("profiles", {})
            if opts is None:
                profiles.pop(name, None)
            else:
                profiles[name] = {str(k): str(v) for k, v in opts.items()}
        self.registry.edit_models(change)
