import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import customtkinter as ctk
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import asyncio
import threading
import concurrent.futures
from datetime import datetime, timedelta
import warnings
import traceback
from typing import Dict, List, Optional, Tuple, Any
import itertools
from dataclasses import dataclass
import json

from extra_v4 import InstitutionalBacktestEngine,STRATEGY_DATABASE
# no gooooooooooooodddddddddddddeeeeeeeeee results for now should be retested

warnings.filterwarnings('ignore')

# Set appearance
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


# Import the existing classes from your previous code
# (Assuming all the previous classes are available in the same environment)

class InstitutionalStrategyOptimizer:
    """Professional strategy combination optimizer for institutional strategies"""

    def __init__(self, initial_capital: float = 100000):
        self.initial_capital = initial_capital
        self.backtest_engine = InstitutionalBacktestEngine(initial_capital)
        self.optimization_results = []
        self.best_combination = None

    async def optimize_all_combinations(self, symbol: str, n_bars: int,
                                        risk_reward_ratio: float, risk_per_trade: float,
                                        max_workers: int = 5) -> Dict[str, Any]:
        """Test all combinations of strategies, stop loss, take profit, filters, and timeframes"""

        # Define all possible combinations
        strategies = list(STRATEGY_DATABASE.keys())
        stop_loss_techs = list(self.backtest_engine.stop_loss_methods.keys())
        take_profit_techs = list(self.backtest_engine.take_profit_methods.keys())
        filters_combinations = self.get_filter_combinations()
        timeframes = ['15mn', '1h', '4h', '1d']  # Most relevant timeframes

        # Calculate total combinations
        total_combinations = (
                len(strategies) *
                len(stop_loss_techs) *
                len(take_profit_techs) *
                len(filters_combinations) *
                len(timeframes)
        )

        print(f"🔍 Testing {len(strategies)} strategies x {len(stop_loss_techs)} stop losses x "
              f"{len(take_profit_techs)} take profits x {len(filters_combinations)} filters x "
              f"{len(timeframes)} timeframes = {total_combinations} total combinations")

        tested_combinations = 0
        self.optimization_results = []

        # Create progress tracking
        progress_data = {
            'total': total_combinations,
            'completed': 0,
            'best_sharpe': -float('inf'),
            'best_combination': None
        }

        # Test combinations in batches to avoid memory issues
        batch_size = 50
        all_combinations = []

        # Generate all combinations
        for strategy in strategies:
            for stop_loss in stop_loss_techs:
                for take_profit in take_profit_techs:
                    for filters in filters_combinations:
                        for timeframe in timeframes:
                            all_combinations.append({
                                'strategy': strategy,
                                'stop_loss': stop_loss,
                                'take_profit': take_profit,
                                'filters': filters,
                                'timeframe': timeframe
                            })

        print(f"📦 Processing {len(all_combinations)} combinations in batches of {batch_size}")

        # Process in batches
        for i in range(0, len(all_combinations), batch_size):
            batch = all_combinations[i:i + batch_size]
            batch_results = await self._process_batch(batch, symbol, n_bars, risk_reward_ratio, risk_per_trade,
                                                      max_workers)

            for result in batch_results:
                if result and 'metrics' in result:
                    metrics = result['metrics']

                    # Only consider combinations with trades
                    if metrics['total_trades'] > 0:
                        combination_score = self.calculate_combination_score(metrics, result['combination_info'])

                        result_data = {
                            **result['combination_info'],
                            'metrics': metrics,
                            'score': combination_score,
                            'total_trades': metrics['total_trades'],
                            'sharpe_ratio': metrics['sharpe_ratio'],
                            'win_rate': metrics['win_rate'],
                            'total_pnl': metrics['total_pnl'],
                            'max_drawdown': metrics['max_drawdown'],
                            'annual_return': metrics['annual_return']
                        }

                        self.optimization_results.append(result_data)

                        # Update best combination
                        if metrics['sharpe_ratio'] > progress_data['best_sharpe'] and metrics['total_trades'] >= 5:
                            progress_data['best_sharpe'] = metrics['sharpe_ratio']
                            progress_data['best_combination'] = result_data
                            self.best_combination = result_data

                tested_combinations += 1
                progress_data['completed'] = tested_combinations

            print(f"📊 Batch {i // batch_size + 1}/{(len(all_combinations) - 1) // batch_size + 1} completed: "
                  f"{tested_combinations}/{total_combinations} ({tested_combinations / total_combinations * 100:.1f}%) | "
                  f"Best Sharpe: {progress_data['best_sharpe']:.3f}")

        # Sort results by score
        self.optimization_results.sort(key=lambda x: x['score'], reverse=True)

        print(f"✅ Optimization completed! Tested {tested_combinations} combinations.")
        if self.best_combination:
            print(f"🏆 Best combination: {self.best_combination['strategy']} "
                  f"on {self.best_combination['timeframe']} with Sharpe: {self.best_combination['sharpe_ratio']:.3f}")

        return {
            'best_combination': self.best_combination,
            'top_combinations': self.optimization_results[:50],  # Top 50
            'total_tested': tested_combinations,
            'successful_combinations': len(self.optimization_results),
            'total_possible': total_combinations
        }

    async def _process_batch(self, batch: List[Dict], symbol: str, n_bars: int,
                             risk_reward_ratio: float, risk_per_trade: float, max_workers: int) -> List[Dict]:
        """Process a batch of combinations"""
        loop = asyncio.get_event_loop()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []

            for combination in batch:
                # Create parameters for this combination
                parameters = {
                    'risk_per_trade': risk_per_trade,
                    'stop_loss_multiplier': 2.0,
                    'risk_reward_ratio': risk_reward_ratio,
                    'filter_params': self.get_filter_parameters(combination['filters'])
                }

                # Submit task
                future = executor.submit(
                    self._test_single_combination,
                    symbol, combination['strategy'], combination['timeframe'], n_bars,
                    combination['stop_loss'], combination['take_profit'], combination['filters'], parameters
                )
                futures.append((future, combination))

            # Collect results
            batch_results = []
            for future, combination in futures:
                try:
                    result = future.result(timeout=300)  # 5 minute timeout per combination
                    batch_results.append({
                        'result': result,
                        'combination_info': combination
                    })
                except concurrent.futures.TimeoutError:
                    print(f"⏰ Timeout for combination: {combination}")
                    batch_results.append({
                        'result': None,
                        'combination_info': combination
                    })
                except Exception as e:
                    print(f"❌ Error for combination {combination}: {e}")
                    batch_results.append({
                        'result': None,
                        'combination_info': combination
                    })

        return batch_results

    def _test_single_combination(self, symbol: str, strategy: str, timeframe: str, n_bars: int,
                                 stop_loss: str, take_profit: str, filters: List[str],
                                 parameters: Dict[str, Any]):
        """Test a single combination synchronously"""
        try:
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Run backtest
            result = loop.run_until_complete(
                self.backtest_engine.run_comprehensive_backtest(
                    symbol, strategy, timeframe, n_bars, stop_loss, take_profit, filters, parameters
                )
            )

            loop.close()
            return result

        except Exception as e:
            print(f"Error in combination {strategy}-{timeframe}-{stop_loss}-{take_profit}: {e}")
            return None

    def get_filter_combinations(self) -> List[List[str]]:
        """Get all relevant filter combinations from 1 to max filters"""
        base_filters = ['Volume Filter', 'Volatility Filter', 'Trend Filter']

        # Generate all possible combinations from 1 filter to all filters
        all_combinations = []
        for r in range(1, len(base_filters) + 1):
            for combo in itertools.combinations(base_filters, r):
                all_combinations.append(list(combo))

        print(f"🎯 Generated {len(all_combinations)} filter combinations (1 to {len(base_filters)} filters)")
        return all_combinations

    def get_filter_parameters(self, filters: List[str]) -> Dict[str, Any]:
        """Get appropriate parameters for given filters"""
        filter_params = {}

        if 'Volume Filter' in filters:
            filter_params['Volume Filter'] = {'volume_period': 20, 'multiplier': 1.2}
        if 'Volatility Filter' in filters:
            filter_params['Volatility Filter'] = {'atr_period': 14, 'threshold': 0.02}
        if 'Trend Filter' in filters:
            filter_params['Trend Filter'] = {'ma_period': 50}

        return filter_params

    def calculate_combination_score(self, metrics: Dict[str, Any], combination_info: Dict[str, Any]) -> float:
        """Calculate a professional score for strategy combination"""
        score = 0.0

        # Sharpe ratio (40% weight)
        sharpe_weight = 0.4
        if metrics['sharpe_ratio'] > 0:
            score += metrics['sharpe_ratio'] * sharpe_weight
        else:
            score += metrics['sharpe_ratio'] * sharpe_weight * 0.5  # Penalize negative Sharpe less harshly

        # Win rate (20% weight)
        win_rate_weight = 0.2
        score += metrics['win_rate'] * win_rate_weight

        # Profit factor (15% weight)
        profit_factor_weight = 0.15
        if metrics['profit_factor'] > 0:
            score += min(metrics['profit_factor'] / 5.0, 1.0) * profit_factor_weight

        # Drawdown control (15% weight)
        drawdown_weight = 0.15
        if metrics['max_drawdown'] > 0:
            drawdown_score = 1.0 - min(metrics['max_drawdown'] / 0.5, 1.0)  # Cap at 50% drawdown
            score += drawdown_score * drawdown_weight

        # Trade frequency (10% weight) - prefer strategies with reasonable trade count
        trade_count_weight = 0.1
        if metrics['total_trades'] > 0:
            trade_count_score = min(metrics['total_trades'] / 30.0, 1.0)  # Normalize to 30 trades
            score += trade_count_score * trade_count_weight

        # Strategy-specific bonuses
        strategy_bonus = self.get_strategy_bonus(combination_info['strategy'], combination_info['timeframe'])
        score += strategy_bonus

        return max(score, 0)  # Ensure non-negative score

    def get_strategy_bonus(self, strategy: str, timeframe: str) -> float:
        """Add bonus points for well-matched strategy/timeframe combinations"""
        bonus = 0.0

        # Mean reversion strategies work better on shorter timeframes
        if any(name in strategy for name in ['Mean Reversion', 'RSI', 'Bollinger']):
            if timeframe in ['15mn', '1h', '4h']:
                bonus += 0.1

        # Trend following strategies work better on longer timeframes
        elif any(name in strategy for name in ['Trend', 'Moving Average', 'MACD', 'Channel']):
            if timeframe in ['4h', '1d']:
                bonus += 0.1

        # Breakout strategies work on various timeframes but prefer medium
        elif 'Breakout' in strategy:
            if timeframe in ['1h', '4h']:
                bonus += 0.05

        return bonus

    def get_top_combinations_by_metric(self, metric: str, top_n: int = 10) -> List[Dict]:
        """Get top combinations by specific metric"""
        if not self.optimization_results:
            return []

        return sorted(self.optimization_results, key=lambda x: x['metrics'].get(metric, 0), reverse=True)[:top_n]

    def generate_optimization_report(self) -> Dict[str, Any]:
        """Generate comprehensive optimization report"""
        if not self.optimization_results:
            return {}

        # Basic statistics
        total_combinations = len(self.optimization_results)
        sharpe_values = [r['sharpe_ratio'] for r in self.optimization_results]
        win_rates = [r['win_rate'] for r in self.optimization_results]
        pnls = [r['total_pnl'] for r in self.optimization_results]

        report = {
            'summary': {
                'total_combinations_tested': total_combinations,
                'best_sharpe': max(sharpe_values) if sharpe_values else 0,
                'best_win_rate': max(win_rates) if win_rates else 0,
                'best_pnl': max(pnls) if pnls else 0,
                'avg_sharpe': np.mean(sharpe_values) if sharpe_values else 0,
                'avg_win_rate': np.mean(win_rates) if win_rates else 0,
            },
            'best_overall': self.best_combination,
            'top_by_sharpe': self.get_top_combinations_by_metric('sharpe_ratio', 5),
            'top_by_win_rate': self.get_top_combinations_by_metric('win_rate', 5),
            'top_by_pnl': self.get_top_combinations_by_metric('total_pnl', 5),
            'strategy_performance': self.analyze_strategy_performance(),
            'timeframe_performance': self.analyze_timeframe_performance(),
            'stop_loss_performance': self.analyze_stop_loss_performance(),
            'take_profit_performance': self.analyze_take_profit_performance(),
            'filter_performance': self.analyze_filter_performance()
        }

        return report

    def analyze_strategy_performance(self) -> Dict[str, Any]:
        """Analyze performance by strategy"""
        strategy_stats = {}

        for result in self.optimization_results:
            strategy = result['strategy']
            if strategy not in strategy_stats:
                strategy_stats[strategy] = {
                    'count': 0,
                    'sharpe_values': [],
                    'win_rates': [],
                    'pnl_values': [],
                    'best_combination': None
                }

            stats = strategy_stats[strategy]
            stats['count'] += 1
            stats['sharpe_values'].append(result['sharpe_ratio'])
            stats['win_rates'].append(result['win_rate'])
            stats['pnl_values'].append(result['total_pnl'])

            # Track best combination for this strategy
            if not stats['best_combination'] or result['sharpe_ratio'] > stats['best_combination']['sharpe_ratio']:
                stats['best_combination'] = result

        # Calculate averages
        for strategy, stats in strategy_stats.items():
            stats['avg_sharpe'] = np.mean(stats['sharpe_values'])
            stats['avg_win_rate'] = np.mean(stats['win_rates'])
            stats['avg_pnl'] = np.mean(stats['pnl_values'])
            stats['success_rate'] = stats['count'] / len(self.optimization_results)

        return strategy_stats

    def analyze_timeframe_performance(self) -> Dict[str, Any]:
        """Analyze performance by timeframe"""
        timeframe_stats = {}

        for result in self.optimization_results:
            tf = result['timeframe']
            if tf not in timeframe_stats:
                timeframe_stats[tf] = {
                    'count': 0,
                    'sharpe_values': [],
                    'win_rates': [],
                    'pnl_values': []
                }

            stats = timeframe_stats[tf]
            stats['count'] += 1
            stats['sharpe_values'].append(result['sharpe_ratio'])
            stats['win_rates'].append(result['win_rate'])
            stats['pnl_values'].append(result['total_pnl'])

        # Calculate averages
        for tf, stats in timeframe_stats.items():
            stats['avg_sharpe'] = np.mean(stats['sharpe_values'])
            stats['avg_win_rate'] = np.mean(stats['win_rates'])
            stats['avg_pnl'] = np.mean(stats['pnl_values'])

        return timeframe_stats

    def analyze_stop_loss_performance(self) -> Dict[str, Any]:
        """Analyze performance by stop loss technique"""
        sl_stats = {}

        for result in self.optimization_results:
            sl = result['stop_loss']
            if sl not in sl_stats:
                sl_stats[sl] = {
                    'count': 0,
                    'sharpe_values': [],
                    'win_rates': [],
                    'pnl_values': []
                }

            stats = sl_stats[sl]
            stats['count'] += 1
            stats['sharpe_values'].append(result['sharpe_ratio'])
            stats['win_rates'].append(result['win_rate'])
            stats['pnl_values'].append(result['total_pnl'])

        # Calculate averages
        for sl, stats in sl_stats.items():
            stats['avg_sharpe'] = np.mean(stats['sharpe_values'])
            stats['avg_win_rate'] = np.mean(stats['win_rates'])
            stats['avg_pnl'] = np.mean(stats['pnl_values'])

        return sl_stats

    def analyze_take_profit_performance(self) -> Dict[str, Any]:
        """Analyze performance by take profit technique"""
        tp_stats = {}

        for result in self.optimization_results:
            tp = result['take_profit']
            if tp not in tp_stats:
                tp_stats[tp] = {
                    'count': 0,
                    'sharpe_values': [],
                    'win_rates': [],
                    'pnl_values': []
                }

            stats = tp_stats[tp]
            stats['count'] += 1
            stats['sharpe_values'].append(result['sharpe_ratio'])
            stats['win_rates'].append(result['win_rate'])
            stats['pnl_values'].append(result['total_pnl'])

        # Calculate averages
        for tp, stats in tp_stats.items():
            stats['avg_sharpe'] = np.mean(stats['sharpe_values'])
            stats['avg_win_rate'] = np.mean(stats['win_rates'])
            stats['avg_pnl'] = np.mean(stats['pnl_values'])

        return tp_stats

    def analyze_filter_performance(self) -> Dict[str, Any]:
        """Analyze performance by filter combinations"""
        filter_stats = {}

        for result in self.optimization_results:
            filters_key = '+'.join(sorted(result['filters']))
            if filters_key not in filter_stats:
                filter_stats[filters_key] = {
                    'count': 0,
                    'sharpe_values': [],
                    'win_rates': [],
                    'pnl_values': []
                }

            stats = filter_stats[filters_key]
            stats['count'] += 1
            stats['sharpe_values'].append(result['sharpe_ratio'])
            stats['win_rates'].append(result['win_rate'])
            stats['pnl_values'].append(result['total_pnl'])

        # Calculate averages
        for filters, stats in filter_stats.items():
            stats['avg_sharpe'] = np.mean(stats['sharpe_values'])
            stats['avg_win_rate'] = np.mean(stats['win_rates'])
            stats['avg_pnl'] = np.mean(stats['pnl_values'])

        return filter_stats


class StrategyOptimizerApp(ctk.CTk):
    """GUI for testing all institutional strategy combinations"""

    def __init__(self):
        super().__init__()

        self.title("🏛️ INSTITUTIONAL STRATEGY OPTIMIZER")
        self.geometry("1400x900")
        self.minsize(1200, 800)

        self.optimizer = InstitutionalStrategyOptimizer()
        self.optimization_running = False
        self.current_results = None

        self.init_ui()

    def init_ui(self):
        """Initialize user interface"""
        main_container = ctk.CTkFrame(self)
        main_container.pack(fill="both", expand=True, padx=10, pady=10)

        # Header
        header_frame = ctk.CTkFrame(main_container, fg_color="#2b2b2b")
        header_frame.pack(fill="x", pady=10)

        ctk.CTkLabel(header_frame,
                     text="🏛️ INSTITUTIONAL STRATEGY COMBINATION OPTIMIZER",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color="white").pack(pady=15)

        ctk.CTkLabel(header_frame,
                     text="Test All Combinations: Strategies × Stop Loss × Take Profit × Filters × Timeframes",
                     font=ctk.CTkFont(size=14),
                     text_color="lightblue").pack(pady=5)

        # Configuration frame
        config_frame = ctk.CTkFrame(main_container)
        config_frame.pack(fill="x", pady=10, padx=10)

        # Input parameters
        input_frame = ctk.CTkFrame(config_frame)
        input_frame.pack(fill="x", pady=5, padx=10)

        # Symbol
        ctk.CTkLabel(input_frame, text="Symbol:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=5, pady=5)
        self.symbol_entry = ctk.CTkEntry(input_frame, width=120, placeholder_text="EURUSD")
        self.symbol_entry.grid(row=0, column=1, padx=5, pady=5)
        self.symbol_entry.insert(0, "EURUSD")

        # Number of Bars
        ctk.CTkLabel(input_frame, text="Number of Bars:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=2, padx=5,
                                                                                                pady=5)
        self.n_bars_entry = ctk.CTkEntry(input_frame, width=100, placeholder_text="1000")
        self.n_bars_entry.grid(row=0, column=3, padx=5, pady=5)
        self.n_bars_entry.insert(0, "1000")

        # Risk/Reward Ratio
        ctk.CTkLabel(input_frame, text="Risk/Reward Ratio:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=4,
                                                                                                   padx=5, pady=5)
        self.risk_reward_ratio = ctk.CTkEntry(input_frame, width=80)
        self.risk_reward_ratio.grid(row=0, column=5, padx=5, pady=5)
        self.risk_reward_ratio.insert(0, "2.0")

        # Risk per Trade
        ctk.CTkLabel(input_frame, text="Risk per Trade (%):", font=ctk.CTkFont(weight="bold")).grid(row=1, column=0,
                                                                                                    padx=5, pady=5)
        self.risk_per_trade = ctk.CTkEntry(input_frame, width=80)
        self.risk_per_trade.grid(row=1, column=1, padx=5, pady=5)
        self.risk_per_trade.insert(0, "2.0")

        # Max Workers
        ctk.CTkLabel(input_frame, text="Max Parallel Tests:", font=ctk.CTkFont(weight="bold")).grid(row=1, column=2,
                                                                                                    padx=5, pady=5)
        self.max_workers = ctk.CTkEntry(input_frame, width=80)
        self.max_workers.grid(row=1, column=3, padx=5, pady=5)
        self.max_workers.insert(0, "3")  # Reduced for stability

        # Calculate combinations button
        ctk.CTkButton(input_frame,
                      text="🧮 CALCULATE COMBINATIONS",
                      command=self.calculate_combinations,
                      width=180).grid(row=1, column=4, columnspan=2, padx=5, pady=5)

        # Combinations info
        self.combinations_label = ctk.CTkLabel(input_frame, text="Combinations: Not calculated",
                                               font=ctk.CTkFont(weight="bold"))
        self.combinations_label.grid(row=2, column=0, columnspan=6, pady=10)

        # Control buttons
        button_frame = ctk.CTkFrame(main_container)
        button_frame.pack(fill="x", pady=10, padx=10)

        self.optimize_button = ctk.CTkButton(button_frame,
                                             text="🚀 START COMPREHENSIVE OPTIMIZATION",
                                             command=self.start_optimization,
                                             fg_color="#2E8B57",
                                             height=50,
                                             font=ctk.CTkFont(weight="bold", size=14))
        self.optimize_button.pack(side="left", padx=5)

        ctk.CTkButton(button_frame,
                      text="📊 GENERATE OPTIMIZATION REPORT",
                      command=self.generate_report,
                      height=50,
                      font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)

        ctk.CTkButton(button_frame,
                      text="💾 EXPORT RESULTS",
                      command=self.export_results,
                      height=50).pack(side="left", padx=5)

        ctk.CTkButton(button_frame,
                      text="🧹 CLEAR RESULTS",
                      command=self.clear_results,
                      height=50).pack(side="left", padx=5)

        # Progress frame
        self.progress_frame = ctk.CTkFrame(main_container)
        self.progress_frame.pack(fill="x", pady=10, padx=10)

        self.progress_label = ctk.CTkLabel(self.progress_frame, text="Ready to start optimization...",
                                           font=ctk.CTkFont(weight="bold"))
        self.progress_label.pack(pady=5)

        self.progress_bar = ctk.CTkProgressBar(self.progress_frame)
        self.progress_bar.pack(fill="x", padx=10, pady=5)
        self.progress_bar.set(0)

        # Results display
        results_frame = ctk.CTkFrame(main_container)
        results_frame.pack(fill="both", expand=True, pady=10, padx=10)

        # Create notebook for results
        self.results_notebook = ctk.CTkTabview(results_frame)
        self.results_notebook.pack(fill="both", expand=True)

        # Add tabs
        self.results_notebook.add("Optimization Results")
        self.results_notebook.add("Best Combinations")
        self.results_notebook.add("Performance Analysis")
        self.results_notebook.add("Detailed Report")

        # Optimization results tab
        results_tab = self.results_notebook.tab("Optimization Results")
        self.results_text = scrolledtext.ScrolledText(results_tab,
                                                      height=20,
                                                      bg="#1a1a1a",
                                                      fg="white",
                                                      font=("Consolas", 10))
        self.results_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.results_text.config(state="disabled")

        # Best combinations tab
        best_tab = self.results_notebook.tab("Best Combinations")
        self.best_text = scrolledtext.ScrolledText(best_tab,
                                                   height=20,
                                                   bg="#1a1a1a",
                                                   fg="white",
                                                   font=("Consolas", 10))
        self.best_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.best_text.config(state="disabled")

        # Performance analysis tab
        analysis_tab = self.results_notebook.tab("Performance Analysis")
        self.analysis_text = scrolledtext.ScrolledText(analysis_tab,
                                                       height=20,
                                                       bg="#1a1a1a",
                                                       fg="white",
                                                       font=("Consolas", 10))
        self.analysis_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.analysis_text.config(state="disabled")

        # Detailed report tab
        report_tab = self.results_notebook.tab("Detailed Report")
        self.report_text = scrolledtext.ScrolledText(report_tab,
                                                     height=20,
                                                     bg="#1a1a1a",
                                                     fg="white",
                                                     font=("Consolas", 10))
        self.report_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.report_text.config(state="disabled")

        # Status bar
        self.setup_status_bar(main_container)

    def setup_status_bar(self, parent):
        """Setup status bar"""
        status_frame = ctk.CTkFrame(parent, height=30)
        status_frame.pack(fill="x", side="bottom")
        status_frame.pack_propagate(False)

        self.status_label = ctk.CTkLabel(status_frame, text="Ready")
        self.status_label.pack(side="left", padx=10)

    async def debug_data_loading(symbol, timeframe, n_bars):
        try:
            df = await self.data_feed.get_data_by_bars(symbol, timeframe, n_bars)
            print(f"📊 Data loaded: {len(df)} bars")
            print(f"Columns: {df.columns.tolist()}")
            print(f"Date range: {df.index[0]} to {df.index[-1]}")
            print(f"Sample data:\n{df.head()}")
            return df
        except Exception as e:
            print(f"❌ Data loading failed: {e}")
            return None

    def calculate_combinations(self):
        """Calculate and display total number of combinations"""
        try:
            strategies = len(STRATEGY_DATABASE)
            stop_loss_techs = len(self.optimizer.backtest_engine.stop_loss_methods)
            take_profit_techs = len(self.optimizer.backtest_engine.take_profit_methods)
            filter_combinations = len(self.optimizer.get_filter_combinations())
            timeframes = 4  # ['15mn', '1h', '4h', '1d']

            total_combinations = strategies * stop_loss_techs * take_profit_techs * filter_combinations * timeframes

            self.combinations_label.configure(
                text=f"Total Combinations: {total_combinations:,} "
                     f"({strategies} strats × {stop_loss_techs} SL × {take_profit_techs} TP × "
                     f"{filter_combinations} filters × {timeframes} TFs)"
            )

            # Estimate time
            estimated_time_minutes = total_combinations * 0.5 / 60  # Assuming 30 seconds per combination
            self.status_label.configure(
                text=f"Estimated time: ~{estimated_time_minutes:.1f} minutes with current settings"
            )

        except Exception as e:
            messagebox.showerror("Error", f"Failed to calculate combinations: {str(e)}")

    def start_optimization(self):
        """Start comprehensive optimization"""
        if self.optimization_running:
            return

        try:
            symbol = self.symbol_entry.get().strip().upper()
            n_bars = int(self.n_bars_entry.get())
            risk_reward_ratio = float(self.risk_reward_ratio.get())
            risk_per_trade = float(self.risk_per_trade.get()) / 100
            max_workers = int(self.max_workers.get())

            if max_workers < 1 or max_workers > 5:
                messagebox.showwarning("Warning", "Max workers should be between 1 and 5 for stability")
                return

            if n_bars > 5000:
                messagebox.showwarning("Warning", "Large number of bars may cause performance issues")

            self.optimization_running = True
            self.optimize_button.configure(state="disabled", text="🔄 OPTIMIZATION RUNNING...")
            self.progress_bar.set(0)
            self.progress_label.configure(text="Starting comprehensive optimization...")
            self.status_label.configure(text="Optimization in progress...")

            # Run optimization in thread
            threading.Thread(target=self._run_optimization,
                             args=(symbol, n_bars, risk_reward_ratio, risk_per_trade, max_workers),
                             daemon=True).start()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to start optimization: {str(e)}")
            self.optimization_running = False
            self.optimize_button.configure(state="normal", text="🚀 START COMPREHENSIVE OPTIMIZATION")

    def _run_optimization(self, symbol: str, n_bars: int, risk_reward_ratio: float,
                          risk_per_trade: float, max_workers: int):
        """Run optimization in background thread"""
        try:
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Run optimization
            results = loop.run_until_complete(
                self.optimizer.optimize_all_combinations(
                    symbol, n_bars, risk_reward_ratio, risk_per_trade, max_workers
                )
            )

            loop.close()

            # Update UI in main thread
            self.after(0, lambda: self._display_optimization_results(results))

        except Exception as error:
            # Fixed the lambda scope issue
            error_msg = str(error)
            self.after(0, lambda: self._display_optimization_error(error_msg))

    def _display_optimization_results(self, results: Dict[str, Any]):
        """Display optimization results"""
        self.optimization_running = False
        self.optimize_button.configure(state="normal", text="🚀 START COMPREHENSIVE OPTIMIZATION")
        self.progress_bar.set(1.0)
        self.progress_label.configure(text="Optimization completed!")
        self.status_label.configure(text="Optimization completed")

        self.current_results = results

        # Display basic results
        self._display_basic_results(results)

        # Display best combinations
        self._display_best_combinations(results)

        # Display performance analysis
        self._display_performance_analysis()

        # Display detailed report
        self._display_detailed_report()

    def _display_optimization_error(self, error_message: str):
        """Display optimization error - FIXED VERSION"""
        self.optimization_running = False
        self.optimize_button.configure(state="normal", text="🚀 START COMPREHENSIVE OPTIMIZATION")
        self.progress_label.configure(text="Optimization failed!")
        self.status_label.configure(text="Optimization failed")

        self.results_text.config(state="normal")
        self.results_text.delete(1.0, tk.END)
        self.results_text.insert(1.0, f"❌ OPTIMIZATION ERROR: {error_message}")
        self.results_text.config(state="disabled")

    def _display_basic_results(self, results: Dict[str, Any]):
        """Display basic optimization results"""
        basic_text = f"🏆 COMPREHENSIVE OPTIMIZATION RESULTS\n"
        basic_text += "=" * 70 + "\n\n"

        basic_text += f"Symbol: {self.symbol_entry.get()}\n"
        basic_text += f"Bars Tested: {self.n_bars_entry.get()}\n"
        basic_text += f"Risk/Reward: {self.risk_reward_ratio.get()}\n"
        basic_text += f"Risk per Trade: {self.risk_per_trade.get()}%\n\n"

        basic_text += f"Total Combinations Tested: {results['total_tested']}\n"
        basic_text += f"Successful Combinations: {results['successful_combinations']}\n"
        basic_text += f"Total Possible Combinations: {results['total_possible']}\n\n"

        best = results['best_combination']
        if best:
            basic_text += f"🏆 BEST OVERALL COMBINATION:\n"
            basic_text += f"   Strategy: {best['strategy']}\n"
            basic_text += f"   Timeframe: {best['timeframe']}\n"
            basic_text += f"   Stop Loss: {best['stop_loss']}\n"
            basic_text += f"   Take Profit: {best['take_profit']}\n"
            basic_text += f"   Filters: {', '.join(best['filters'])}\n"
            basic_text += f"   Sharpe Ratio: {best['sharpe_ratio']:.3f}\n"
            basic_text += f"   Win Rate: {best['win_rate']:.1%}\n"
            basic_text += f"   Total PnL: ${best['total_pnl']:.2f}\n"
            basic_text += f"   Max Drawdown: {best['max_drawdown']:.1%}\n"
            basic_text += f"   Annual Return: {best['annual_return']:.1%}\n"
            basic_text += f"   Total Trades: {best['total_trades']}\n"
        else:
            basic_text += "No successful combinations found.\n"

        self.results_text.config(state="normal")
        self.results_text.delete(1.0, tk.END)
        self.results_text.insert(1.0, basic_text)
        self.results_text.config(state="disabled")

    def _display_best_combinations(self, results: Dict[str, Any]):
        """Display best combinations"""
        best_text = "🏅 TOP 20 STRATEGY COMBINATIONS\n"
        best_text += "=" * 70 + "\n\n"

        top_combinations = results.get('top_combinations', [])[:20]

        if not top_combinations:
            best_text += "No successful combinations found.\n"
        else:
            for i, combo in enumerate(top_combinations, 1):
                best_text += f"{i:2d}. {combo['strategy'][:25]:25} | TF: {combo['timeframe']:4} | "
                best_text += f"SL: {combo['stop_loss'][:15]:15} | TP: {combo['take_profit'][:15]:15}\n"
                best_text += f"     Filters: {', '.join(combo['filters']):40} | "
                best_text += f"Sharpe: {combo['sharpe_ratio']:6.3f} | Win: {combo['win_rate']:5.1%} | "
                best_text += f"PnL: ${combo['total_pnl']:8.2f} | Trades: {combo['total_trades']:3}\n\n"

        self.best_text.config(state="normal")
        self.best_text.delete(1.0, tk.END)
        self.best_text.insert(1.0, best_text)
        self.best_text.config(state="disabled")

    def _display_performance_analysis(self):
        """Display performance analysis"""
        if not self.optimizer.optimization_results:
            self.analysis_text.config(state="normal")
            self.analysis_text.delete(1.0, tk.END)
            self.analysis_text.insert(1.0, "No optimization results available.")
            self.analysis_text.config(state="disabled")
            return

        analysis_text = "📊 PERFORMANCE ANALYSIS BY CATEGORY\n"
        analysis_text += "=" * 70 + "\n\n"

        # Strategy performance
        analysis_text += "STRATEGY PERFORMANCE:\n"
        strategy_stats = self.optimizer.analyze_strategy_performance()
        for strategy, stats in strategy_stats.items():
            analysis_text += f"  {strategy[:30]:30} | Avg Sharpe: {stats['avg_sharpe']:6.3f} | "
            analysis_text += f"Avg Win: {stats['avg_win_rate']:5.1%} | Count: {stats['count']:3}\n"

        analysis_text += "\nTIMEFRAME PERFORMANCE:\n"
        tf_stats = self.optimizer.analyze_timeframe_performance()
        for tf, stats in tf_stats.items():
            analysis_text += f"  {tf:4} | Avg Sharpe: {stats['avg_sharpe']:6.3f} | "
            analysis_text += f"Avg Win: {stats['avg_win_rate']:5.1%} | Count: {stats['count']:3}\n"

        analysis_text += "\nSTOP LOSS PERFORMANCE:\n"
        sl_stats = self.optimizer.analyze_stop_loss_performance()
        for sl, stats in sl_stats.items():
            analysis_text += f"  {sl[:20]:20} | Avg Sharpe: {stats['avg_sharpe']:6.3f} | "
            analysis_text += f"Avg Win: {stats['avg_win_rate']:5.1%} | Count: {stats['count']:3}\n"

        analysis_text += "\nTAKE PROFIT PERFORMANCE:\n"
        tp_stats = self.optimizer.analyze_take_profit_performance()
        for tp, stats in tp_stats.items():
            analysis_text += f"  {tp[:20]:20} | Avg Sharpe: {stats['avg_sharpe']:6.3f} | "
            analysis_text += f"Avg Win: {stats['avg_win_rate']:5.1%} | Count: {stats['count']:3}\n"

        self.analysis_text.config(state="normal")
        self.analysis_text.delete(1.0, tk.END)
        self.analysis_text.insert(1.0, analysis_text)
        self.analysis_text.config(state="disabled")

    def _display_detailed_report(self):
        """Display detailed optimization report"""
        report = self.optimizer.generate_optimization_report()

        report_text = "📈 DETAILED OPTIMIZATION REPORT\n"
        report_text += "=" * 70 + "\n\n"

        if not report:
            report_text += "No optimization results available. Run optimization first."
        else:
            # Summary
            summary = report['summary']
            report_text += "SUMMARY:\n"
            report_text += f"  Total Combinations Tested: {summary['total_combinations_tested']}\n"
            report_text += f"  Best Sharpe Ratio: {summary['best_sharpe']:.3f}\n"
            report_text += f"  Best Win Rate: {summary['best_win_rate']:.1%}\n"
            report_text += f"  Best PnL: ${summary['best_pnl']:.2f}\n"
            report_text += f"  Average Sharpe Ratio: {summary['avg_sharpe']:.3f}\n"
            report_text += f"  Average Win Rate: {summary['avg_win_rate']:.1%}\n\n"

            # Best overall
            best = report['best_overall']
            if best:
                report_text += "BEST OVERALL COMBINATION:\n"
                report_text += f"  Strategy: {best['strategy']}\n"
                report_text += f"  Timeframe: {best['timeframe']}\n"
                report_text += f"  Stop Loss: {best['stop_loss']}\n"
                report_text += f"  Take Profit: {best['take_profit']}\n"
                report_text += f"  Filters: {', '.join(best['filters'])}\n"
                report_text += f"  Score: {best['score']:.3f}\n\n"
            else:
                report_text += "No best combination found.\n\n"

            # Filter performance
            report_text += "FILTER COMBINATION PERFORMANCE:\n"
            filter_stats = report['filter_performance']
            for filters, stats in filter_stats.items():
                report_text += f"  {filters[:40]:40} | Avg Sharpe: {stats['avg_sharpe']:6.3f} | "
                report_text += f"Count: {stats['count']:3}\n"

        self.report_text.config(state="normal")
        self.report_text.delete(1.0, tk.END)
        self.report_text.insert(1.0, report_text)
        self.report_text.config(state="disabled")

    def generate_report(self):
        """Generate and display comprehensive report"""
        if not self.current_results:
            messagebox.showinfo("Info", "Please run optimization first")
            return

        self._display_detailed_report()
        self.results_notebook.set("Detailed Report")
        messagebox.showinfo("Report Generated", "Comprehensive optimization report has been generated!")

    def export_results(self):
        """Export optimization results to file"""
        if not self.current_results:
            messagebox.showinfo("Info", "No results to export")
            return

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"strategy_optimization_{timestamp}.json"

            # Prepare data for export
            export_data = {
                'optimization_parameters': {
                    'symbol': self.symbol_entry.get(),
                    'n_bars': self.n_bars_entry.get(),
                    'risk_reward_ratio': self.risk_reward_ratio.get(),
                    'risk_per_trade': self.risk_per_trade.get(),
                    'timestamp': timestamp
                },
                'results': self.current_results,
                'top_combinations': self.optimizer.optimization_results[:100]  # Top 100
            }

            with open(filename, 'w') as f:
                json.dump(export_data, f, indent=2, default=str)

            messagebox.showinfo("Export Successful", f"Results exported to {filename}")

        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export results: {str(e)}")

    def clear_results(self):
        """Clear all results"""
        self.results_text.config(state="normal")
        self.results_text.delete(1.0, tk.END)
        self.results_text.config(state="disabled")

        self.best_text.config(state="normal")
        self.best_text.delete(1.0, tk.END)
        self.best_text.config(state="disabled")

        self.analysis_text.config(state="normal")
        self.analysis_text.delete(1.0, tk.END)
        self.analysis_text.config(state="disabled")

        self.report_text.config(state="normal")
        self.report_text.delete(1.0, tk.END)
        self.report_text.config(state="disabled")

        self.progress_bar.set(0)
        self.progress_label.configure(text="Ready to start optimization...")
        self.status_label.configure(text="Ready")

        self.optimizer.optimization_results = []
        self.current_results = None


# =============================================================================
# APPLICATION LAUNCH
# =============================================================================

if __name__ == "__main__":
    print("🚀 LAUNCHING INSTITUTIONAL STRATEGY OPTIMIZER...")
    print("🔍 TESTING ALL STRATEGY COMBINATIONS...")
    print("📊 ANALYZING PERFORMANCE ACROSS MULTIPLE DIMENSIONS...")

    try:
        app = StrategyOptimizerApp()
        app.mainloop()
    except Exception as e:
        print(f"❌ Application failed to start: {e}")
        traceback.print_exc()