# app/domain/market_diagnostics/backtest_analyzer.py
"""
Утилита для мини-backtest анализа исторических данных Market Doctor.

Анализирует сохраненные диагностики и вычисляет:
- pump_score decile → средний доход
- phase + trend → распределение доходности
- Hit-rate по фазам
"""

from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
from collections import defaultdict
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import hashlib

if TYPE_CHECKING:
    from ...domain.interfaces.idb import IDatabase
    from ...domain.interfaces.idiagnostics_repository import IDiagnosticsRepository
else:
    IDatabase = object
    IDiagnosticsRepository = object

from ..market_regime import GlobalRegime, GlobalRegimeAnalyzer


class BacktestAnalyzer:
    """Анализатор для backtest исторических данных Market Doctor."""
    
    def __init__(
        self,
        db: IDatabase,
        diagnostics_repo: IDiagnosticsRepository,
        regime_analyzer: 'GlobalRegimeAnalyzer'
    ):
        """
        Args:
            db: Database instance (реализует IDatabase интерфейс)
            diagnostics_repo: Репозиторий диагностик (реализует IDiagnosticsRepository интерфейс)
            regime_analyzer: Анализатор режима рынка
        """
        self.db = db
        self.diagnostics_repo = diagnostics_repo
        self.regime_analyzer = regime_analyzer
    
    def calculate_returns(
        self,
        symbol: str,
        timeframe: str,
        snapshot_timestamp: int,
        hours: int = 24
    ) -> Optional[float]:
        """
        Вычислить доходность через N часов после снимка диагностики.
        
        Args:
            symbol: Символ
            timeframe: Таймфрейм
            snapshot_timestamp: Timestamp снимка диагностики (ms)
            hours: Через сколько часов считать доходность
        
        Returns:
            Доходность в процентах или None если данных нет
        """
        # Конвертируем timestamp в секунды
        snapshot_ts_sec = snapshot_timestamp / 1000
        target_ts_sec = snapshot_ts_sec + (hours * 3600)
        target_ts_ms = int(target_ts_sec * 1000)
        
        # Получаем цену на момент снимка
        cur = self.db.conn.cursor()
        cur.execute("""
            SELECT close_price FROM market_diagnostics
            WHERE symbol = ? AND timeframe = ? AND timestamp = ?
        """, (symbol, timeframe, snapshot_timestamp))
        row = cur.fetchone()
        if not row:
            return None
        
        entry_price = row['close_price']
        
        # Получаем цену через N часов (из bars или из следующей диагностики)
        # Сначала пробуем найти следующую диагностику
        cur.execute("""
            SELECT close_price FROM market_diagnostics_snapshots
            WHERE symbol = ? AND timeframe = ?
            AND timestamp > ?
            ORDER BY timestamp ASC
            LIMIT 1
        """, (symbol, timeframe, snapshot_timestamp))
        row = cur.fetchone()
        
        if row:
            exit_price = row['close_price']
            return ((exit_price - entry_price) / entry_price) * 100
        
        # Если нет следующей диагностики, пробуем получить из bars
        try:
            # Конвертируем timeframe в формат для bars
            tf_map = {"1h": "1h", "4h": "4h", "1d": "1d"}
            bars_tf = tf_map.get(timeframe)
            if not bars_tf:
                return None
            
            # Получаем бары после timestamp
            bars = self.db.last_n(symbol, bars_tf, 100)
            if not bars:
                return None
            
            # Находим бар ближайший к target_ts_ms
            for bar in bars:
                ts, o, h, l, c, v = bar
                if ts >= target_ts_ms:
                    exit_price = c
                    return ((exit_price - entry_price) / entry_price) * 100
            
            # Если не нашли, берем последний бар
            if bars:
                ts, o, h, l, c, v = bars[-1]
                exit_price = c
                return ((exit_price - entry_price) / entry_price) * 100
        except Exception:
            pass
        
        return None
    
    def analyze_pump_score_deciles(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        hours: int = 24
    ) -> Dict[str, Dict]:
        """
        Анализ доходности по децилям pump_score.
        
        Args:
            symbol: Фильтр по символу (None = все символы)
            timeframe: Фильтр по таймфрейму (None = все таймфреймы)
            hours: Через сколько часов считать доходность
        
        Returns:
            Словарь {decile: {avg_return, count, win_rate}}
        """
        # Получаем все снимки
        snapshots = self.diagnostics_repo.get_snapshots(
            symbol=symbol,
            timeframe=timeframe,
            limit=10000
        )
        
        if not snapshots:
            return {}
        
        # Вычисляем доходность для каждого снимка
        results = []
        for snapshot in snapshots:
            pump_score = snapshot.get('pump_score', 0.0)
            ret = self.calculate_returns(
                snapshot['symbol'],
                snapshot['timeframe'],
                snapshot['timestamp'],
                hours
            )
            if ret is not None:
                results.append({
                    'pump_score': pump_score,
                    'return': ret
                })
        
        if not results:
            return {}
        
        # Разбиваем на децили
        df = pd.DataFrame(results)
        df['decile'] = pd.qcut(df['pump_score'], q=10, labels=False, duplicates='drop')
        
        # Агрегируем по децилям
        decile_stats = {}
        for decile in range(10):
            decile_data = df[df['decile'] == decile]
            if len(decile_data) > 0:
                decile_stats[f"decile_{decile+1}"] = {
                    'avg_return': decile_data['return'].mean(),
                    'median_return': decile_data['return'].median(),
                    'count': len(decile_data),
                    'win_rate': (decile_data['return'] > 0).mean() * 100,
                    'avg_pump_score': decile_data['pump_score'].mean()
                }
        
        return decile_stats
    
    def analyze_phase_trend_distribution(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        hours: int = 24
    ) -> Dict[str, Dict]:
        """
        Анализ распределения доходности по комбинациям phase + trend.
        
        Args:
            symbol: Фильтр по символу
            timeframe: Фильтр по таймфрейму
            hours: Через сколько часов считать доходность
        
        Returns:
            Словарь {phase_trend: {avg_return, count, win_rate, ...}}
        """
        snapshots = self.diagnostics_repo.get_snapshots(
            symbol=symbol,
            timeframe=timeframe,
            limit=10000
        )
        
        if not snapshots:
            return {}
        
        # Вычисляем доходность для каждого снимка
        results = []
        for snapshot in snapshots:
            phase = snapshot.get('phase', '')
            trend = snapshot.get('trend', '')
            ret = self.calculate_returns(
                snapshot['symbol'],
                snapshot['timeframe'],
                snapshot['timestamp'],
                hours
            )
            if ret is not None:
                results.append({
                    'phase': phase,
                    'trend': trend,
                    'phase_trend': f"{phase}_{trend}",
                    'return': ret
                })
        
        if not results:
            return {}
        
        # Агрегируем по комбинациям phase + trend
        df = pd.DataFrame(results)
        phase_trend_stats = {}
        
        for phase_trend in df['phase_trend'].unique():
            group_data = df[df['phase_trend'] == phase_trend]
            phase_trend_stats[phase_trend] = {
                'avg_return': group_data['return'].mean(),
                'median_return': group_data['return'].median(),
                'count': len(group_data),
                'win_rate': (group_data['return'] > 0).mean() * 100,
                'std_return': group_data['return'].std(),
                'min_return': group_data['return'].min(),
                'max_return': group_data['return'].max()
            }
        
        return phase_trend_stats
    
    def generate_backtest_report(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        hours: int = 24
    ) -> str:
        """
        Сгенерировать текстовый отчет по backtest анализу.
        
        Args:
            symbol: Фильтр по символу
            timeframe: Фильтр по таймфрейму
            hours: Через сколько часов считать доходность
        
        Returns:
            Текстовый отчет
        """
        lines = []
        lines.append("📊 <b>Backtest анализ Market Doctor</b>")
        
        if symbol:
            lines.append(f"Символ: <b>{symbol}</b>")
        if timeframe:
            lines.append(f"Таймфрейм: <b>{timeframe}</b>")
        lines.append(f"Период анализа: <b>{hours} часов</b>")
        lines.append("")
        
        # Анализ по децилям pump_score
        decile_stats = self.analyze_pump_score_deciles(symbol, timeframe, hours)
        if decile_stats:
            lines.append("📈 <b>Доходность по децилям pump_score:</b>")
            lines.append("")
            
            for decile_name, stats in sorted(decile_stats.items()):
                decile_num = decile_name.split('_')[1]
                lines.append(
                    f"Дециль {decile_num} (pump_score ~{stats['avg_pump_score']:.2f}):\n"
                    f"  Средняя доходность: <b>{stats['avg_return']:.2f}%</b>\n"
                    f"  Медианная доходность: {stats['median_return']:.2f}%\n"
                    f"  Win rate: {stats['win_rate']:.1f}%\n"
                    f"  Количество снимков: {stats['count']}"
                )
                lines.append("")
        
        # Анализ по phase + trend
        phase_trend_stats = self.analyze_phase_trend_distribution(symbol, timeframe, hours)
        if phase_trend_stats:
            lines.append("🎯 <b>Распределение доходности по phase + trend:</b>")
            lines.append("")
            
            # Сортируем по средней доходности
            sorted_stats = sorted(
                phase_trend_stats.items(),
                key=lambda x: x[1]['avg_return'],
                reverse=True
            )
            
            for phase_trend, stats in sorted_stats:
                phase, trend = phase_trend.rsplit('_', 1)
                lines.append(
                    f"<b>{phase} + {trend}:</b>\n"
                    f"  Средняя доходность: <b>{stats['avg_return']:.2f}%</b>\n"
                    f"  Медианная доходность: {stats['median_return']:.2f}%\n"
                    f"  Win rate: {stats['win_rate']:.1f}%\n"
                    f"  Количество: {stats['count']}\n"
                    f"  Диапазон: {stats['min_return']:.2f}% ... {stats['max_return']:.2f}%"
                )
                lines.append("")
        
        if not decile_stats and not phase_trend_stats:
            lines.append("❌ Недостаточно данных для анализа.")
            lines.append("Нужно больше сохраненных диагностик.")
        
        return "\n".join(lines)
    
    def analyze_per_asset_regime(
        self,
        symbol: Optional[str] = None,
        regime: Optional[GlobalRegime] = None,
        phase: Optional[str] = None,
        hours: int = 24
    ) -> Dict[str, Dict]:
        """
        Анализ hit_rate и avg_return по symbol, regime, phase.
        
        Args:
            symbol: Фильтр по символу (None = все символы)
            regime: Фильтр по режиму (None = все режимы)
            phase: Фильтр по фазе (None = все фазы)
            hours: Через сколько часов считать доходность
        
        Returns:
            Словарь с агрегированной статистикой:
            {
                'by_symbol': {symbol: {hit_rate, avg_return, count}},
                'by_regime': {regime: {hit_rate, avg_return, count}},
                'by_phase': {phase: {hit_rate, avg_return, count}},
                'by_symbol_regime': {(symbol, regime): {hit_rate, avg_return, count}},
                'by_regime_phase': {(regime, phase): {hit_rate, avg_return, count}}
            }
        """
        # Получаем все снимки
        snapshots = self.diagnostics_repo.get_snapshots(
            symbol=symbol,
            phase=phase,
            limit=50000
        )
        
        if not snapshots:
            return {}
        
        # Для каждого снимка определяем режим и вычисляем доходность
        results = []
        for snapshot in snapshots:
            snap_symbol = snapshot['symbol']
            snap_phase = snapshot.get('phase', '')
            snap_timestamp = snapshot['timestamp']
            
            # Определяем режим на момент снимка
            # TODO: Сохранять regime в snapshot для более точного анализа
            # Пока используем текущий режим как приближение
            current_regime_snapshot = self.regime_analyzer.analyze_current_regime()
            snap_regime = current_regime_snapshot.regime
            
            # Применяем фильтры
            if regime and snap_regime != regime:
                continue
            
            # Вычисляем доходность
            ret = self.calculate_returns(
                snap_symbol,
                snapshot['timeframe'],
                snap_timestamp,
                hours
            )
            
            if ret is not None:
                results.append({
                    'symbol': snap_symbol,
                    'regime': snap_regime.value,
                    'phase': snap_phase,
                    'pump_score': snapshot.get('pump_score', 0.0),
                    'return': ret,
                    'is_win': ret > 0
                })
        
        if not results:
            return {}
        
        df = pd.DataFrame(results)
        
        # Агрегируем по разным измерениям
        stats = {}
        
        # По символам
        if len(df['symbol'].unique()) > 1:
            symbol_stats = df.groupby('symbol').agg({
                'return': ['mean', 'count'],
                'is_win': 'mean'
            }).to_dict()
            
            stats['by_symbol'] = {
                sym: {
                    'hit_rate': symbol_stats[('is_win', 'mean')].get(sym, 0.0),
                    'avg_return': symbol_stats[('return', 'mean')].get(sym, 0.0),
                    'count': int(symbol_stats[('return', 'count')].get(sym, 0))
                }
                for sym in df['symbol'].unique()
            }
        
        # По режимам
        if len(df['regime'].unique()) > 1:
            regime_stats = df.groupby('regime').agg({
                'return': ['mean', 'count'],
                'is_win': 'mean'
            }).to_dict()
            
            stats['by_regime'] = {
                reg: {
                    'hit_rate': regime_stats[('is_win', 'mean')].get(reg, 0.0),
                    'avg_return': regime_stats[('return', 'mean')].get(reg, 0.0),
                    'count': int(regime_stats[('return', 'count')].get(reg, 0))
                }
                for reg in df['regime'].unique()
            }
        
        # По фазам
        if len(df['phase'].unique()) > 1:
            phase_stats = df.groupby('phase').agg({
                'return': ['mean', 'count'],
                'is_win': 'mean'
            }).to_dict()
            
            stats['by_phase'] = {
                ph: {
                    'hit_rate': phase_stats[('is_win', 'mean')].get(ph, 0.0),
                    'avg_return': phase_stats[('return', 'mean')].get(ph, 0.0),
                    'count': int(phase_stats[('return', 'count')].get(ph, 0))
                }
                for ph in df['phase'].unique()
            }
        
        # По комбинации symbol + regime
        if len(df.groupby(['symbol', 'regime'])) > 1:
            symbol_regime_stats = df.groupby(['symbol', 'regime']).agg({
                'return': ['mean', 'count'],
                'is_win': 'mean'
            }).to_dict()
            
            stats['by_symbol_regime'] = {}
            for (sym, reg), group in df.groupby(['symbol', 'regime']):
                key = (sym, reg)
                stats['by_symbol_regime'][key] = {
                    'hit_rate': group['is_win'].mean(),
                    'avg_return': group['return'].mean(),
                    'count': len(group)
                }
        
        # По комбинации regime + phase
        if len(df.groupby(['regime', 'phase'])) > 1:
            stats['by_regime_phase'] = {}
            for (reg, ph), group in df.groupby(['regime', 'phase']):
                key = (reg, ph)
                stats['by_regime_phase'][key] = {
                    'hit_rate': group['is_win'].mean(),
                    'avg_return': group['return'].mean(),
                    'count': len(group)
                }
        
        return stats
    
    def analyze_pump_score_bins_by_regime(
        self,
        symbol: Optional[str] = None,
        regime: Optional[GlobalRegime] = None,
        phase: Optional[str] = None,
        bins: int = 10,
        hours: int = 24
    ) -> Dict[str, Dict]:
        """
        Анализ доходности по бинам pump_score с разбивкой по режиму.
        
        Args:
            symbol: Фильтр по символу
            regime: Фильтр по режиму
            phase: Фильтр по фазе
            bins: Количество бинов (по умолчанию 10)
            hours: Через сколько часов считать доходность
        
        Returns:
            Словарь {bin_range: {avg_return, hit_rate, count, regime}}
        """
        stats = self.analyze_per_asset_regime(symbol, regime, phase, hours)
        
        # Получаем снимки с доходностью
        snapshots = self.diagnostics_repo.get_snapshots(
            symbol=symbol,
            phase=phase,
            limit=10000
        )
        
        if not snapshots:
            return {}
        
        # Вычисляем доходность и определяем режим
        results = []
        for snapshot in snapshots:
            ret = self.calculate_returns(
                snapshot['symbol'],
                snapshot['timeframe'],
                snapshot['timestamp'],
                hours
            )
            
            if ret is not None:
                current_regime = self.regime_analyzer.analyze_current_regime().regime
                if regime and current_regime != regime:
                    continue
                
                results.append({
                    'pump_score': snapshot.get('pump_score', 0.0),
                    'return': ret,
                    'regime': current_regime.value
                })
        
        if not results:
            return {}
        
        df = pd.DataFrame(results)
        
        # Разбиваем на бины
        df['bin'] = pd.cut(df['pump_score'], bins=bins, labels=False, duplicates='drop')
        
        # Агрегируем по бинам
        bin_stats = {}
        for bin_num in range(bins):
            bin_data = df[df['bin'] == bin_num]
            if len(bin_data) > 0:
                bin_range = (
                    bin_data['pump_score'].min(),
                    bin_data['pump_score'].max()
                )
                bin_stats[f"bin_{bin_num+1}"] = {
                    'pump_score_range': bin_range,
                    'avg_return': bin_data['return'].mean(),
                    'hit_rate': (bin_data['return'] > 0).mean(),
                    'count': len(bin_data),
                    'regime_distribution': bin_data['regime'].value_counts().to_dict()
                }
        
        return bin_stats
    
    def analyze_levels_distance_impact(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        hours: int = 24
    ) -> Dict[str, Dict]:
        """
        Анализ влияния расстояния до уровней на доходность.
        
        Args:
            symbol: Фильтр по символу
            timeframe: Фильтр по таймфрейму
            hours: Через сколько часов считать доходность
        
        Returns:
            Словарь с статистикой по расстояниям до уровней
        """
        snapshots = self.diagnostics_repo.get_snapshots(
            symbol=symbol,
            timeframe=timeframe,
            limit=10000
        )
        
        if not snapshots:
            return {}
        
        results = []
        for snapshot in snapshots:
            ret = self.calculate_returns(
                snapshot['symbol'],
                snapshot['timeframe'],
                snapshot['timestamp'],
                hours
            )
            
            if ret is not None:
                extra = snapshot.get('extra_metrics', {})
                levels = extra.get('levels', {})
                
                result = {
                    'return': ret,
                    'is_win': ret > 0
                }
                
                # Расстояние до поддержки
                if 'distance_to_support_pct' in levels:
                    result['distance_to_support_pct'] = levels['distance_to_support_pct']
                    result['support_strength'] = levels.get('nearest_support_strength', 0.0)
                
                # Расстояние до сопротивления
                if 'distance_to_resistance_pct' in levels:
                    result['distance_to_resistance_pct'] = levels['distance_to_resistance_pct']
                    result['resistance_strength'] = levels.get('nearest_resistance_strength', 0.0)
                
                results.append(result)
        
        if not results:
            return {}
        
        df = pd.DataFrame(results)
        stats = {}
        
        # Анализ по расстоянию до поддержки
        if 'distance_to_support_pct' in df.columns:
            # Разбиваем на бины по расстоянию до поддержки
            df['support_distance_bin'] = pd.cut(
                df['distance_to_support_pct'],
                bins=[0, 1, 3, 5, 10, float('inf')],
                labels=['<1%', '1-3%', '3-5%', '5-10%', '>10%']
            )
            
            support_stats = {}
            for bin_label in df['support_distance_bin'].cat.categories:
                bin_data = df[df['support_distance_bin'] == bin_label]
                if len(bin_data) > 0:
                    support_stats[str(bin_label)] = {
                        'avg_return': bin_data['return'].mean(),
                        'hit_rate': bin_data['is_win'].mean(),
                        'count': len(bin_data),
                        'median_return': bin_data['return'].median()
                    }
            
            stats['by_support_distance'] = support_stats
        
        # Анализ по расстоянию до сопротивления
        if 'distance_to_resistance_pct' in df.columns:
            df['resistance_distance_bin'] = pd.cut(
                df['distance_to_resistance_pct'],
                bins=[0, 1, 3, 5, 10, float('inf')],
                labels=['<1%', '1-3%', '3-5%', '5-10%', '>10%']
            )
            
            resistance_stats = {}
            for bin_label in df['resistance_distance_bin'].cat.categories:
                bin_data = df[df['resistance_distance_bin'] == bin_label]
                if len(bin_data) > 0:
                    resistance_stats[str(bin_label)] = {
                        'avg_return': bin_data['return'].mean(),
                        'hit_rate': bin_data['is_win'].mean(),
                        'count': len(bin_data),
                        'median_return': bin_data['return'].median()
                    }
            
            stats['by_resistance_distance'] = resistance_stats
        
        return stats
    
    def analyze_order_block_impact(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        hours: int = 24
    ) -> Dict[str, Dict]:
        """
        Анализ влияния order blocks на доходность.
        
        Сравнивает доходность сигналов, где был demand OB ниже цены, 
        с сигналами без OB.
        
        Args:
            symbol: Фильтр по символу
            timeframe: Фильтр по таймфрейму
            hours: Через сколько часов считать доходность
        
        Returns:
            Словарь со статистикой по order blocks
        """
        snapshots = self.diagnostics_repo.get_snapshots(
            symbol=symbol,
            timeframe=timeframe,
            limit=10000
        )
        
        if not snapshots:
            return {}
        
        with_ob = []
        without_ob = []
        
        for snapshot in snapshots:
            ret = self.calculate_returns(
                snapshot['symbol'],
                snapshot['timeframe'],
                snapshot['timestamp'],
                hours
            )
            
            if ret is not None:
                extra = snapshot.get('extra_metrics', {})
                smc = extra.get('smc', {})
                
                has_demand_ob = smc.get('has_demand_ob_below', False)
                
                result = {
                    'return': ret,
                    'is_win': ret > 0,
                    'pump_score': snapshot.get('pump_score', 0.0)
                }
                
                if has_demand_ob:
                    result['distance_to_ob_pct'] = smc.get('distance_to_demand_ob_pct', 0.0)
                    result['ob_strength'] = smc.get('demand_ob_strength', 0.0)
                    with_ob.append(result)
                else:
                    without_ob.append(result)
        
        stats = {}
        
        if with_ob:
            df_with = pd.DataFrame(with_ob)
            stats['with_demand_ob'] = {
                'avg_return': df_with['return'].mean(),
                'median_return': df_with['return'].median(),
                'hit_rate': df_with['is_win'].mean(),
                'count': len(df_with),
                'std_return': df_with['return'].std()
            }
            
            # Анализ по расстоянию до OB
            if 'distance_to_ob_pct' in df_with.columns:
                df_with['ob_distance_bin'] = pd.cut(
                    df_with['distance_to_ob_pct'],
                    bins=[0, 1, 3, 5, float('inf')],
                    labels=['<1%', '1-3%', '3-5%', '>5%']
                )
                
                ob_distance_stats = {}
                for bin_label in df_with['ob_distance_bin'].cat.categories:
                    bin_data = df_with[df_with['ob_distance_bin'] == bin_label]
                    if len(bin_data) > 0:
                        ob_distance_stats[str(bin_label)] = {
                            'avg_return': bin_data['return'].mean(),
                            'hit_rate': bin_data['is_win'].mean(),
                            'count': len(bin_data)
                        }
                
                stats['by_ob_distance'] = ob_distance_stats
        
        if without_ob:
            df_without = pd.DataFrame(without_ob)
            stats['without_demand_ob'] = {
                'avg_return': df_without['return'].mean(),
                'median_return': df_without['return'].median(),
                'hit_rate': df_without['is_win'].mean(),
                'count': len(df_without),
                'std_return': df_without['return'].std()
            }
        
        # Сравнение
        if with_ob and without_ob:
            stats['comparison'] = {
                'return_diff': stats['with_demand_ob']['avg_return'] - stats['without_demand_ob']['avg_return'],
                'hit_rate_diff': stats['with_demand_ob']['hit_rate'] - stats['without_demand_ob']['hit_rate']
            }
        
        return stats
    
    def analyze_premium_discount_impact(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        hours: int = 24
    ) -> Dict[str, Dict]:
        """
        Анализ влияния premium/discount зон на доходность.
        
        Сравнивает доходность сигналов из discount зоны vs premium зоны.
        
        Args:
            symbol: Фильтр по символу
            timeframe: Фильтр по таймфрейму
            hours: Через сколько часов считать доходность
        
        Returns:
            Словарь со статистикой по premium/discount
        """
        snapshots = self.diagnostics_repo.get_snapshots(
            symbol=symbol,
            timeframe=timeframe,
            limit=10000
        )
        
        if not snapshots:
            return {}
        
        discount_signals = []
        premium_signals = []
        neutral_signals = []
        
        for snapshot in snapshots:
            ret = self.calculate_returns(
                snapshot['symbol'],
                snapshot['timeframe'],
                snapshot['timestamp'],
                hours
            )
            
            if ret is not None:
                extra = snapshot.get('extra_metrics', {})
                smc = extra.get('smc', {})
                
                position = smc.get('current_position')
                position_in_range = smc.get('position_in_range')
                
                result = {
                    'return': ret,
                    'is_win': ret > 0,
                    'pump_score': snapshot.get('pump_score', 0.0)
                }
                
                if position == 'discount':
                    result['position_in_range'] = position_in_range
                    discount_signals.append(result)
                elif position == 'premium':
                    result['position_in_range'] = position_in_range
                    premium_signals.append(result)
                elif position == 'neutral' or position_in_range is not None:
                    result['position_in_range'] = position_in_range
                    neutral_signals.append(result)
        
        stats = {}
        
        if discount_signals:
            df_discount = pd.DataFrame(discount_signals)
            stats['discount_zone'] = {
                'avg_return': df_discount['return'].mean(),
                'median_return': df_discount['return'].median(),
                'hit_rate': df_discount['is_win'].mean(),
                'count': len(df_discount),
                'std_return': df_discount['return'].std()
            }
        
        if premium_signals:
            df_premium = pd.DataFrame(premium_signals)
            stats['premium_zone'] = {
                'avg_return': df_premium['return'].mean(),
                'median_return': df_premium['return'].median(),
                'hit_rate': df_premium['is_win'].mean(),
                'count': len(df_premium),
                'std_return': df_premium['return'].std()
            }
        
        if neutral_signals:
            df_neutral = pd.DataFrame(neutral_signals)
            stats['neutral_zone'] = {
                'avg_return': df_neutral['return'].mean(),
                'median_return': df_neutral['return'].median(),
                'hit_rate': df_neutral['is_win'].mean(),
                'count': len(df_neutral),
                'std_return': df_neutral['return'].std()
            }
        
        # Анализ по позиции внутри диапазона (для всех сигналов с position_in_range)
        all_with_position = discount_signals + premium_signals + neutral_signals
        if all_with_position:
            df_all = pd.DataFrame(all_with_position)
            if 'position_in_range' in df_all.columns:
                # Разбиваем на бины: discount (0-0.3), neutral (0.3-0.7), premium (0.7-1.0)
                df_all['zone_bin'] = pd.cut(
                    df_all['position_in_range'],
                    bins=[0, 0.3, 0.7, 1.0],
                    labels=['discount', 'neutral', 'premium']
                )
                
                zone_stats = {}
                for zone_label in df_all['zone_bin'].cat.categories:
                    zone_data = df_all[df_all['zone_bin'] == zone_label]
                    if len(zone_data) > 0:
                        zone_stats[str(zone_label)] = {
                            'avg_return': zone_data['return'].mean(),
                            'hit_rate': zone_data['is_win'].mean(),
                            'count': len(zone_data),
                            'median_return': zone_data['return'].median()
                        }
                
                stats['by_position_in_range'] = zone_stats
        
        # Сравнение discount vs premium
        if discount_signals and premium_signals:
            stats['discount_vs_premium'] = {
                'return_diff': stats['discount_zone']['avg_return'] - stats['premium_zone']['avg_return'],
                'hit_rate_diff': stats['discount_zone']['hit_rate'] - stats['premium_zone']['hit_rate']
            }
        
        return stats
    
    def generate_levels_smc_report(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        hours: int = 24
    ) -> str:
        """
        Сгенерировать отчет по анализу уровней и SMC метрик.
        
        Args:
            symbol: Фильтр по символу
            timeframe: Фильтр по таймфрейму
            hours: Через сколько часов считать доходность
        
        Returns:
            Текстовый отчет
        """
        lines = []
        lines.append("📊 <b>Backtest анализ: Уровни и SMC метрики</b>")
        
        if symbol:
            lines.append(f"Символ: <b>{symbol}</b>")
        if timeframe:
            lines.append(f"Таймфрейм: <b>{timeframe}</b>")
        lines.append(f"Период анализа: <b>{hours} часов</b>")
        lines.append("")
        
        # Анализ по расстоянию до уровней
        levels_stats = self.analyze_levels_distance_impact(symbol, timeframe, hours)
        if levels_stats:
            lines.append("📌 <b>Влияние расстояния до уровней:</b>")
            lines.append("")
            
            if 'by_support_distance' in levels_stats:
                lines.append("🟢 <b>Расстояние до поддержки:</b>")
                for distance, stats in levels_stats['by_support_distance'].items():
                    lines.append(
                        f"  {distance}: средняя доходность <b>{stats['avg_return']:.2f}%</b>, "
                        f"hit rate {stats['hit_rate']*100:.1f}%, количество {stats['count']}"
                    )
                lines.append("")
            
            if 'by_resistance_distance' in levels_stats:
                lines.append("🔴 <b>Расстояние до сопротивления:</b>")
                for distance, stats in levels_stats['by_resistance_distance'].items():
                    lines.append(
                        f"  {distance}: средняя доходность <b>{stats['avg_return']:.2f}%</b>, "
                        f"hit rate {stats['hit_rate']*100:.1f}%, количество {stats['count']}"
                    )
                lines.append("")
        
        # Анализ по order blocks
        ob_stats = self.analyze_order_block_impact(symbol, timeframe, hours)
        if ob_stats:
            lines.append("🟦 <b>Влияние Order Blocks:</b>")
            lines.append("")
            
            if 'with_demand_ob' in ob_stats:
                with_ob = ob_stats['with_demand_ob']
                lines.append(
                    f"С demand OB ниже цены:\n"
                    f"  Средняя доходность: <b>{with_ob['avg_return']:.2f}%</b>\n"
                    f"  Hit rate: {with_ob['hit_rate']*100:.1f}%\n"
                    f"  Количество: {with_ob['count']}"
                )
                lines.append("")
            
            if 'without_demand_ob' in ob_stats:
                without_ob = ob_stats['without_demand_ob']
                lines.append(
                    f"Без demand OB:\n"
                    f"  Средняя доходность: <b>{without_ob['avg_return']:.2f}%</b>\n"
                    f"  Hit rate: {without_ob['hit_rate']*100:.1f}%\n"
                    f"  Количество: {without_ob['count']}"
                )
                lines.append("")
            
            if 'comparison' in ob_stats:
                comp = ob_stats['comparison']
                lines.append(
                    f"Разница: доходность <b>{comp['return_diff']:+.2f}%</b>, "
                    f"hit rate {comp['hit_rate_diff']*100:+.1f}%"
                )
                lines.append("")
            
            if 'by_ob_distance' in ob_stats:
                lines.append("📏 <b>По расстоянию до OB:</b>")
                for distance, stats in ob_stats['by_ob_distance'].items():
                    lines.append(
                        f"  {distance}: средняя доходность <b>{stats['avg_return']:.2f}%</b>, "
                        f"hit rate {stats['hit_rate']*100:.1f}%, количество {stats['count']}"
                    )
                lines.append("")
        
        # Анализ по premium/discount
        pd_stats = self.analyze_premium_discount_impact(symbol, timeframe, hours)
        if pd_stats:
            lines.append("💰 <b>Влияние Premium/Discount зон:</b>")
            lines.append("")
            
            if 'discount_zone' in pd_stats:
                discount = pd_stats['discount_zone']
                lines.append(
                    f"Discount зона:\n"
                    f"  Средняя доходность: <b>{discount['avg_return']:.2f}%</b>\n"
                    f"  Hit rate: {discount['hit_rate']*100:.1f}%\n"
                    f"  Количество: {discount['count']}"
                )
                lines.append("")
            
            if 'premium_zone' in pd_stats:
                premium = pd_stats['premium_zone']
                lines.append(
                    f"Premium зона:\n"
                    f"  Средняя доходность: <b>{premium['avg_return']:.2f}%</b>\n"
                    f"  Hit rate: {premium['hit_rate']*100:.1f}%\n"
                    f"  Количество: {premium['count']}"
                )
                lines.append("")
            
            if 'discount_vs_premium' in pd_stats:
                comp = pd_stats['discount_vs_premium']
                lines.append(
                    f"Разница (discount - premium): доходность <b>{comp['return_diff']:+.2f}%</b>, "
                    f"hit rate {comp['hit_rate_diff']*100:+.1f}%"
                )
                lines.append("")
            
            if 'by_position_in_range' in pd_stats:
                lines.append("📊 <b>По позиции внутри диапазона:</b>")
                for zone, stats in pd_stats['by_position_in_range'].items():
                    lines.append(
                        f"  {zone}: средняя доходность <b>{stats['avg_return']:.2f}%</b>, "
                        f"hit rate {stats['hit_rate']*100:.1f}%, количество {stats['count']}"
                    )
                lines.append("")
        
        if not levels_stats and not ob_stats and not pd_stats:
            lines.append("❌ Недостаточно данных для анализа.")
            lines.append("Нужно больше сохраненных диагностик с метриками уровней и SMC.")
        
        return "\n".join(lines)

