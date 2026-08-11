from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType


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


def validated_legacy_static_deck_profile(value: object) -> dict[str, str]:
    """Return the exact reviewed profile or reject ambiguous source identity."""
    if not isinstance(value, Mapping) or set(value) != set(
        LEGACY_STATIC_DECK_PROFILE
    ):
        raise ValueError("static_deck_profile must contain exactly the reviewed fields")
    profile: dict[str, str] = {}
    for field, expected in LEGACY_STATIC_DECK_PROFILE.items():
        observed = value.get(field)
        if not isinstance(observed, str) or observed != expected:
            raise ValueError(
                f"static_deck_profile.{field} must match the reviewed source profile"
            )
        profile[field] = observed
    return profile
