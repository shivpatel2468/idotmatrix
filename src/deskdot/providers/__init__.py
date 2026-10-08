"""Background data sources. Apps read `provider.value`; they never do I/O themselves."""

from .airquality import AirQualityProvider
from .anki import AnkiProvider
from .asteroids import AsteroidsProvider
from .avatars import AvatarsProvider
from .base import Hub, Provider
from .bikeshare import BikeShareProvider
from .bitcoin import BitcoinProvider
from .calendar import CalendarProvider
from .camera import CameraProvider
from .capture import AudioProvider, GitHubProvider, ScreenProvider
from .chess import ChessProvider
from .ci import CIProvider
from .cryptomarket import CryptoMarketProvider
from .currency import CurrencyProvider
from .custom import CustomAppsProvider
from .daily import DailyProvider
from .earthevents import EarthEventsProvider
from .flags import FlagsProvider
from .flights import FlightsProvider
from .gamedeals import GameDealsProvider
from .gameserver import GameServerProvider
from .headlines import HeadlinesProvider
from .holidays import HolidaysProvider
from .homeassistant import HomeAssistantProvider
from .hourly import HourlyProvider
from .idle import IdleProvider
from .longweekend import LongWeekendProvider
from .lyrics import LyricsProvider
from .markets import MarketsProvider
from .media import MediaProvider
from .mediaserver import MediaServerProvider
from .notifications import NotificationsProvider
from .ntfy import NtfyProvider
from .obs import OBSProvider
from .onair import OnAirProvider
from .photos import PhotosProvider
from .planets import PlanetsProvider
from .pokedex import PokedexProvider
from .printer import PrinterProvider
from .quakes import QuakesProvider
from .racing import RacingProvider
from .rainradar import RainRadarProvider
from .sky import SkyProvider
from .space import IssProvider, SpaceProvider
from .spaceweather import SpaceWeatherProvider
from .sports import SportsProvider
from .stocks import StocksProvider
from .system import SystemProvider
from .tides import TidesProvider
from .trivia import TriviaProvider
from .tvguide import TvGuideProvider
from .uptime import UptimeProvider
from .wear import WearProvider
from .weather import WeatherProvider
from .wiki import WikiProvider
from .window import WindowProvider

ALL: tuple[type[Provider], ...] = (  # type: ignore[type-arg]
    SystemProvider,
    WeatherProvider,
    MarketsProvider,
    SportsProvider,
    MediaProvider,
    LyricsProvider,
    WindowProvider,
    ScreenProvider,
    AudioProvider,
    GitHubProvider,
    CameraProvider,
    NotificationsProvider,
    FlightsProvider,
    StocksProvider,
    SpaceProvider,
    IssProvider,
    SkyProvider,
    QuakesProvider,
    RainRadarProvider,
    AirQualityProvider,
    HolidaysProvider,
    DailyProvider,
    TriviaProvider,
    HeadlinesProvider,
    CurrencyProvider,
    PhotosProvider,
    PokedexProvider,
    AvatarsProvider,
    ChessProvider,
    GameDealsProvider,
    OnAirProvider,
    IdleProvider,
    NtfyProvider,
    HomeAssistantProvider,
    CustomAppsProvider,
    CIProvider,
    UptimeProvider,
    OBSProvider,
    PrinterProvider,
    MediaServerProvider,
    AnkiProvider,
    PlanetsProvider,
    WearProvider,
    TidesProvider,
    CalendarProvider,
    # 3.6.0: more keyless public APIs (docs/PUBLIC_APIS.md)
    AsteroidsProvider,
    BikeShareProvider,
    BitcoinProvider,
    CryptoMarketProvider,
    EarthEventsProvider,
    FlagsProvider,
    GameServerProvider,
    HourlyProvider,
    LongWeekendProvider,
    RacingProvider,
    SpaceWeatherProvider,
    TvGuideProvider,
    WikiProvider,
)


def build_hub(store, on_change) -> Hub:  # type: ignore[no-untyped-def]
    hub = Hub(store, on_change)
    for cls in ALL:
        hub.providers[cls.name] = cls(hub)
    from ..platforms import current

    if current() == "web":  # a browser tab: camera / screen / sound come from the page (getUserMedia & co.)
        from .webmedia import WEB

        for web_cls in WEB:
            hub.providers[web_cls.name] = web_cls(hub)
    return hub


__all__ = ["ALL", "Hub", "Provider", "build_hub"]
