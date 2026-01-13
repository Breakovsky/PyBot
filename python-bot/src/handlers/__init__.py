"""
Handlers package for NetAdmin v3.0 Telegram Bot
"""

from .asset_search import handle_asset_search
from .diagnostics import handle_test_command

__all__ = ['handle_asset_search', 'handle_test_command']

