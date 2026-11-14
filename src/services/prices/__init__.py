"""Daily market prices for every game. Importing this package registers every source."""

from src.services.prices.registry import MARKETS, SOURCES, get_source, register, sources
from src.services.prices.magic import MagicCardmarketSource, MagicTcgplayerSource
from src.services.prices.pokemon import PokemonCardmarketSource, PokemonTcgplayerSource
from src.services.prices.yugioh import YugiohCardmarketSource, YugiohTcgplayerSource

if not SOURCES:
    for _source in (YugiohCardmarketSource(), YugiohTcgplayerSource(), MagicCardmarketSource(),
                    MagicTcgplayerSource(), PokemonCardmarketSource(), PokemonTcgplayerSource()):
        register(_source)
    from src.services.prices.cardtrader import build_source as _cardtrader

    _ct = _cardtrader()  # only with OPENYUGI_CARDTRADER_TOKEN
    if _ct is not None:
        register(_ct)

__all__ = ['MARKETS', 'get_source', 'register', 'sources']
