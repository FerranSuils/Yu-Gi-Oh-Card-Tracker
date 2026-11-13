"""Game catalogs. Importing this package registers every provider."""

from src.services.catalog.registry import PROVIDERS, game_ids, get_provider, register
from src.services.catalog.magic import MagicProvider
from src.services.catalog.pokemon import PokemonProvider
from src.services.catalog.yugioh import YugiohProvider

if not PROVIDERS:
    register(YugiohProvider())
    register(MagicProvider())
    register(PokemonProvider())

__all__ = ['PROVIDERS', 'game_ids', 'get_provider', 'register']
