# app/domain/market_diagnostics/__init__.py
"""
Market Doctor - модуль диагностики рынка.
"""

from .indicators import IndicatorCalculator
from .features import FeatureExtractor, TrendState, VolatilityState, LiquidityState
from .analyzer import MarketAnalyzer, MarketDiagnostics, MarketPhase
from .reporter import ReportRenderer
from .trade_planner import TradePlanner
from .config import MarketDoctorConfig, DEFAULT_CONFIG
from .multi_tf import MultiTFDiagnostics
from .profile_provider import ProfileProvider, RiskProfile
from .anomaly_detector import AnomalyDetector
from .calibration_service import CalibrationService
from .pattern_utils import generate_pattern_id
from .tradability import TradabilityAnalyzer, TradabilityState, TradabilitySnapshot
from .structure_levels import Level, LevelKind, LevelOrigin, find_swings, build_support_resistance_levels
from .smc import SMCContext, StructureEvent, OrderBlock, FairValueGap, analyze_smc_context
from .waves import PriceLeg, analyze_legs, generate_legs_summary
from .scoring_engine import ScoringEngine, IndicatorGroup, GroupScore, TimeframeScore, MultiTFScore
from .compact_report import CompactReport, CompactReportRenderer
from .report_builder import ReportBuilder
from .setup_type import SetupType, SetupTypeDetector, SetupClassification, translate_setup_type
from .diagnostics_logger import DiagnosticsLogger, DiagnosticsSnapshot, DiagnosticsResult
from .calibration_analyzer import CalibrationAnalyzer, CalibrationReport, ScoreBucketStats, GroupWeightRecommendation
from .weights_storage import WeightsStorage
from .momentum_intelligence import MomentumIntelligence, MomentumInsight

__all__ = [
    # Core components
    "IndicatorCalculator",
    "FeatureExtractor",
    "MarketAnalyzer",
    "MarketDiagnostics",
    "MarketPhase",
    "TrendState",
    "VolatilityState",
    "LiquidityState",
    "ReportRenderer",
    "TradePlanner",
    "MarketDoctorConfig",
    "DEFAULT_CONFIG",
    "MultiTFDiagnostics",
    # Profile and personalization
    "ProfileProvider",
    "RiskProfile",
    # Anomaly detection
    "AnomalyDetector",
    # Calibration and reliability
    "CalibrationService",
    "generate_pattern_id",
    # Tradability
    "TradabilityAnalyzer",
    "TradabilityState",
    "TradabilitySnapshot",
    # Structure and levels
    "Level",
    "LevelKind",
    "LevelOrigin",
    "find_swings",
    "build_support_resistance_levels",
    # SMC
    "SMCContext",
    "StructureEvent",
    "OrderBlock",
    "FairValueGap",
    "analyze_smc_context",
    # Waves
    "PriceLeg",
    "analyze_legs",
    "generate_legs_summary",
    # New compact report system
    "ScoringEngine",
    "IndicatorGroup",
    "GroupScore",
    "TimeframeScore",
    "MultiTFScore",
    "CompactReport",
    "CompactReportRenderer",
    "ReportBuilder",
    # Setup types
    "SetupType",
    "SetupTypeDetector",
    "SetupClassification",
    "translate_setup_type",
    # Diagnostics logging and calibration
    "DiagnosticsLogger",
    "DiagnosticsSnapshot",
    "DiagnosticsResult",
    "CalibrationAnalyzer",
    "CalibrationReport",
    "ScoreBucketStats",
    "GroupWeightRecommendation",
    # Weights storage
    "WeightsStorage",
    # Momentum Intelligence Layer
    "MomentumIntelligence",
    "MomentumInsight",
]

