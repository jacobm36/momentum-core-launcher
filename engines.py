"""Provider-independent selection of evidence-backed existing engine installations."""
from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional

Facts = Dict[str, object]
Build = Mapping[str, object]


def matches(facts: Mapping[str, object], build: Build) -> bool:
    return facts.get("installed") is True and all(
        facts.get(key) == value for key, value in build.items()
        if not (key == "scope" and build.get("provider") == "flatpak"
                and facts.get("scope") in ("user", "system")))


def identity(facts: Mapping[str, object]) -> dict:
    return {key: facts.get(key) for key in (
        "provider", "scope", "app_id", "arch", "branch", "origin",
        "version", "commit", "executable", "sha256", "launch_argv", "managed")}


@dataclass
class Selection:
    facts: Facts
    build: Build
    status: str
    candidates: List[Facts]
    supported_builds: List[Build]

    def details(self) -> dict:
        return {"status": self.status, "selected": identity(self.facts),
                "candidates": [identity(candidate) for candidate in self.candidates],
                "supported_builds": self.supported_builds}


def select(preferred: Facts, builds: List[Build],
           discover: Optional[Callable[[], List[Facts]]] = None) -> Selection:
    if not builds:
        raise ValueError("Engine selection requires an explicit supported build.")
    candidates = [preferred]
    for build in builds:
        if matches(preferred, build):
            return Selection(preferred, build, "supported", candidates, builds)
    if discover is not None and preferred.get("installed"):
        for candidate in discover():
            if not candidate.get("installed") or any(
                    identity(candidate) == identity(old) for old in candidates):
                continue
            candidates.append(candidate)
        for candidate in candidates[1:]:
            for build in builds:
                if matches(candidate, build):
                    return Selection(candidate, build, "supported", candidates, builds)
    return Selection(preferred, builds[0],
                     "untested" if preferred.get("installed") else "missing", candidates, builds)
