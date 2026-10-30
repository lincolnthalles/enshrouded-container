"""Backup Categories — the three storage locations."""

from enum import StrEnum


class Category(StrEnum):
    LIVE = "live"
    COLD = "cold"
    EMERGENCY = "emergency"


CATEGORIES: tuple[Category, ...] = tuple(Category)
