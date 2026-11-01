"""Settings, and the host list in particular.

Engram depends on free services run by other people. Any of them can change an address,
start refusing automated uploads, or close. Keeping the host list in a file means a broken
default is a one line fix on the spot rather than a wait for a new release.

Overriding a host's URL template changes how codes for that host are read, so a code made
before the change may no longer resolve. That is the right trade when the alternative is a
host that does not work at all, but it is worth knowing.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .hosts import spec
from .hosts.spec import HostSpec

#: Set this to use a config file somewhere other than the usual place.
ENV_CONFIG = "ENGRAM_CONFIG"

APP_NAME = "Engram"
CONFIG_NAME = "config.json"

_HOST_FIELDS = {
    "uploadUrl": "upload_url",
    "urlTemplate": "url_template",
    "expiry": "expiry",
    "maxBytes": "max_bytes",
    "idWidth": "id_width",
    "uploadFilename": "upload_filename",
}


class ConfigError(Exception):
    """A config file that cannot be used."""


def app_data() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".config" / APP_NAME.lower()


def local_app_data() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME.lower()


def default_config_path() -> Path:
    override = os.environ.get(ENV_CONFIG)
    if override:
        return Path(override)
    return app_data() / CONFIG_NAME


def default_backup_root() -> Path:
    return local_app_data() / "backups"


@dataclass
class Config:
    """Everything adjustable, with the defaults that work out of the box."""

    game_dir: str | None = None
    save_dir: str | None = None
    host_order: list[str] = field(default_factory=lambda: list(spec.known_keys()))
    host_overrides: dict[str, dict] = field(default_factory=dict)
    slot_prefix: str = "EngramSave"
    backup_root: str | None = None
    path: Path | None = None

    @property
    def backups(self) -> Path:
        return Path(self.backup_root) if self.backup_root else default_backup_root()

    def resolve(self, host: HostSpec) -> HostSpec:
        """A host with this machine's overrides applied."""
        override = self.host_overrides.get(host.key)
        if not override:
            return host
        changes = {}
        for key, attribute in _HOST_FIELDS.items():
            if key not in override:
                continue
            value = override[key]
            if attribute in ("max_bytes", "id_width") and value is not None:
                value = int(value)
            changes[attribute] = value
        return host.replace(**changes) if changes else host

    def hosts(self) -> list[HostSpec]:
        """The hosts to try, in the order this machine wants them tried."""
        out: list[HostSpec] = []
        seen = set()
        for key in self.host_order:
            found = spec.by_key(key)
            if found is None or found.key in seen:
                continue
            seen.add(found.key)
            out.append(self.resolve(found))
        for host in spec.HOSTS:
            if host.key not in seen:
                out.append(self.resolve(host))
        return out

    def host_by_key(self, key: str) -> HostSpec | None:
        found = spec.by_key(key)
        return self.resolve(found) if found else None

    def host_by_tag(self, tag: str) -> HostSpec | None:
        found = spec.by_tag(tag)
        return self.resolve(found) if found else None

    def to_json(self) -> dict:
        return {
            "gameDir": self.game_dir,
            "saveDir": self.save_dir,
            "hostOrder": list(self.host_order),
            "hosts": self.host_overrides,
            "slotPrefix": self.slot_prefix,
            "backupRoot": self.backup_root,
        }


def load(path: str | os.PathLike | None = None) -> Config:
    """Read the config, falling back to defaults when there is not one yet."""
    target = Path(path) if path else default_config_path()
    if not target.is_file():
        return Config(path=target)
    try:
        data = json.loads(target.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"could not read {target}: {exc}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{target} does not hold a settings object")

    order = data.get("hostOrder")
    overrides = data.get("hosts")
    return Config(
        game_dir=data.get("gameDir") or None,
        save_dir=data.get("saveDir") or None,
        host_order=[str(k) for k in order] if isinstance(order, list) else list(spec.known_keys()),
        host_overrides={
            str(k): v for k, v in overrides.items() if isinstance(v, dict)
        }
        if isinstance(overrides, dict)
        else {},
        slot_prefix=str(data.get("slotPrefix") or "EngramSave"),
        backup_root=data.get("backupRoot") or None,
        path=target,
    )


def save(config: Config, path: str | os.PathLike | None = None) -> Path:
    """Write the config back out."""
    target = Path(path) if path else (config.path or default_config_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(config.to_json(), indent=2) + "\n", encoding="utf-8"
    )
    return target
