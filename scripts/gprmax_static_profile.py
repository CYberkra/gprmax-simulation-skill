from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

# Reference example of a reviewed static-deck profile (gprMax 3.1.6 legacy
# build). This is a *project profile*, not a core constraint: the generic
# schema accepts any structurally valid profile. Do not hard-code a version
# into the core validator — the manifest declares its own gprmax_version and
# the profile's internal_version, and the audit only requires them to agree.
LEGACY_STATIC_DECK_PROFILE: Mapping[str, str] = MappingProxyType(
    {
        "profile_id": "gprmax-legacy-static-deck-v1",
        "source_archive_sha256": (
            "b98b4ee28f56a993506c51ac1acdb831657fcb1809e1efe6f6c6cd7eb627f75e"
        ),
        "source_tree_label": "gprMax-v.3.1.7",
        "internal_version": "3.1.6",
        "codename": "Big Smoke",
    }
)

_REQUIRED_FIELDS = tuple(LEGACY_STATIC_DECK_PROFILE)


def validated_legacy_static_deck_profile(value: object) -> dict[str, str]:
    """Validate a static-deck profile structurally.

    The profile must contain exactly the reviewed fields, each a non-empty
    string. Values are *not* constrained to the legacy example — any build's
    profile is valid as long as it is complete and well-formed. This keeps
    the generic skill version-agnostic.
    """
    if not isinstance(value, Mapping) or set(value) != set(_REQUIRED_FIELDS):
        raise ValueError(
            "static_deck_profile must contain exactly the fields: "
            + ", ".join(_REQUIRED_FIELDS)
        )
    profile: dict[str, str] = {}
    for field in _REQUIRED_FIELDS:
        observed = value.get(field)
        if not isinstance(observed, str) or not observed.strip():
            raise ValueError(f"static_deck_profile.{field} must be non-empty text")
        profile[field] = observed.strip()
    return profile
