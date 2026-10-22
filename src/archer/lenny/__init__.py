"""
ARCHER LENNY Package (Phase 8, Spec Section 11).
Client and automation operators for ARCHER's own dedicated desk PC (LENNY).
"""

from archer.lenny.lenny_client import LennyClient, get_lenny_client

__all__ = ["LennyClient", "get_lenny_client"]
