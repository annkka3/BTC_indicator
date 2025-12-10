# app/presentation/handlers/handler_factory.py
"""
Factory for creating and initializing handlers and services.

Этот модуль реализует паттерн Factory для создания и инициализации
всех handlers и services с правильными зависимостями.

Архитектура:
- Presentation Layer - создание компонентов presentation layer
- Использует паттерн Factory для централизованного создания объектов
- Использует паттерн Singleton для кэширования созданных объектов
- Реализует Dependency Injection для передачи зависимостей

Поток создания:
1. Создаются services с их зависимостями
2. Создаются handlers с инжектированными services
3. Все объекты кэшируются для переиспользования

Пример использования:
    factory = HandlerFactory(db)
    handlers = factory.get_handlers()
    services = factory.get_services()
    
    # Использование handler
    bubbles_handler = handlers["bubbles"]
    await bubbles_handler.handle_bubbles_command(update, context)
"""

from typing import Dict
from .base_handler import BaseHandler
from .command_handler import CommandHandler
from .bubbles_handler import BubblesHandler
from .report_handler import ReportHandler
from .top_flop_handler import TopFlopHandler
from .twap_handler import TWAPHandler
from .chart_handler import ChartHandler
from .analytics_handler import AnalyticsHandler
from .indices_handler import IndicesHandler
from .options_handler import OptionsHandler
from .forecast_handler import ForecastHandler
from .events_handler import EventsHandler
from .diag_handler import DiagHandler
from .market_doctor_handler import MarketDoctorHandler
from .market_doctor_profile_handler import MarketDoctorProfileHandler
from .market_doctor_watchlist_handler import MarketDoctorWatchlistHandler
from .market_doctor_backtest_handler import MarketDoctorBacktestHandler
from .market_doctor_tag_handler import MarketDoctorTagHandler
from ...application.services.market_data_service import MarketDataService
from ...application.services.bubbles_service import BubblesService
from ...application.services.twap_service import TWAPService
from ...application.services.traditional_markets_service import TraditionalMarketsService
from ...application.services.forecast_service import ForecastService


class HandlerFactory:
    """
    Фабрика для создания handlers и services.
    
    Этот класс реализует паттерн Factory для централизованного создания
    всех handlers и services с правильными зависимостями. Использует
    паттерн Singleton для кэширования созданных объектов.
    
    Порядок создания:
    1. Сначала создаются services (так как handlers зависят от них)
    2. Затем создаются handlers с инжектированными services
    3. Все объекты кэшируются для переиспользования
    
    Зависимости:
    - BubblesService зависит от MarketDataService
    - Все handlers зависят от db и services
    - ForecastService и TWAPService зависят от db
    
    Атрибуты:
        db: Database instance - экземпляр базы данных
        _services: Кэш созданных services (Singleton)
        _handlers: Кэш созданных handlers (Singleton)
    """
    
    def __init__(self, db):
        """
        Инициализация фабрики.
        
        Args:
            db: Database instance - экземпляр базы данных для передачи в handlers и services
        
        Пример:
            factory = HandlerFactory(db)
        """
        self.db = db
        self._services = None  # Кэш services (Singleton pattern)
        self._handlers = None  # Кэш handlers (Singleton pattern)
    
    def get_services(self) -> Dict:
        """
        Получить словарь всех сервисов.
        
        Создает и возвращает все application services с правильными зависимостями.
        Использует паттерн Singleton для кэширования созданных объектов.
        
        Зависимости между services:
        - MarketDataService - не имеет зависимостей
        - BubblesService - зависит от MarketDataService
                - TWAPService - зависит от db
                - TWAPDetectorService - не зависит от db
        - TraditionalMarketsService - не имеет зависимостей
        - ForecastService - зависит от db
        
        Returns:
            Dict: Словарь со всеми services:
                - "market_data_service": MarketDataService
                - "bubbles_service": BubblesService
                - "twap_service": TWAPService
                - "traditional_markets_service": TraditionalMarketsService
                - "forecast_service": ForecastService
        
        Пример:
            services = factory.get_services()
            market_data = services["market_data_service"]
            bubbles = services["bubbles_service"]
        """
        if self._services is None:
            # Создание services с правильными зависимостями
            # Порядок важен: сначала создаем независимые services
            market_data = MarketDataService()  # Не зависит от других services
            bubbles = BubblesService(market_data)  # Зависит от MarketDataService
            twap = TWAPService(self.db)  # Зависит от db
            from ...application.services.twap_detector_service import TWAPDetectorService
            twap_detector = TWAPDetectorService(db=self.db)  # Теперь использует db для кэшированных данных
            traditional_markets = TraditionalMarketsService()  # Не зависит от других
            forecast = ForecastService(self.db)  # Зависит от db
            
            # Сохраняем services в словарь для переиспользования
            self._services = {
                "market_data_service": market_data,
                "bubbles_service": bubbles,
                "twap_service": twap,
                "twap_detector_service": twap_detector,
                "traditional_markets_service": traditional_markets,
                "forecast_service": forecast,
            }
        return self._services
    
    def get_handlers(self) -> Dict[str, BaseHandler]:
        """
        Получить словарь всех handlers.
        
        Создает и возвращает все handlers с инжектированными services.
        Использует паттерн Singleton для кэширования созданных объектов.
        
        Все handlers получают:
        - db: Database instance
        - services: Словарь со всеми application services
        
        Returns:
            Dict[str, BaseHandler]: Словарь со всеми handlers:
                - "command": CommandHandler - базовые команды (start, help, info)
                - "bubbles": BubblesHandler - обработка пузырьков
                - "report": ReportHandler - отчеты (status, full)
                - "top_flop": TopFlopHandler - топ/флоп криптовалют
                - "twap": TWAPHandler - TWAP команда
                - "chart": ChartHandler - графики (chart, chart_album)
                - "analytics": AnalyticsHandler - аналитика (corr, beta, vol, etc.)
                - "indices": IndicesHandler - индексы (fng, altseason)
                - "options": OptionsHandler - опционы (btc_options, eth_options)
                - "forecast": ForecastHandler - ML прогнозы
                - "events": EventsHandler - события (events_add, events_list, etc.)
                - "diag": DiagHandler - диагностика
        
        Пример:
            handlers = factory.get_handlers()
            bubbles_handler = handlers["bubbles"]
            await bubbles_handler.handle_bubbles_command(update, context, tf="1h")
        """
        if self._handlers is None:
            # Получаем services (создаются при первом вызове)
            services = self.get_services()
            
            # Создаем handlers с инжектированными services
            # Все handlers получают db и services через dependency injection
            import logging
            logger = logging.getLogger("alt_forecast.handlers.factory")
            
            self._handlers = {}
            
            # Создаем handlers с обработкой ошибок
            handler_configs = [
                ("command", CommandHandler),
                ("bubbles", BubblesHandler),
                ("report", ReportHandler),
                ("top_flop", TopFlopHandler),
                ("twap", TWAPHandler),
                ("chart", ChartHandler),
                ("analytics", AnalyticsHandler),
                ("indices", IndicesHandler),
                ("options", OptionsHandler),
                ("forecast", ForecastHandler),
                ("events", EventsHandler),
                ("diag", DiagHandler),
                ("market_doctor", MarketDoctorHandler),
                ("market_doctor_profile", MarketDoctorProfileHandler),
                ("market_doctor_watchlist", MarketDoctorWatchlistHandler),
                ("market_doctor_backtest", MarketDoctorBacktestHandler),
                ("market_doctor_tag", MarketDoctorTagHandler),
            ]
            
            for name, handler_class in handler_configs:
                try:
                    self._handlers[name] = handler_class(self.db, services)
                    logger.debug(f"Successfully created handler: {name}")
                except Exception as e:
                    logger.exception(f"Failed to create handler {name}: {e}")
                    # Не прерываем создание других handlers
            
            logger.info(f"Created {len(self._handlers)} handlers out of {len(handler_configs)}")
        return self._handlers

