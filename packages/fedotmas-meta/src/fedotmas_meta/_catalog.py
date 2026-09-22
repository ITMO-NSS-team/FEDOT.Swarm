from __future__ import annotations

from collections.abc import Iterator

from fedotmas_meta._spec import Preset, SpecError


class Catalog:
    """The caller's menu of presets, addressed by name. `menu` is the listing a selector (or a
    meta-agent) ranks a task against, which is why every preset carries a one-line hint."""

    def __init__(self, *presets: Preset) -> None:
        self._by_name = {p.name: p for p in presets}
        if len(self._by_name) != len(presets):
            names = [p.name for p in presets]
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"duplicate preset names: {dupes}")

    def __getitem__(self, name: str) -> Preset:
        if name not in self._by_name:
            raise SpecError(
                f"no preset {name!r}: the catalog holds {sorted(self._by_name)}"
            )
        return self._by_name[name]

    def __contains__(self, name: object) -> bool:
        return name in self._by_name

    def __iter__(self) -> Iterator[Preset]:
        return iter(self._by_name.values())

    def __len__(self) -> int:
        return len(self._by_name)

    def menu(self) -> str:
        return "\n".join(f"{p.name}: {p.hint}" for p in self)
