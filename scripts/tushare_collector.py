#!/usr/bin/env python3
"""Turtle Investment Framework - Tushare Data Collector (Phase 1A).

Collects 5 years of financial data from Tushare Pro API and outputs
a structured data_pack_market.md file.

Usage:
    python3 scripts/tushare_collector.py --code 600887.SH
    python3 scripts/tushare_collector.py --code 600887.SH --output output/data_pack.md
    python3 scripts/tushare_collector.py --code 600887.SH --dry-run
"""

import argparse
import functools
import sys
import time

import pandas as pd
import tushare as ts

from config import get_token, validate_stock_code
from format_utils import format_number, format_table, format_header


def rate_limit(func):
    """Decorator to enforce 0.5s delay between Tushare API calls."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        time.sleep(0.5)
        return func(*args, **kwargs)
    return wrapper


class TushareClient:
    """Client for Tushare Pro API with rate limiting and retry logic."""

    MAX_RETRIES = 5
    RETRY_DELAY = 2.0  # seconds between retries

    def __init__(self, token: str):
        ts.set_token(token)
        self.pro = ts.pro_api(timeout=30)
        self.token = token
        self._store = {}  # {key: pd.DataFrame} for derived metrics computation

    @rate_limit
    def _safe_call(self, api_name: str, **kwargs) -> pd.DataFrame:
        """Call a Tushare API endpoint with retry logic.

        Args:
            api_name: The API endpoint name (e.g., 'stock_basic').
            **kwargs: Parameters passed to the API call.

        Returns:
            DataFrame with results.

        Raises:
            RuntimeError: After MAX_RETRIES failures.
        """
        last_err = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                api_func = getattr(self.pro, api_name)
                df = api_func(**kwargs)
                return df
            except Exception as e:
                last_err = e
                if attempt < self.MAX_RETRIES:
                    is_conn_err = isinstance(e, (ConnectionError, OSError)) or \
                        "RemoteDisconnected" in type(e).__name__ or \
                        "ConnectionAborted" in str(e) or \
                        "RemoteDisconnected" in str(e)
                    if is_conn_err:
                        print(f"[retry {attempt}/{self.MAX_RETRIES}] {api_name}: connection error, re-creating API client...", file=sys.stderr)
                        self.pro = ts.pro_api(timeout=30)
                    else:
                        print(f"[retry {attempt}/{self.MAX_RETRIES}] {api_name}: {e}", file=sys.stderr)
                    time.sleep(self.RETRY_DELAY * attempt)
        raise RuntimeError(
            f"Tushare API '{api_name}' failed after {self.MAX_RETRIES} retries: {last_err}"
        )

    @staticmethod
    def _prepare_display_periods(df, max_annual=5):
        """Select up to max_annual annual reports + any newer interim reports.

        Returns (display_df, column_labels) where column_labels are like:
        ["2025Q3", "2025H1", "2025Q1", "2024", "2023", "2022", "2021", "2020"]
        """
        if df.empty:
            return df, []

        df = df.drop_duplicates(subset=["end_date"])

        # Split into annual (1231) and non-annual
        annual = df[df["end_date"].str.endswith("1231")].copy()
        non_annual = df[~df["end_date"].str.endswith("1231")].copy()

        # Sort annual descending, take top max_annual
        annual = annual.sort_values("end_date", ascending=False).head(max_annual)

        latest_annual_date = annual["end_date"].max() if not annual.empty else "00000000"

        # Keep only non-annual entries strictly newer than latest annual
        interim = non_annual[non_annual["end_date"] > latest_annual_date].copy()
        interim = interim.sort_values("end_date", ascending=False)

        # Build labels
        def _label(end_date):
            mmdd = end_date[4:]
            year = end_date[:4]
            if mmdd == "1231":
                return year
            elif mmdd == "0630":
                return f"{year}H1"
            elif mmdd == "0331":
                return f"{year}Q1"
            elif mmdd == "0930":
                return f"{year}Q3"
            else:
                return f"{year}_{mmdd}"

        # Combine: interim (desc) + annual (desc)
        display_df = pd.concat([interim, annual], ignore_index=True)
        if display_df.empty:
            return display_df, []

        labels = [_label(d) for d in display_df["end_date"]]
        return display_df, labels

    # --- Feature #14: Section 1 — Basic company info ---

    def get_basic_info(self, ts_code: str) -> str:
        """Section 1: Basic company info from stock_basic + daily_basic."""
        basic = self._safe_call("stock_basic", ts_code=ts_code,
                                fields="ts_code,name,industry,area,market,exchange,list_date,fullname")
        if basic.empty:
            return format_header(2, "1. 基本信息") + "\n\n数据缺失\n"

        row = basic.iloc[0]

        # Get latest daily_basic for valuation
        daily = self._safe_call("daily_basic", ts_code=ts_code,
                                fields="ts_code,trade_date,close,pe_ttm,pb,total_mv,circ_mv,total_share,float_share")
        val_rows = []
        if not daily.empty:
            self._store["basic_info"] = daily
            d = daily.iloc[0]
            val_rows = [
                ["当前价格", f"{d.get('close', '—')}"],
                ["PE (TTM)", f"{d.get('pe_ttm', '—')}"],
                ["PB", f"{d.get('pb', '—')}"],
                ["总市值 (万元)", format_number(d.get('total_mv', None), divider=1, decimals=2)],
                ["流通市值 (万元)", format_number(d.get('circ_mv', None), divider=1, decimals=2)],
            ]

        lines = [format_header(2, "1. 基本信息"), ""]
        info_table = format_table(
            ["项目", "内容"],
            [
                ["股票代码", str(row.get("ts_code", ""))],
                ["公司名称", str(row.get("name", ""))],
                ["全称", str(row.get("fullname", ""))],
                ["行业", str(row.get("industry", ""))],
                ["地区", str(row.get("area", ""))],
                ["交易所", str(row.get("exchange", ""))],
                ["上市日期", str(row.get("list_date", ""))],
            ] + val_rows,
            alignments=["l", "r"],
        )
        lines.append(info_table)
        return "\n".join(lines)

    # --- Feature #15: Section 2 — Market data ---

    def get_market_data(self, ts_code: str) -> str:
        """Section 2: Current price and 52-week range."""
        today = pd.Timestamp.now().strftime("%Y%m%d")
        year_ago = (pd.Timestamp.now() - pd.DateOffset(years=1)).strftime("%Y%m%d")

        df = self._safe_call("daily", ts_code=ts_code,
                             start_date=year_ago, end_date=today,
                             fields="ts_code,trade_date,open,high,low,close,vol,amount")
        lines = [format_header(2, "2. 市场行情"), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        latest_close = df.iloc[0]["close"]
        high_52w = df["high"].max()
        low_52w = df["low"].min()
        high_date = df.loc[df["high"].idxmax(), "trade_date"]
        low_date = df.loc[df["low"].idxmin(), "trade_date"]
        avg_vol = df["vol"].mean()

        table = format_table(
            ["指标", "数值"],
            [
                ["最新收盘价", f"{latest_close:.2f}"],
                ["52周最高", f"{high_52w:.2f} ({high_date})"],
                ["52周最低", f"{low_52w:.2f} ({low_date})"],
                ["52周涨跌幅", f"{(latest_close / low_52w - 1) * 100:.1f}% (自低点)"],
                ["日均成交量 (手)", f"{avg_vol:,.0f}"],
            ],
            alignments=["l", "r"],
        )
        lines.append(table)
        return "\n".join(lines)

    # --- Feature #16: Section 3 — Consolidated income statement ---

    def get_income(self, ts_code: str, report_type: str = "1") -> str:
        """Section 3: Five-year consolidated income statement."""
        df = self._safe_call("income", ts_code=ts_code,
                             report_type=report_type,
                             fields="ts_code,end_date,report_type,"
                                    "revenue,oper_cost,biz_tax_surch,"
                                    "sell_exp,admin_exp,rd_exp,finance_exp,"
                                    "assets_impair_loss,credit_impair_loss,"
                                    "fv_value_chg_gain,invest_income,asset_disp_income,"
                                    "operate_profit,non_oper_income,non_oper_exp,"
                                    "total_profit,income_tax,"
                                    "n_income,n_income_attr_p,minority_gain,"
                                    "basic_eps,diluted_eps,dt_eps")
        section_label = "3P. 母公司利润表" if report_type == "6" else "3. 合并利润表"
        lines = [format_header(2, section_label), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        df, years = self._prepare_display_periods(df)

        # Store for derived metrics
        store_key = "income_parent" if report_type == "6" else "income"
        self._store[store_key] = df
        self._store[store_key + "_years"] = years

        if not years:
            lines.append("无年报数据\n")
            return "\n".join(lines)

        fields = [
            ("营业收入", "revenue"),
            ("营业成本", "oper_cost"),
            ("税金及附加", "biz_tax_surch"),
            ("销售费用", "sell_exp"),
            ("管理费用", "admin_exp"),
            ("研发费用", "rd_exp"),
            ("财务费用", "finance_exp"),
            ("资产减值损失", "assets_impair_loss"),
            ("信用减值损失", "credit_impair_loss"),
            ("公允价值变动收益", "fv_value_chg_gain"),
            ("投资收益", "invest_income"),
            ("资产处置收益", "asset_disp_income"),
            ("营业利润", "operate_profit"),
            ("营业外收入", "non_oper_income"),
            ("营业外支出", "non_oper_exp"),
            ("利润总额", "total_profit"),
            ("所得税费用", "income_tax"),
            ("净利润", "n_income"),
            ("归母净利润", "n_income_attr_p"),
            ("少数股东损益", "minority_gain"),
            ("基本EPS", "basic_eps"),
            ("稀释EPS", "diluted_eps"),
        ]

        if report_type == "6":
            _exclude = {"minority_gain", "basic_eps", "diluted_eps", "credit_impair_loss"}
            fields = [(label, col) for label, col in fields if col not in _exclude]

        headers = ["项目 (百万元)"] + years
        rows = []
        for label, col in fields:
            row = [label]
            for _, r in df.iterrows():
                val = r.get(col)
                if col in ("basic_eps", "diluted_eps", "dt_eps"):
                    row.append(f"{val:.2f}" if val is not None and val == val else "—")
                else:
                    row.append(format_number(val))
            rows.append(row)

        table = format_table(headers, rows,
                             alignments=["l"] + ["r"] * len(years))
        lines.append(table)
        lines.append("")
        lines.append("*单位: 百万元 (原始数据 / 1,000,000), EPS为元/股*")
        return "\n".join(lines)

    # --- Feature #17: Section 3P — Parent company income ---

    def get_income_parent(self, ts_code: str) -> str:
        """Section 3P: Five-year parent-company income statement."""
        return self.get_income(ts_code, report_type="6")

    # --- Feature #18: Section 4 — Consolidated balance sheet ---

    def get_balance_sheet(self, ts_code: str, report_type: str = "1") -> str:
        """Section 4: Five-year consolidated balance sheet."""
        df = self._safe_call("balancesheet", ts_code=ts_code,
                             report_type=report_type,
                             fields="ts_code,end_date,report_type,"
                                    "money_cap,trad_asset,notes_receiv,"
                                    "accounts_receiv,oth_receiv,inventories,"
                                    "oth_cur_assets,total_cur_assets,"
                                    "lt_eqt_invest,fix_assets,cip,"
                                    "intang_assets,goodwill,total_assets,"
                                    "st_borr,notes_payable,acct_payable,"
                                    "contract_liab,adv_receipts,"
                                    "non_cur_liab_due_1y,oth_cur_liab,"
                                    "total_cur_liab,lt_borr,bond_payable,"
                                    "total_liab,defer_tax_assets,defer_tax_liab,"
                                    "total_hldr_eqy_exc_min_int,minority_int")
        section_label = "4P. 母公司资产负债表" if report_type == "6" else "4. 合并资产负债表"
        lines = [format_header(2, section_label), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        df, years = self._prepare_display_periods(df)

        # Store for derived metrics
        store_key = "balance_sheet_parent" if report_type == "6" else "balance_sheet"
        self._store[store_key] = df
        self._store[store_key + "_years"] = years

        if not years:
            lines.append("无年报数据\n")
            return "\n".join(lines)

        fields = [
            ("货币资金", "money_cap"),
            ("交易性金融资产", "trad_asset"),
            ("应收票据", "notes_receiv"),
            ("应收账款", "accounts_receiv"),
            ("其他应收款", "oth_receiv"),
            ("存货", "inventories"),
            ("其他流动资产", "oth_cur_assets"),
            ("流动资产合计", "total_cur_assets"),
            ("长期股权投资", "lt_eqt_invest"),
            ("固定资产", "fix_assets"),
            ("在建工程", "cip"),
            ("无形资产", "intang_assets"),
            ("商誉", "goodwill"),
            ("总资产", "total_assets"),
            ("短期借款", "st_borr"),
            ("应付票据", "notes_payable"),
            ("应付账款", "acct_payable"),
            ("合同负债", "contract_liab"),
            ("预收款项", "adv_receipts"),
            ("一年内到期非流动负债", "non_cur_liab_due_1y"),
            ("其他流动负债", "oth_cur_liab"),
            ("流动负债合计", "total_cur_liab"),
            ("长期借款", "lt_borr"),
            ("应付债券", "bond_payable"),
            ("总负债", "total_liab"),
            ("递延所得税资产", "defer_tax_assets"),
            ("递延所得税负债", "defer_tax_liab"),
            ("归母所有者权益", "total_hldr_eqy_exc_min_int"),
            ("少数股东权益", "minority_int"),
        ]

        # Feature #81: For parent company, use subset of fields
        if report_type == "6":
            fields = [
                ("货币资金", "money_cap"),
                ("长期股权投资", "lt_eqt_invest"),
                ("总资产", "total_assets"),
                ("短期借款", "st_borr"),
                ("长期借款", "lt_borr"),
                ("应付债券", "bond_payable"),
                ("一年内到期非流动负债", "non_cur_liab_due_1y"),
                ("总负债", "total_liab"),
                ("归母权益", "total_hldr_eqy_exc_min_int"),
            ]

        headers = ["项目 (百万元)"] + years
        rows = []
        for label, col in fields:
            row = [label]
            for _, r in df.iterrows():
                row.append(format_number(r.get(col)))
            rows.append(row)

        table = format_table(headers, rows,
                             alignments=["l"] + ["r"] * len(years))
        lines.append(table)
        lines.append("")
        lines.append("*单位: 百万元*")
        return "\n".join(lines)

    # --- Feature #19: Section 4P — Parent company balance sheet ---

    def get_balance_sheet_parent(self, ts_code: str) -> str:
        """Section 4P: Five-year parent-company balance sheet."""
        return self.get_balance_sheet(ts_code, report_type="6")

    # --- Feature #20: Section 5 — Cash flow statement ---

    def get_cashflow(self, ts_code: str) -> str:
        """Section 5: Five-year cash flow statement with FCF calculation."""
        df = self._safe_call("cashflow", ts_code=ts_code,
                             report_type="1",
                             fields="ts_code,end_date,report_type,"
                                    "n_cashflow_act,n_cashflow_inv_act,"
                                    "n_cash_flows_fnc_act,c_pay_acq_const_fiolta,"
                                    "depr_fa_coga_dpba,amort_intang_assets,"
                                    "lt_amort_deferred_exp,"
                                    "c_pay_dist_dpcp_int_exp,"
                                    "c_pay_to_staff,c_paid_for_taxes,"
                                    "n_recp_disp_fiolta,receiv_tax_refund,"
                                    "c_recp_return_invest")
        lines = [format_header(2, "5. 现金流量表"), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        df, years = self._prepare_display_periods(df)

        # Store for derived metrics
        self._store["cashflow"] = df
        self._store["cashflow_years"] = years

        if not years:
            lines.append("无年报数据\n")
            return "\n".join(lines)

        headers = ["项目 (百万元)"] + years
        rows = []

        simple_fields = [
            ("经营活动现金流 (OCF)", "n_cashflow_act"),
            ("投资活动现金流", "n_cashflow_inv_act"),
            ("筹资活动现金流", "n_cash_flows_fnc_act"),
            ("资本支出(购建固定资产等)", "c_pay_acq_const_fiolta"),
            ("支付给职工现金", "c_pay_to_staff"),
            ("支付的各项税费", "c_paid_for_taxes"),
            ("处置固定资产收回现金", "n_recp_disp_fiolta"),
            ("收到税费返还", "receiv_tax_refund"),
            ("取得投资收益收到现金", "c_recp_return_invest"),
            ("分配股利偿付利息", "c_pay_dist_dpcp_int_exp"),
        ]
        for label, col in simple_fields:
            row = [label]
            for _, r in df.iterrows():
                row.append(format_number(r.get(col)))
            rows.append(row)

        # D&A = 固定资产折旧 + 无形资产摊销 + 长期待摊费用摊销
        da_row = ["折旧与摊销 (D&A)"]
        for _, r in df.iterrows():
            depr = r.get("depr_fa_coga_dpba")
            amort_intang = r.get("amort_intang_assets")
            amort_deferred = r.get("lt_amort_deferred_exp")
            vals = [v for v in [depr, amort_intang, amort_deferred]
                    if v is not None and v == v]
            if vals:
                da_row.append(format_number(sum(float(v) for v in vals)))
            else:
                da_row.append("—")
        rows.append(da_row)

        # FCF = OCF - |Capex| (values are in raw yuan, format_number divides by 1e6)
        fcf_row = ["自由现金流 (FCF)"]
        for _, r in df.iterrows():
            ocf = r.get("n_cashflow_act")
            capex = r.get("c_pay_acq_const_fiolta")
            if ocf is not None and capex is not None:
                fcf = float(ocf) - abs(float(capex))
                fcf_row.append(format_number(fcf))
            else:
                fcf_row.append("—")
        rows.append(fcf_row)

        table = format_table(headers, rows,
                             alignments=["l"] + ["r"] * len(years))
        lines.append(table)
        lines.append("")
        lines.append("*单位: 百万元; FCF = OCF - |Capex|*")
        return "\n".join(lines)

    # --- Feature #21: Section 6 — Dividend history ---

    def get_dividends(self, ts_code: str) -> str:
        """Section 6: Dividend history."""
        df = self._safe_call("dividend", ts_code=ts_code,
                             fields="ts_code,end_date,ann_date,div_proc,"
                                    "stk_div,cash_div_tax,record_date,"
                                    "ex_date,base_share")
        lines = [format_header(2, "6. 分红历史"), ""]

        if df.empty:
            lines.append("暂无分红数据\n")
            return "\n".join(lines)

        # Filter for completed dividends
        df = df[df["div_proc"] == "实施"].copy()
        df = df.drop_duplicates(subset=["end_date"])
        df = df.sort_values("end_date", ascending=False).head(5)

        # Store for derived metrics
        self._store["dividends"] = df

        if df.empty:
            lines.append("暂无已实施分红\n")
            return "\n".join(lines)

        headers = ["年度", "每股现金分红(税前)", "每股送股", "登记日", "除权日", "总分红 (百万元)"]
        rows = []
        for _, r in df.iterrows():
            year = str(r.get("end_date", ""))[:4]
            cash_div = r.get("cash_div_tax", 0) or 0
            stk_div = r.get("stk_div", 0) or 0
            base_share = r.get("base_share", 0) or 0
            total_div = cash_div * base_share * 10000  # base_share is 万股, convert to shares
            rows.append([
                year,
                f"{cash_div:.4f}",
                f"{stk_div:.2f}" if stk_div else "—",
                str(r.get("record_date", "—")),
                str(r.get("ex_date", "—")),
                format_number(total_div),
            ])

        table = format_table(headers, rows,
                             alignments=["l", "r", "r", "l", "l", "r"])
        lines.append(table)
        return "\n".join(lines)

    # --- Feature #22: Section 11 + Appendix A — 10-year weekly prices ---

    def get_weekly_prices(self, ts_code: str) -> str:
        """Section 11 + Appendix A: 10-year weekly price history."""
        today = pd.Timestamp.now().strftime("%Y%m%d")
        ten_years_ago = (pd.Timestamp.now() - pd.DateOffset(years=10)).strftime("%Y%m%d")

        df = self._safe_call("weekly", ts_code=ts_code,
                             start_date=ten_years_ago, end_date=today,
                             fields="ts_code,trade_date,open,high,low,close,vol,amount")
        lines = [format_header(2, "11. 十年周线行情"), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        df = df.sort_values("trade_date", ascending=True)

        # Store for derived metrics
        self._store["weekly_prices"] = df

        # 10-year summary
        high_10y = df["high"].max()
        low_10y = df["low"].min()
        high_date = df.loc[df["high"].idxmax(), "trade_date"]
        low_date = df.loc[df["low"].idxmin(), "trade_date"]
        latest_close = df.iloc[-1]["close"]

        summary_table = format_table(
            ["指标", "数值"],
            [
                ["10年最高", f"{high_10y:.2f} ({high_date})"],
                ["10年最低", f"{low_10y:.2f} ({low_date})"],
                ["最新收盘", f"{latest_close:.2f}"],
                ["距最高回撤", f"{(1 - latest_close / high_10y) * 100:.1f}%"],
                ["距最低涨幅", f"{(latest_close / low_10y - 1) * 100:.1f}%"],
            ],
            alignments=["l", "r"],
        )
        lines.append(summary_table)
        lines.append("")

        # Annual summary
        df["year"] = df["trade_date"].str[:4]
        annual = df.groupby("year").agg(
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            avg_vol=("vol", "mean"),
        ).reset_index()
        annual = annual.sort_values("year", ascending=False)

        lines.append(format_header(3, "年度行情汇总"))
        lines.append("")
        annual_table = format_table(
            ["年度", "最高", "最低", "年末收盘", "周均成交量(手)"],
            [[
                r["year"],
                f"{r['high']:.2f}",
                f"{r['low']:.2f}",
                f"{r['close']:.2f}",
                f"{r['avg_vol']:,.0f}",
            ] for _, r in annual.iterrows()],
            alignments=["l", "r", "r", "r", "r"],
        )
        lines.append(annual_table)
        return "\n".join(lines)

    # --- Feature #23: Section 12 — Financial indicators ---

    def get_fina_indicators(self, ts_code: str) -> str:
        """Section 12: Key financial indicators from fina_indicator endpoint."""
        df = self._safe_call("fina_indicator", ts_code=ts_code,
                             fields="ts_code,end_date,roe,roe_waa,"
                                    "grossprofit_margin,netprofit_margin,"
                                    "rd_exp,current_ratio,quick_ratio,"
                                    "assets_turn,debt_to_assets,"
                                    "revenue_yoy,netprofit_yoy,"
                                    "ocfps,bps,profit_dedt")
        lines = [format_header(2, "12. 关键财务指标"), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        df, years = self._prepare_display_periods(df)

        # Store for derived metrics
        self._store["fina_indicators"] = df
        self._store["fina_indicators_years"] = years

        if not years:
            lines.append("无年报数据\n")
            return "\n".join(lines)

        pct_fields = [
            ("ROE (%)", "roe"),
            ("加权ROE (%)", "roe_waa"),
            ("毛利率 (%)", "grossprofit_margin"),
            ("净利率 (%)", "netprofit_margin"),
            ("资产负债率 (%)", "debt_to_assets"),
        ]
        ratio_fields = [
            ("流动比率", "current_ratio"),
            ("速动比率", "quick_ratio"),
            ("总资产周转率", "assets_turn"),
        ]
        growth_fields = [
            ("营收同比增长率 (%)", "revenue_yoy"),
            ("净利润同比增长率 (%)", "netprofit_yoy"),
        ]
        per_share_fields = [
            ("每股经营现金流", "ocfps"),
            ("每股净资产", "bps"),
        ]

        headers = ["指标"] + years
        rows = []
        for label, col in pct_fields:
            row = [label]
            for _, r in df.iterrows():
                val = r.get(col)
                row.append(f"{val:.2f}" if val is not None and val == val else "—")
            rows.append(row)
        for label, col in ratio_fields:
            row = [label]
            for _, r in df.iterrows():
                val = r.get(col)
                row.append(f"{val:.2f}" if val is not None and val == val else "—")
            rows.append(row)
        for label, col in growth_fields:
            row = [label]
            for _, r in df.iterrows():
                val = r.get(col)
                row.append(f"{val:.2f}" if val is not None and val == val else "—")
            rows.append(row)
        for label, col in per_share_fields:
            row = [label]
            for _, r in df.iterrows():
                val = r.get(col)
                row.append(f"{val:.2f}" if val is not None and val == val else "—")
            rows.append(row)
        # Quality: 扣非净利润 (in millions)
        profit_dedt_row = ["扣非净利润 (百万元)"]
        for _, r in df.iterrows():
            val = r.get("profit_dedt")
            profit_dedt_row.append(format_number(val))
        rows.append(profit_dedt_row)

        table = format_table(headers, rows,
                             alignments=["l"] + ["r"] * len(years))
        lines.append(table)
        return "\n".join(lines)

    # --- Feature #24: Section 9 — Business segments ---

    def get_segments(self, ts_code: str) -> str:
        """Section 9: Business segment data from fina_mainbz."""
        lines = [format_header(2, "9. 主营业务构成"), ""]
        try:
            df = self._safe_call("fina_mainbz", ts_code=ts_code, type="P",
                                 fields="ts_code,end_date,bz_item,bz_sales,bz_profit,bz_cost")
        except RuntimeError:
            lines.append("数据缺失 (接口可能无权限)\n")
            return "\n".join(lines)

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        # Get latest period
        if "end_date" in df.columns:
            latest_period = df["end_date"].max()
            df = df[df["end_date"] == latest_period]

        headers = ["业务名称", "营业收入 (百万元)", "营业利润 (百万元)", "毛利率 (%)"]
        rows = []
        for _, r in df.iterrows():
            name = r.get("bz_item", "—")
            rev = r.get("bz_sales", None)
            profit = r.get("bz_profit", None)
            margin = r.get("bz_cost", None)
            # Compute gross margin if both revenue and cost available
            gm = "—"
            if rev and margin:
                try:
                    gm = f"{(1 - float(margin)/float(rev)) * 100:.1f}"
                except (ValueError, ZeroDivisionError):
                    gm = "—"
            rows.append([
                str(name),
                format_number(rev),
                format_number(profit),
                gm,
            ])

        table = format_table(headers, rows,
                             alignments=["l", "r", "r", "r"])
        lines.append(table)
        return "\n".join(lines)

    # --- Feature #25: Section 7 (partial) — Top 10 holders + audit ---

    def get_holders(self, ts_code: str) -> str:
        """Section 7 (partial): Top 10 shareholders."""
        lines = [format_header(2, "7. 股东与治理 (部分)"), ""]

        try:
            df = self._safe_call("top10_holders", ts_code=ts_code)
        except RuntimeError:
            lines.append("股东数据缺失\n")
            return "\n".join(lines)

        if df.empty:
            lines.append("股东数据缺失\n")
            return "\n".join(lines)

        # Get latest period
        if "end_date" in df.columns:
            latest = df["end_date"].max()
            df = df[df["end_date"] == latest]

        lines.append(f"*截至 {latest}*\n" if "end_date" in df.columns else "")

        headers = ["序号", "股东名称", "持股数量 (万股)", "持股比例 (%)"]
        rows = []
        for i, (_, r) in enumerate(df.head(10).iterrows(), 1):
            rows.append([
                str(i),
                str(r.get("holder_name", "—")),
                format_number(r.get("hold_amount", None), divider=1e4, decimals=2),
                f"{r.get('hold_ratio', 0) or 0:.2f}",
            ])

        table = format_table(headers, rows,
                             alignments=["l", "l", "r", "r"])
        lines.append(table)
        return "\n".join(lines)

    def get_audit(self, ts_code: str) -> str:
        """Audit opinion info."""
        lines = [format_header(3, "审计意见"), ""]
        try:
            df = self._safe_call("fina_audit", ts_code=ts_code,
                                 fields="ts_code,end_date,audit_result,audit_agency,audit_fees")
        except RuntimeError:
            lines.append("审计数据缺失\n")
            return "\n".join(lines)

        if df.empty:
            lines.append("审计数据缺失\n")
            return "\n".join(lines)

        df = df.sort_values("end_date", ascending=False).head(3)
        headers = ["年度", "审计意见", "会计事务所", "审计费用 (万元)"]
        rows = []
        for _, r in df.iterrows():
            year = str(r.get("end_date", ""))[:4]
            opinion = str(r.get("audit_result", "—"))
            agency = str(r.get("audit_agency", "—")) if r.get("audit_agency") else "—"
            fees = r.get("audit_fees", None)
            if fees is not None and fees == fees:
                fees_str = f"{fees / 10000:.1f}"
            else:
                fees_str = "—"
            rows.append([year, opinion, agency, fees_str])

        table = format_table(headers, rows, alignments=["l", "l", "l", "r"])
        lines.append(table)
        return "\n".join(lines)

    # --- Feature #84: Section 14 — Risk-free rate ---

    def get_risk_free_rate(self) -> str:
        """Section 14: Risk-free rate from yc_cb (中债国债收益率曲线)."""
        lines = [format_header(2, "14. 无风险利率"), ""]
        try:
            today = pd.Timestamp.now().strftime("%Y%m%d")
            # Get recent 10-year government bond yield
            df = self._safe_call("yc_cb", ts_code="1001.CB",
                                 curve_type="0",
                                 curve_term="10",
                                 start_date=(pd.Timestamp.now() - pd.DateOffset(months=1)).strftime("%Y%m%d"),
                                 end_date=today,
                                 fields="trade_date,yield")
        except RuntimeError:
            lines.append("数据缺失 (接口可能无权限)\n")
            return "\n".join(lines)

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        df = df.sort_values("trade_date", ascending=False)

        # Store for derived metrics
        self._store["risk_free_rate"] = df

        latest = df.iloc[0]

        table = format_table(
            ["日期", "10年期国债收益率 (%)"],
            [[str(latest.get("trade_date", "—")),
              f"{latest.get('yield', 0):.4f}"]],
            alignments=["l", "r"],
        )
        lines.append(table)
        lines.append("")
        lines.append("*数据来源: 中债国债收益率曲线 (yc_cb)*")
        return "\n".join(lines)

    # --- Feature #85: Section 15 — Share repurchase ---

    def get_repurchase(self, ts_code: str) -> str:
        """Section 15: Share repurchase data from repurchase endpoint."""
        lines = [format_header(2, "15. 股票回购"), ""]
        try:
            df = self._safe_call("repurchase", ts_code=ts_code,
                                 fields="ts_code,ann_date,end_date,proc,exp_date,"
                                        "vol,amount,high_limit,low_limit")
        except RuntimeError:
            lines.append("数据缺失 (接口可能无权限)\n")
            return "\n".join(lines)

        if df.empty:
            lines.append("近3年无回购记录\n")
            return "\n".join(lines)

        # Filter to last 3 years
        three_years_ago = (pd.Timestamp.now() - pd.DateOffset(years=3)).strftime("%Y%m%d")
        if "ann_date" in df.columns:
            df = df[df["ann_date"] >= three_years_ago].copy()

        if df.empty:
            lines.append("近3年无回购记录\n")
            return "\n".join(lines)

        df = df.sort_values("ann_date", ascending=False)

        # Store for derived metrics
        self._store["repurchase"] = df

        headers = ["公告日", "回购金额 (百万元)", "回购股数 (万股)", "价格下限", "价格上限"]
        rows = []
        total_amount = 0
        for _, r in df.iterrows():
            amt = r.get("amount", None)
            vol = r.get("vol", None)
            if amt is not None and amt == amt:
                total_amount += float(amt)
            rows.append([
                str(r.get("ann_date", "—")),
                format_number(amt),
                format_number(vol, divider=1e4, decimals=2) if vol is not None and vol == vol else "—",
                f"{r.get('low_limit', 0):.2f}" if r.get("low_limit") is not None else "—",
                f"{r.get('high_limit', 0):.2f}" if r.get("high_limit") is not None else "—",
            ])

        table = format_table(headers, rows,
                             alignments=["l", "r", "r", "r", "r"])
        lines.append(table)
        lines.append("")
        lines.append(f"近3年累计回购金额: {format_number(total_amount)} 百万元")
        years_span = min(3, max(1, len(set(str(r.get("ann_date", ""))[:4] for _, r in df.iterrows()))))
        lines.append(f"年均回购金额: {format_number(total_amount / years_span)} 百万元")
        return "\n".join(lines)

    # --- Feature #86: Section 16 — Share pledge statistics ---

    def get_pledge_stat(self, ts_code: str) -> str:
        """Section 16: Share pledge statistics from pledge_stat endpoint."""
        lines = [format_header(2, "16. 股权质押"), ""]
        try:
            df = self._safe_call("pledge_stat", ts_code=ts_code,
                                 fields="ts_code,end_date,pledge_count,"
                                        "unrest_pledge,rest_pledge,"
                                        "total_share,pledge_ratio")
        except RuntimeError:
            lines.append("数据缺失 (接口可能无权限)\n")
            return "\n".join(lines)

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        df = df.sort_values("end_date", ascending=False)
        latest = df.iloc[0]

        table = format_table(
            ["项目", "数值"],
            [
                ["统计日期", str(latest.get("end_date", "—"))],
                ["质押笔数", f"{int(latest.get('pledge_count', 0))}"],
                ["无限售质押 (万股)", format_number(latest.get("unrest_pledge"), divider=1e4, decimals=2)],
                ["有限售质押 (万股)", format_number(latest.get("rest_pledge"), divider=1e4, decimals=2)],
                ["总股本 (万股)", format_number(latest.get("total_share"), divider=1e4, decimals=2)],
                ["质押比例 (%)", f"{latest.get('pledge_ratio', 0):.2f}"],
            ],
            alignments=["l", "r"],
        )
        lines.append(table)
        return "\n".join(lines)

    # --- Feature #90-92: Derived metrics (Section 17) ---

    @staticmethod
    def _safe_float(val) -> float | None:
        """Convert a value to float, returning None for NaN/None."""
        if val is None:
            return None
        try:
            f = float(val)
            return None if f != f else f  # NaN check
        except (TypeError, ValueError):
            return None

    def _get_annual_df(self, store_key: str) -> pd.DataFrame:
        """Get stored DataFrame filtered to annual periods only (end_date ending in 1231)."""
        df = self._store.get(store_key)
        if df is None or df.empty:
            return pd.DataFrame()
        annual = df[df["end_date"].str.endswith("1231")].copy()
        return annual.sort_values("end_date", ascending=False)

    def _get_annual_series(self, store_key: str, col: str) -> list[tuple[str, float | None]]:
        """Extract (year_label, value) pairs for annual periods, sorted desc."""
        df = self._get_annual_df(store_key)
        if df.empty or col not in df.columns:
            return []
        result = []
        for _, r in df.iterrows():
            year = str(r["end_date"])[:4]
            result.append((year, self._safe_float(r.get(col))))
        return result

    def _compute_financial_trends(self) -> str | None:
        """Compute §17.1: Financial trend summary (CAGR, debt ratios, net cash, payout)."""
        income_df = self._get_annual_df("income")
        bs_df = self._get_annual_df("balance_sheet")

        if income_df.empty or len(income_df) < 2:
            return None

        years_labels = [str(r["end_date"])[:4] for _, r in income_df.iterrows()]
        n_years = len(years_labels)

        lines = [format_header(3, "17.1 财务趋势速览"), ""]

        # --- Revenue & Net Profit series ---
        rev_series = [(y, self._safe_float(r.get("revenue"))) for y, (_, r) in zip(years_labels, income_df.iterrows())]
        np_series = [(y, self._safe_float(r.get("n_income_attr_p"))) for y, (_, r) in zip(years_labels, income_df.iterrows())]

        # CAGR calculation
        def _cagr(series: list[tuple[str, float | None]]) -> str:
            vals = [v for _, v in series if v is not None and v > 0]
            if len(vals) < 2:
                return "—"
            # series is desc order: [latest, ..., oldest]
            latest, oldest = vals[0], vals[-1]
            n = len(vals) - 1
            if oldest <= 0:
                return "—"
            cagr = (latest / oldest) ** (1 / n) - 1
            return f"{cagr * 100:.2f}%"

        rev_cagr = _cagr(rev_series)
        np_cagr = _cagr(np_series)

        # --- Interest-bearing debt per year ---
        def _interest_bearing_debt(row) -> float | None:
            components = ["st_borr", "lt_borr", "bond_payable", "non_cur_liab_due_1y"]
            total = 0.0
            any_valid = False
            for c in components:
                v = self._safe_float(row.get(c))
                if v is not None:
                    total += v
                    any_valid = True
            return total if any_valid else None

        debt_series = []  # (year, debt_raw)
        debt_ratio_series = []  # (year, ratio_pct)
        net_cash_series = []  # (year, net_cash_raw)
        if not bs_df.empty:
            for _, r in bs_df.iterrows():
                year = str(r["end_date"])[:4]
                debt = _interest_bearing_debt(r)
                ta = self._safe_float(r.get("total_assets"))
                cash = self._safe_float(r.get("money_cap"))
                debt_series.append((year, debt))
                if debt is not None and ta and ta > 0:
                    debt_ratio_series.append((year, debt / ta * 100))
                else:
                    debt_ratio_series.append((year, None))
                if cash is not None and debt is not None:
                    net_cash_series.append((year, cash - debt))
                else:
                    net_cash_series.append((year, None))

        # --- Payout ratio per year ---
        div_df = self._store.get("dividends")
        payout_series = []  # (year, payout_pct)
        if div_df is not None and not div_df.empty:
            # Build dividend total lookup by year
            div_lookup = {}
            for _, r in div_df.iterrows():
                year = str(r.get("end_date", ""))[:4]
                cash_div = self._safe_float(r.get("cash_div_tax")) or 0
                base_share = self._safe_float(r.get("base_share")) or 0
                div_total = cash_div * base_share * 10000  # base_share is 万股
                div_lookup[year] = div_total

            for y, np_val in np_series:
                div_total = div_lookup.get(y)
                if div_total and np_val and np_val > 0:
                    payout_series.append((y, div_total / np_val * 100))
                else:
                    payout_series.append((y, None))

        # --- Build table ---
        # Use income years as primary (most complete)
        def _fmt_val(val: float | None, divider: float = 1e6, is_pct: bool = False) -> str:
            if val is None:
                return "—"
            if is_pct:
                return f"{val:.2f}"
            return format_number(val, divider=divider)

        def _lookup(series: list[tuple[str, float | None]], year: str) -> float | None:
            for y, v in series:
                if y == year:
                    return v
            return None

        headers = ["指标"] + years_labels + ["5年CAGR"]
        rows = []

        # Revenue
        row = ["营业收入（百万元）"]
        for y, v in rev_series:
            row.append(_fmt_val(v))
        row.append(rev_cagr)
        rows.append(row)

        # Net profit
        row = ["归母净利润（百万元）"]
        for y, v in np_series:
            row.append(_fmt_val(v))
        row.append(np_cagr)
        rows.append(row)

        # Interest-bearing debt
        row = ["有息负债（百万元）"]
        for y in years_labels:
            row.append(_fmt_val(_lookup(debt_series, y)))
        row.append("—")
        rows.append(row)

        # Debt/total_assets ratio
        row = ["有息负债/总资产（%）"]
        for y in years_labels:
            row.append(_fmt_val(_lookup(debt_ratio_series, y), is_pct=True))
        row.append("—")
        rows.append(row)

        # Net cash
        row = ["广义净现金（百万元）"]
        for y in years_labels:
            row.append(_fmt_val(_lookup(net_cash_series, y)))
        row.append("—")
        rows.append(row)

        # Payout ratio
        row = ["股息支付率（%）"]
        for y in years_labels:
            row.append(_fmt_val(_lookup(payout_series, y), is_pct=True))
        row.append("—")
        rows.append(row)

        table = format_table(headers, rows, alignments=["l"] + ["r"] * (n_years + 1))
        lines.append(table)
        return "\n".join(lines)

    def _compute_factor2_inputs(self, ts_code: str) -> str | None:
        """Compute §17.2: Factor 2 input parameters (OE components, payout, threshold)."""
        income_df = self._get_annual_df("income")
        cf_df = self._get_annual_df("cashflow")

        if income_df.empty:
            return None

        years_labels = [str(r["end_date"])[:4] for _, r in income_df.iterrows()]
        n_years = len(years_labels)
        lines = [format_header(3, "17.2 因子2输入参数"), ""]

        # --- Per-year table: C, B, minority%, D&A, Capex, Capex/D&A, FCF ---
        headers = ["变量"] + years_labels
        rows = []

        # C = n_income_attr_p (already in millions after format_number)
        c_row = ["C 归母净利润"]
        b_row = ["B 少数股东损益"]
        min_pct_row = ["少数股东占比（%）"]
        for _, r in income_df.iterrows():
            c = self._safe_float(r.get("n_income_attr_p"))
            b = self._safe_float(r.get("minority_gain"))
            ni = self._safe_float(r.get("n_income"))
            c_row.append(format_number(c))
            b_row.append(format_number(b))
            if b is not None and ni and ni != 0:
                min_pct_row.append(f"{b / ni * 100:.2f}")
            else:
                min_pct_row.append("—")
        rows.extend([c_row, b_row, min_pct_row])

        # D&A and Capex from cashflow
        da_row = ["D 折旧与摊销"]
        capex_row = ["E 资本开支"]
        capex_da_row = ["Capex/D&A"]
        fcf_row = ["FCF = OCF - |Capex|"]
        da_vals = []  # for median calculation
        capex_vals = []  # for median calculation
        capex_da_vals = []

        if not cf_df.empty:
            # Align cashflow by year
            cf_by_year = {}
            for _, r in cf_df.iterrows():
                y = str(r["end_date"])[:4]
                cf_by_year[y] = r

            for y in years_labels:
                r = cf_by_year.get(y)
                if r is None:
                    da_row.append("—"); capex_row.append("—")
                    capex_da_row.append("—"); fcf_row.append("—")
                    continue

                depr = self._safe_float(r.get("depr_fa_coga_dpba"))
                amort_i = self._safe_float(r.get("amort_intang_assets"))
                amort_d = self._safe_float(r.get("lt_amort_deferred_exp"))
                da_components = [v for v in [depr, amort_i, amort_d] if v is not None]
                da = sum(da_components) if da_components else None

                capex = self._safe_float(r.get("c_pay_acq_const_fiolta"))
                ocf = self._safe_float(r.get("n_cashflow_act"))

                da_row.append(format_number(da) if da is not None else "—")
                capex_row.append(format_number(capex))
                if da and da > 0 and capex is not None:
                    ratio = abs(capex) / da
                    capex_da_row.append(f"{ratio:.2f}")
                    da_vals.append(da)
                    capex_vals.append(abs(capex))
                    capex_da_vals.append(ratio)
                else:
                    capex_da_row.append("—")
                if ocf is not None and capex is not None:
                    fcf_row.append(format_number(ocf - abs(capex)))
                else:
                    fcf_row.append("—")
        else:
            for _ in years_labels:
                da_row.append("—"); capex_row.append("—")
                capex_da_row.append("—"); fcf_row.append("—")

        rows.extend([da_row, capex_row, capex_da_row, fcf_row])

        table = format_table(headers, rows, alignments=["l"] + ["r"] * n_years)
        lines.append(table)
        lines.append("")

        # --- Summary variables ---
        summary_rows = []

        # F = Capex/D&A 5-year median
        if capex_da_vals:
            sorted_vals = sorted(capex_da_vals)
            mid = len(sorted_vals) // 2
            f_median = sorted_vals[mid] if len(sorted_vals) % 2 else (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
            summary_rows.append(["F（Capex/D&A 5年中位数）", f"{f_median:.2f}", "—"])
        else:
            summary_rows.append(["F（Capex/D&A 5年中位数）", "—", "数据不足"])

        # Payout ratio: M, N
        div_df = self._store.get("dividends")
        payout_ratios = []
        if div_df is not None and not div_df.empty:
            div_lookup = {}
            for _, r in div_df.iterrows():
                y = str(r.get("end_date", ""))[:4]
                cash_div = self._safe_float(r.get("cash_div_tax")) or 0
                base_share = self._safe_float(r.get("base_share")) or 0
                div_lookup[y] = cash_div * base_share * 10000

            # Use latest 3 years
            for y in years_labels[:3]:
                div_total = div_lookup.get(y)
                for _, r in income_df.iterrows():
                    if str(r["end_date"])[:4] == y:
                        np_val = self._safe_float(r.get("n_income_attr_p"))
                        if div_total and np_val and np_val > 0:
                            payout_ratios.append(div_total / np_val * 100)
                        break

        if payout_ratios:
            m_mean = sum(payout_ratios) / len(payout_ratios)
            if len(payout_ratios) > 1:
                variance = sum((x - m_mean) ** 2 for x in payout_ratios) / (len(payout_ratios) - 1)
                n_std = variance ** 0.5
            else:
                n_std = 0
            summary_rows.append(["M（支付率3年均值）", f"{m_mean:.2f}%", f"基于 {len(payout_ratios)} 年"])
            summary_rows.append(["N（支付率3年标准差）", f"{n_std:.2f}%", "—"])
        else:
            summary_rows.append(["M（支付率3年均值）", "—", "分红数据不足"])
            summary_rows.append(["N（支付率3年标准差）", "—", "—"])

        # O = buyback annual average
        rep_df = self._store.get("repurchase")
        if rep_df is not None and not rep_df.empty:
            total_amt = 0.0
            for _, r in rep_df.iterrows():
                amt = self._safe_float(r.get("amount"))
                if amt:
                    total_amt += amt
            o_avg = total_amt / 3  # always over 3 years per spec
            summary_rows.append(["O（年均回购金额）", f"{format_number(o_avg)} 百万", "来自 §15 近3年"])
        else:
            summary_rows.append(["O（年均回购金额）", "0.00 百万", "无回购记录"])

        # Rf and II (threshold)
        rf_df = self._store.get("risk_free_rate")
        rf_val = None
        if rf_df is not None and not rf_df.empty:
            rf_val = self._safe_float(rf_df.iloc[0].get("yield"))

        if rf_val is not None:
            summary_rows.append(["Rf（无风险利率）", f"{rf_val:.4f}%", "来自 §14"])
            # Determine market type from ts_code
            if ts_code.endswith(".HK"):
                ii = max(5.0, rf_val + 3.0)
                summary_rows.append(["II（门槛值）", f"{ii:.2f}%", f"港股: max(5%, {rf_val:.2f}%+3%)"])
            else:  # A-share default
                ii = max(3.5, rf_val + 2.0)
                summary_rows.append(["II（门槛值）", f"{ii:.2f}%", f"A股: max(3.5%, {rf_val:.2f}%+2%)"])
        else:
            summary_rows.append(["Rf（无风险利率）", "—", "数据缺失"])
            summary_rows.append(["II（门槛值）", "—", "需Rf"])

        # OE base case (G=1.0)
        latest_c = self._safe_float(income_df.iloc[0].get("n_income_attr_p"))
        if latest_c is not None:
            summary_rows.append(["OE_base（G=1.0）", f"{format_number(latest_c)} 百万",
                                 "OE = C + D×(1-G); LLM 选 G 后代入"])

        summary_table = format_table(["汇总变量", "值", "说明"], summary_rows,
                                     alignments=["l", "r", "l"])
        lines.append(summary_table)
        return "\n".join(lines)

    def _compute_factor4_inputs(self) -> str | None:
        """Compute §17.6: Price percentiles from 10yr weekly data."""
        wp_df = self._store.get("weekly_prices")
        basic_df = self._store.get("basic_info")

        if wp_df is None or wp_df.empty:
            return None

        lines = [format_header(3, "17.6 因子4·股价分位"), ""]

        closes = wp_df["close"].dropna().tolist()
        if not closes:
            return None

        nn = len(closes)
        current_price = closes[-1] if closes else None  # latest (sorted ascending)

        # Also try from basic_info
        if basic_df is not None and not basic_df.empty:
            bp = self._safe_float(basic_df.iloc[0].get("close"))
            if bp is not None:
                current_price = bp

        if current_price is None:
            return None

        # Current price percentile
        below_count = sum(1 for c in closes if c < current_price)
        current_percentile = below_count / nn * 100

        # Key percentile prices
        sorted_closes = sorted(closes)

        def _percentile_price(pct: float) -> float:
            idx = int(pct / 100 * (nn - 1))
            return sorted_closes[min(idx, nn - 1)]

        rows = [
            ["10年数据点数", str(nn)],
            ["当前股价", f"{current_price:.2f}"],
            ["当前股价历史分位", f"{current_percentile:.1f}%"],
            ["10%分位价格", f"{_percentile_price(10):.2f}"],
            ["25%分位价格", f"{_percentile_price(25):.2f}"],
            ["50%分位价格（中位数）", f"{_percentile_price(50):.2f}"],
            ["75%分位价格", f"{_percentile_price(75):.2f}"],
            ["90%分位价格", f"{_percentile_price(90):.2f}"],
        ]

        table = format_table(["指标", "值"], rows, alignments=["l", "r"])
        lines.append(table)
        return "\n".join(lines)

    def _compute_sotp_inputs(self) -> str | None:
        """Compute §17.7: SOTP holding company structure inputs from parent/consolidated BS."""
        bs_df = self._get_annual_df("balance_sheet")
        bs_parent_df = self._get_annual_df("balance_sheet_parent")

        if bs_df.empty or bs_parent_df.empty:
            return None

        lines = [format_header(3, "17.7 控股结构辅助"), ""]

        latest_consol = bs_df.iloc[0]
        latest_parent = bs_parent_df.iloc[0]

        def _debt(row):
            components = ["st_borr", "lt_borr", "bond_payable", "non_cur_liab_due_1y"]
            total = 0.0
            for c in components:
                v = self._safe_float(row.get(c))
                if v:
                    total += v
            return total

        consol_debt = _debt(latest_consol)
        parent_debt = _debt(latest_parent)
        consol_cash = self._safe_float(latest_consol.get("money_cap")) or 0
        parent_cash = self._safe_float(latest_parent.get("money_cap")) or 0

        rows = [
            ["有息负债", format_number(consol_debt), format_number(parent_debt)],
            ["现金", format_number(consol_cash), format_number(parent_cash)],
            ["净现金", format_number(consol_cash - consol_debt), format_number(parent_cash - parent_debt)],
        ]

        if consol_debt > 0:
            sub_ratio = (consol_debt - parent_debt) / consol_debt * 100
            rows.append(["子公司层面负债占比", f"{sub_ratio:.1f}%", "—"])

        table = format_table(["指标", "合并口径", "母公司口径"], rows,
                             alignments=["l", "r", "r"])
        lines.append(table)
        return "\n".join(lines)

    # --- Feature #94: §17.8 EV baseline + "买入就是胜利"基准价 ---

    def _compute_factor4_ev_baseline(self, ts_code: str) -> str | None:
        """Compute §17.8: Valuation dashboard + floor-price baseline.

        Requires basic_info in _store (provides close, total_mv, total_share).
        All amounts in 百万元 unless stated otherwise.
        """
        basic_df = self._store.get("basic_info")
        if basic_df is None or basic_df.empty:
            return None

        bi = basic_df.iloc[0]
        close = self._safe_float(bi.get("close"))
        total_mv_wan = self._safe_float(bi.get("total_mv"))  # 万元
        total_share_wan = self._safe_float(bi.get("total_share"))  # 万股

        if not close or not total_mv_wan or not total_share_wan or total_share_wan <= 0:
            return None

        # Convert to common units
        mkt_cap_yuan = total_mv_wan * 10000  # yuan
        mkt_cap = mkt_cap_yuan / 1e6  # 百万元
        total_shares = total_share_wan * 10000  # 股

        # --- Gather data from _store ---
        income_df = self._get_annual_df("income")
        bs_df = self._get_annual_df("balance_sheet")
        cf_df = self._get_annual_df("cashflow")

        if income_df.empty or bs_df.empty or cf_df.empty:
            return None

        latest_inc = income_df.iloc[0]
        latest_bs = bs_df.iloc[0]
        latest_cf = cf_df.iloc[0]

        # Helper: interest-bearing debt components (yuan)
        def _ibd_yuan(row):
            total = 0.0
            for c in ["st_borr", "lt_borr", "bond_payable", "non_cur_liab_due_1y"]:
                v = self._safe_float(row.get(c))
                if v:
                    total += v
            return total

        ibd_yuan = _ibd_yuan(latest_bs)
        cash_yuan = self._safe_float(latest_bs.get("money_cap")) or 0
        trad_yuan = self._safe_float(latest_bs.get("trad_asset")) or 0
        goodwill_yuan = self._safe_float(latest_bs.get("goodwill")) or 0
        total_assets_yuan = self._safe_float(latest_bs.get("total_assets")) or 0
        equity_yuan = self._safe_float(latest_bs.get("total_hldr_eqy_exc_min_int")) or 0

        oper_profit_yuan = self._safe_float(latest_inc.get("operate_profit")) or 0
        finance_exp_yuan = self._safe_float(latest_inc.get("finance_exp")) or 0
        np_parent_yuan = self._safe_float(latest_inc.get("n_income_attr_p")) or 0

        da_yuan = 0.0
        for c in ["depr_fa_coga_dpba", "amort_intang_assets", "lt_amort_deferred_exp"]:
            v = self._safe_float(latest_cf.get(c))
            if v:
                da_yuan += v

        ocf_yuan = self._safe_float(latest_cf.get("n_cashflow_act")) or 0
        capex_yuan = self._safe_float(latest_cf.get("c_pay_acq_const_fiolta")) or 0
        fcf_yuan = ocf_yuan - capex_yuan

        # Convert to 百万元
        ibd = ibd_yuan / 1e6
        cash = cash_yuan / 1e6
        trad = trad_yuan / 1e6
        goodwill = goodwill_yuan / 1e6
        ta = total_assets_yuan / 1e6
        equity = equity_yuan / 1e6
        oper_profit = oper_profit_yuan / 1e6
        fin_exp = finance_exp_yuan / 1e6
        np_parent = np_parent_yuan / 1e6
        da = da_yuan / 1e6
        fcf = fcf_yuan / 1e6

        # ===== Part A: Valuation indicators =====
        ev = mkt_cap + ibd - cash
        ebitda = oper_profit + fin_exp + da
        net_cash = cash - ibd

        ev_ebitda = f"{ev / ebitda:.2f}x" if ebitda > 0 else "—"
        cash_pe = f"{(mkt_cap - net_cash) / np_parent:.2f}x" if np_parent > 0 else "—"
        fcf_yield = f"{fcf / mkt_cap * 100:.2f}%" if mkt_cap > 0 else "—"
        pb = f"{mkt_cap / equity:.2f}x" if equity > 0 else "—"
        net_debt_ebitda = f"{(ibd - cash) / ebitda:.2f}x" if ebitda > 0 else "—"
        goodwill_ratio = f"{goodwill / ta * 100:.2f}%" if ta > 0 else "—"
        ibd_ratio = f"{ibd / ta * 100:.2f}%" if ta > 0 else "—"

        # Dividend yield: latest DPS / close
        div_yield_str = "—"
        div_df = self._store.get("dividends")
        latest_dps = None
        if div_df is not None and not div_df.empty:
            sorted_div = div_df.sort_values("end_date", ascending=False)
            latest_dps = self._safe_float(sorted_div.iloc[0].get("cash_div_tax"))
            if latest_dps is not None and close > 0:
                div_yield_str = f"{latest_dps / close * 100:.2f}%"

        lines = [format_header(3, '17.8 因子4·绝对估值与"买入就是胜利"基准价'), ""]

        # Valuation table
        lines.append("#### 估值指标")
        lines.append("")
        fmt = lambda v: format_number(v, divider=1)
        val_rows = [
            ["总市值（百万元）", fmt(mkt_cap), "—"],
            ["企业价值 EV（百万元）", fmt(ev), "市值+有息负债-现金"],
            ["EBITDA（百万元）", fmt(ebitda), "营业利润+财务费用+D&A"],
            ["EV/EBITDA", ev_ebitda, "—"],
            ["扣除现金PE", cash_pe, "(市值-净现金)/归母净利润"],
            ["FCF收益率", fcf_yield, "FCF/市值"],
            ["P/B", pb, "市值/归母权益"],
            ["净负债/EBITDA", net_debt_ebitda, "(有息负债-现金)/EBITDA，负值=净现金"],
            ["商誉/总资产", goodwill_ratio, "—"],
            ["有息负债率", ibd_ratio, "有息负债/总资产"],
            ["股息率", div_yield_str, "最新DPS/当前股价"],
        ]
        lines.append(format_table(["指标", "值", "说明"], val_rows,
                                  alignments=["l", "r", "l"]))
        lines.append("")

        # ===== Part B: "买入就是胜利" baselines =====
        lines.append('#### "买入就是胜利"基准价')
        lines.append("")

        baselines = []  # (name, value_yuan_per_share, logic)

        # ① Net liquid assets / share
        nla = (cash_yuan + trad_yuan - ibd_yuan) / total_shares
        baselines.append(("① 净流动资产/股", nla, "(现金+交易性金融资产-有息负债)/总股本"))

        # ② BVPS
        bvps = equity_yuan / total_shares
        baselines.append(("② 每股净资产", bvps, "归母权益/总股本"))

        # ③ 10-year low from weekly prices
        wp_df = self._store.get("weekly_prices")
        if wp_df is not None and not wp_df.empty:
            min_close = wp_df["close"].dropna().min()
            if min_close is not None and min_close == min_close:  # NaN check
                baselines.append(("③ 10年最低价", float(min_close), "周线最低收盘价"))

        # ④ Dividend yield implied price: 3yr avg DPS / max(Rf, 3%)
        rf_df = self._store.get("risk_free_rate")
        rf_pct = None
        if rf_df is not None and not rf_df.empty:
            rf_pct = self._safe_float(rf_df.iloc[0].get("yield"))

        if div_df is not None and not div_df.empty and rf_pct is not None:
            sorted_div = div_df.sort_values("end_date", ascending=False)
            recent_dps = []
            for _, row in sorted_div.head(3).iterrows():
                v = self._safe_float(row.get("cash_div_tax"))
                if v is not None:
                    recent_dps.append(v)
            if recent_dps:
                avg_dps = sum(recent_dps) / len(recent_dps)
                discount = max(rf_pct / 100, 0.03)
                implied_price = avg_dps / discount
                baselines.append(("④ 股息隐含价", implied_price,
                                  f"3年均DPS÷max(Rf,3%)"))

        # ⑤ Pessimistic FCF capitalization: min(5yr FCF) / Rf / total_shares
        if rf_pct is not None and rf_pct > 0:
            fcf_list = []
            for _, row in cf_df.iterrows():
                ocf_v = self._safe_float(row.get("n_cashflow_act"))
                cap_v = self._safe_float(row.get("c_pay_acq_const_fiolta"))
                if ocf_v is not None and cap_v is not None:
                    fcf_list.append(ocf_v - cap_v)
            if fcf_list and min(fcf_list) > 0:
                min_fcf = min(fcf_list)
                cap_price = min_fcf / (rf_pct / 100) / total_shares
                baselines.append(("⑤ 悲观FCF资本化", cap_price,
                                  "min(5年FCF)÷Rf÷总股本"))

        # Build baseline table
        bl_rows = []
        valid_prices = []
        for name, val, logic in baselines:
            bl_rows.append([name, f"{val:.2f}", logic])
            valid_prices.append(val)

        lines.append(format_table(["方法", "基准价（元）", "计算逻辑"], bl_rows,
                                  alignments=["l", "r", "l"]))
        lines.append("")

        # ===== Part C: Composite baseline =====
        if valid_prices:
            sorted_prices = sorted(valid_prices)
            n = len(sorted_prices)
            if n % 2 == 1:
                composite = sorted_prices[n // 2]
            else:
                composite = (sorted_prices[n // 2 - 1] + sorted_prices[n // 2]) / 2

            lines.append(f"**综合基准价（中位数）= {composite:.2f} 元**")

            if len(valid_prices) < 3:
                lines.append("*数据不足（有效方法<3），仅供参考*")

            # ===== Part D: Premium analysis =====
            premium = (close / composite - 1) * 100
            lines.append(f"当前股价 {close:.2f} 元，较基准价溢价 **{premium:.1f}%**")

            if premium <= 0:
                verdict = "低于基准线 — 买入就是胜利"
            elif premium <= 30:
                verdict = "接近基准线 — 安全边际充足"
            elif premium <= 80:
                verdict = "合理溢价 — 需确认成长性"
            elif premium <= 150:
                verdict = "较高溢价 — 依赖持续成长"
            else:
                verdict = "显著溢价 — 高成长预期已定价"

            lines.append(f"→ {verdict}")

        return "\n".join(lines)

    # --- Feature #92: §17.3-17.5 Factor 3 base case computations ---

    def _compute_factor3_step1(self) -> str | None:
        """Compute §17.3: True cash revenue (步骤1).

        Conservative base case:
        - Deduct AR increases (revenue not yet collected as cash)
        - Deduct contract liability decreases (consumed pre-collected cash)
        - Do NOT add back AR decreases or CL increases (conservative)
        Stores results in self._store["_true_cash_rev"] for §17.5.
        """
        income_df = self._get_annual_df("income")
        bs_df = self._get_annual_df("balance_sheet")

        if income_df.empty or bs_df.empty or len(income_df) < 2:
            return None

        # Build year-indexed lookups from balance sheet
        bs_by_year = {}
        for _, r in bs_df.iterrows():
            year = str(r["end_date"])[:4]
            bs_by_year[year] = r

        # Income years (desc order)
        income_years = [str(r["end_date"])[:4] for _, r in income_df.iterrows()]

        # Compute changes — need year and prior year in BS
        results = []  # (year, S, T, U, true_cash_rev, collection_ratio) in raw yuan
        true_cash_rev_store = {}

        for i, year in enumerate(income_years):
            # Find prior year in income (next in list since desc)
            prior_year = str(int(year) - 1)
            if year not in bs_by_year or prior_year not in bs_by_year:
                continue

            bs_cur = bs_by_year[year]
            bs_prev = bs_by_year[prior_year]

            # S = revenue (raw yuan)
            s = self._safe_float(income_df[income_df["end_date"].str.startswith(year)].iloc[0].get("revenue"))
            if s is None:
                continue

            # T = AR change (increase positive)
            ar_cur = self._safe_float(bs_cur.get("accounts_receiv")) or 0
            ar_prev = self._safe_float(bs_prev.get("accounts_receiv")) or 0
            t = ar_cur - ar_prev

            # U = contract_liab change (increase positive)
            cl_cur = self._safe_float(bs_cur.get("contract_liab")) or 0
            cl_prev = self._safe_float(bs_prev.get("contract_liab")) or 0
            u = cl_cur - cl_prev

            # Conservative: deduct AR increases, deduct CL decreases
            true_cash = s - max(0, t) - max(0, -u)
            ratio = true_cash / s if s > 0 else None

            results.append((year, s, t, u, true_cash, ratio))
            true_cash_rev_store[year] = true_cash

        if not results:
            return None

        # Store for §17.5
        self._store["_true_cash_rev"] = true_cash_rev_store

        # Build output
        lines = [format_header(3, "17.3 因子3·步骤1 真实现金收入（保守基准）"), ""]
        lines.append("> AR增加扣除，CL增加不加回。LLM 可根据例外规则（如白酒预收）调整。")
        lines.append("")

        headers = ["年份", "S 营业收入", "T 应收变动", "U 合同负债变动",
                   "真实现金收入", "收款比率"]
        rows = []
        for year, s, t, u, tcr, ratio in results:
            rows.append([
                year,
                format_number(s),
                format_number(t),
                format_number(u),
                format_number(tcr),
                f"{ratio * 100:.2f}%" if ratio is not None else "—",
            ])
        table = format_table(headers, rows,
                             alignments=["l"] + ["r"] * 5)
        lines.append(table)
        return "\n".join(lines)

    def _compute_factor3_step4(self) -> str | None:
        """Compute §17.4: Operating cash outflows (步骤4).

        W1 = oper_cost + max(0, -AP_change)
        W2 = c_pay_to_staff (from cashflow)
        W3 = income_tax - deferred_tax_net_change
        W4 = finance_exp
        Stores results in self._store["_w_total"] for §17.5.
        """
        income_df = self._get_annual_df("income")
        bs_df = self._get_annual_df("balance_sheet")
        cf_df = self._get_annual_df("cashflow")

        if income_df.empty or bs_df.empty or cf_df.empty or len(income_df) < 2:
            return None

        # Build lookups
        bs_by_year = {}
        for _, r in bs_df.iterrows():
            bs_by_year[str(r["end_date"])[:4]] = r
        cf_by_year = {}
        for _, r in cf_df.iterrows():
            cf_by_year[str(r["end_date"])[:4]] = r
        inc_by_year = {}
        for _, r in income_df.iterrows():
            inc_by_year[str(r["end_date"])[:4]] = r

        income_years = [str(r["end_date"])[:4] for _, r in income_df.iterrows()]

        results = []  # (year, W1, W2, W3, W4, W)
        w_total_store = {}

        for year in income_years:
            prior_year = str(int(year) - 1)
            if year not in bs_by_year or prior_year not in bs_by_year:
                continue
            if year not in cf_by_year or year not in inc_by_year:
                continue

            inc = inc_by_year[year]
            bs_cur = bs_by_year[year]
            bs_prev = bs_by_year[prior_year]
            cf = cf_by_year[year]

            # W1: supplier = oper_cost + max(0, -AP_change)
            oper_cost = self._safe_float(inc.get("oper_cost")) or 0
            ap_cur = self._safe_float(bs_cur.get("acct_payable")) or 0
            ap_prev = self._safe_float(bs_prev.get("acct_payable")) or 0
            ap_change = ap_cur - ap_prev
            w1 = oper_cost + max(0, -ap_change)

            # W2: employee = c_pay_to_staff
            w2 = self._safe_float(cf.get("c_pay_to_staff")) or 0

            # W3: cash tax = income_tax - (DTA_change - DTL_change)
            income_tax = self._safe_float(inc.get("income_tax")) or 0
            dta_cur = self._safe_float(bs_cur.get("defer_tax_assets")) or 0
            dta_prev = self._safe_float(bs_prev.get("defer_tax_assets")) or 0
            dtl_cur = self._safe_float(bs_cur.get("defer_tax_liab")) or 0
            dtl_prev = self._safe_float(bs_prev.get("defer_tax_liab")) or 0
            deferred_net_change = (dta_cur - dta_prev) - (dtl_cur - dtl_prev)
            w3 = income_tax - deferred_net_change

            # W4: interest = finance_exp
            w4 = self._safe_float(inc.get("finance_exp")) or 0

            w = w1 + w2 + w3 + w4
            results.append((year, w1, w2, w3, w4, w))
            w_total_store[year] = w

        if not results:
            return None

        # Store for §17.5
        self._store["_w_total"] = w_total_store

        # Build output
        lines = [format_header(3, "17.4 因子3·步骤4 经营性现金支出"), ""]

        headers = ["年份", "W1 供应商", "W2 员工", "W3 现金税", "W4 利息", "W 合计"]
        rows = []
        for year, w1, w2, w3, w4, w in results:
            rows.append([
                year,
                format_number(w1),
                format_number(w2),
                format_number(w3),
                format_number(w4),
                format_number(w),
            ])
        table = format_table(headers, rows,
                             alignments=["l"] + ["r"] * 5)
        lines.append(table)
        return "\n".join(lines)

    def _compute_factor3_sensitivity_base(self) -> str | None:
        """Compute §17.5: Base surplus + sensitivity inputs.

        Base surplus = true_cash_revenue - W - Capex (per year, no V/X adjustments).
        Also computes: AA_incl, AA_excl, revenue CV, λ, λ reliability.
        Requires _compute_factor3_step1() and _compute_factor3_step4() to have run first.
        """
        true_cash_rev = self._store.get("_true_cash_rev")
        w_total = self._store.get("_w_total")
        if not true_cash_rev or not w_total:
            return None

        cf_df = self._get_annual_df("cashflow")
        income_df = self._get_annual_df("income")
        if cf_df.empty or income_df.empty:
            return None

        # Capex by year
        capex_by_year = {}
        for _, r in cf_df.iterrows():
            year = str(r["end_date"])[:4]
            capex_by_year[year] = self._safe_float(r.get("c_pay_acq_const_fiolta")) or 0

        # Revenue by year (for CV and λ)
        rev_by_year = {}
        for _, r in income_df.iterrows():
            year = str(r["end_date"])[:4]
            rev_by_year[year] = self._safe_float(r.get("revenue")) or 0

        # Compute base surplus per year (only years with all data)
        common_years = sorted(
            set(true_cash_rev.keys()) & set(w_total.keys()) & set(capex_by_year.keys()),
            reverse=True
        )
        if not common_years:
            return None

        surplus_data = []  # (year, tcr, w, capex, base_surplus)
        for year in common_years:
            tcr = true_cash_rev[year]
            w = w_total[year]
            capex = capex_by_year.get(year, 0)
            base = tcr - w - capex
            surplus_data.append((year, tcr, w, capex, base))

        surpluses = [s[4] for s in surplus_data]

        # AA_incl: mean of all years
        aa_incl = sum(surpluses) / len(surpluses)

        # AA_excl: exclude years where base_surplus < 0
        positive_surpluses = [s for s in surpluses if s >= 0]
        aa_excl = sum(positive_surpluses) / len(positive_surpluses) if positive_surpluses else aa_incl

        # Revenue CV (all available years, not just change-computed years)
        all_revenues = [rev_by_year[y] for y in sorted(rev_by_year.keys()) if rev_by_year[y] > 0]
        cv = None
        if len(all_revenues) >= 2:
            import statistics
            rev_mean = statistics.mean(all_revenues)
            rev_stdev = statistics.pstdev(all_revenues)  # population stdev
            cv = rev_stdev / rev_mean if rev_mean > 0 else None

        # λ: median(ΔSurplus/ΔRevenue) over latest 3 year-pairs
        lambda_vals = []
        sorted_years_asc = sorted(common_years)
        for i in range(1, len(sorted_years_asc)):
            y_cur = sorted_years_asc[i]
            y_prev = sorted_years_asc[i - 1]
            delta_s = rev_by_year.get(y_cur, 0) - rev_by_year.get(y_prev, 0)
            surplus_cur = next((s[4] for s in surplus_data if s[0] == y_cur), None)
            surplus_prev = next((s[4] for s in surplus_data if s[0] == y_prev), None)
            if surplus_cur is not None and surplus_prev is not None and delta_s != 0:
                delta_surplus = surplus_cur - surplus_prev
                lambda_vals.append(delta_surplus / delta_s)

        # Use latest 3 pairs
        lambda_vals = lambda_vals[-3:] if len(lambda_vals) > 3 else lambda_vals
        import statistics
        lambda_median = statistics.median(lambda_vals) if lambda_vals else None

        # λ reliability checks
        lambda_warnings = []
        if len(all_revenues) >= 3:
            # Check 1: revenue amplitude over years used for λ
            lambda_rev_years = sorted(common_years)
            lambda_revs = [rev_by_year.get(y, 0) for y in lambda_rev_years if rev_by_year.get(y, 0) > 0]
            if lambda_revs and min(lambda_revs) > 0:
                amplitude = max(lambda_revs) / min(lambda_revs) - 1
                if amplitude < 0.10:
                    lambda_warnings.append("历史收入波幅不足10%，λ外推可靠性低")

        # Check 2: sign consistency
        if lambda_vals:
            signs = [1 if v >= 0 else -1 for v in lambda_vals]
            if len(set(signs)) > 1:
                lambda_warnings.append("ΔSurplus/ΔRevenue符号不一致，成本结构可能变化")

        # Check 3: λ range
        if lambda_median is not None and (lambda_median > 3 or lambda_median < 0):
            lambda_warnings.append(f"λ={lambda_median:.2f}异常，建议人工核查")

        lambda_reliability = "正常"
        if len(lambda_warnings) >= 2 or (lambda_median is not None and (lambda_median > 3 or lambda_median < 0)):
            lambda_reliability = "多项警告或异常"
        elif len(lambda_warnings) == 1:
            lambda_reliability = "有一项警告"

        # Build output
        lines = [format_header(3, "17.5 因子3·步骤7 基准可支配结余 + 敏感性输入"), ""]
        lines.append("> 不含 V1/V5/-V_deduct/-X1/-X2 调整。LLM 需在此基础上加减调整项。")
        lines.append("")

        # Per-year table
        headers = ["年份", "真实现金收入", "- W 经营支出", "- E 资本开支", "= 基准结余"]
        rows = []
        for year, tcr, w, capex, base in surplus_data:
            rows.append([
                year,
                format_number(tcr),
                format_number(w),
                format_number(capex),
                format_number(base),
            ])
        table = format_table(headers, rows, alignments=["l"] + ["r"] * 4)
        lines.append(table)
        lines.append("")

        # Summary
        lines.append(f"- AA（含全部年份均值）= {format_number(aa_incl)} 百万元")
        lines.append(f"- AA（剔除负值年份均值）= {format_number(aa_excl)} 百万元")
        diff_pct = abs(aa_incl - aa_excl) / abs(aa_incl) * 100 if aa_incl != 0 else 0
        if diff_pct > 30:
            lines.append(f"  ⚠️ 两者差异 {diff_pct:.1f}% > 30%，建议以 AA_excl 为基准")
        lines.append(f"- 收入波动率 CV = {cv * 100:.2f}%" if cv is not None else "- 收入波动率 CV = —")
        lines.append(f"- 经营杠杆系数 λ = {lambda_median:.4f}" if lambda_median is not None else "- 经营杠杆系数 λ = —")
        lines.append(f"- λ可靠性 = {lambda_reliability}")
        for w_msg in lambda_warnings:
            lines.append(f"  ⚠️ {w_msg}")

        return "\n".join(lines)

    def compute_derived_metrics(self, ts_code: str) -> str:
        """Compute §17: Derived metrics from stored DataFrames.

        Must be called after all get_* methods have populated self._store.
        """
        lines = [
            format_header(2, "17. 衍生指标（Python 预计算）"),
            "",
            "> 以下指标基于 §1-§16 原始数据确定性计算，无 LLM 判断成分。Phase 3 可直接引用。百万元。",
            "",
        ]

        sub_methods = [
            self._compute_financial_trends,
            lambda: self._compute_factor2_inputs(ts_code),
            self._compute_factor3_step1,
            self._compute_factor3_step4,
            self._compute_factor3_sensitivity_base,
            self._compute_factor4_inputs,
            self._compute_sotp_inputs,
            lambda: self._compute_factor4_ev_baseline(ts_code),
        ]

        for method in sub_methods:
            try:
                result = method()
                if result:
                    lines.append(result)
                    lines.append("")
            except Exception as e:
                name = getattr(method, "__name__", str(method))
                lines.append(f"*{name} 计算失败: {e}*")
                lines.append("")

        return "\n".join(lines)

    # --- Feature #28: Full data_pack_market.md assembly ---

    def assemble_data_pack(self, ts_code: str) -> str:
        """Assemble complete data_pack_market.md combining all sections."""
        timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            format_header(1, f"数据包 — {ts_code}"),
            "",
            f"*生成时间: {timestamp}*",
            f"*数据来源: Tushare Pro*",
            f"*金额单位: 百万元 (除特殊标注)*",
            "",
            "---",
            "",
        ]

        sections = [
            ("1. 基本信息", self.get_basic_info),
            ("2. 市场行情", self.get_market_data),
            ("3. 合并利润表", self.get_income),
            ("3P. 母公司利润表", self.get_income_parent),
            ("4. 合并资产负债表", self.get_balance_sheet),
            ("4P. 母公司资产负债表", self.get_balance_sheet_parent),
            ("5. 现金流量表", self.get_cashflow),
            ("6. 分红历史", self.get_dividends),
            ("7. 股东与治理", self.get_holders),
            ("9. 主营业务构成", self.get_segments),
            ("11. 十年周线行情", self.get_weekly_prices),
            ("12. 关键财务指标", self.get_fina_indicators),
            ("15. 股票回购", self.get_repurchase),
            ("16. 股权质押", self.get_pledge_stat),
        ]

        completed = 0
        for name, method in sections:
            try:
                print(f"  Collecting {name}...")
                section_md = method(ts_code)
                lines.append(section_md)
                lines.append("")
                completed += 1
            except Exception as e:
                lines.append(format_header(2, name))
                lines.append(f"\n数据获取失败: {e}\n")

        # Audit info (sub-section of 7)
        try:
            audit_md = self.get_audit(ts_code)
            lines.append(audit_md)
            lines.append("")
        except Exception:
            pass

        # Risk-free rate (no ts_code needed)
        try:
            print("  Collecting 14. 无风险利率...")
            rf_md = self.get_risk_free_rate()
            lines.append(rf_md)
            lines.append("")
        except Exception as e:
            lines.append(format_header(2, "14. 无风险利率"))
            lines.append(f"\n数据获取失败: {e}\n")

        # Agent-only placeholder sections (§8, §10)
        for sec_num, sec_name in [
            ("8", "行业与竞争"),
            ("10", "管理层讨论与分析 (MD&A)"),
        ]:
            lines.append(format_header(2, f"{sec_num}. {sec_name}"))
            lines.append("")
            lines.append(f"*[§{sec_num} 待Agent WebSearch补充]*")
            lines.append("")

        # §17 Derived metrics (pre-computed from stored DataFrames)
        try:
            print("  Computing 17. 衍生指标...")
            derived_md = self.compute_derived_metrics(ts_code)
            lines.append(derived_md)
            lines.append("")
        except Exception as e:
            lines.append(format_header(2, "17. 衍生指标（Python 预计算）"))
            lines.append(f"\n计算失败: {e}\n")

        # §13 Warnings: auto-detect + agent placeholder
        wc = WarningsCollector()
        try:
            # Check missing data for core financial statements
            for label, api, fields in [
                ("合并利润表", "income", "ts_code,end_date,revenue"),
                ("合并资产负债表", "balancesheet", "ts_code,end_date,total_assets"),
                ("现金流量表", "cashflow", "ts_code,end_date,n_cashflow_act"),
            ]:
                df = self._safe_call(api, ts_code=ts_code, fields=fields)
                wc.check_missing_data(label, df)
                # YoY checks for key metrics
                if not df.empty:
                    col = fields.split(",")[-1]
                    if col in df.columns:
                        vals = df[col].tolist()
                        wc.check_yoy_change(label, col, vals)

            # Check revenue and net income YoY from income statement
            inc_df = self._safe_call("income", ts_code=ts_code,
                                     fields="ts_code,end_date,revenue,n_income_attr_p")
            if not inc_df.empty:
                for col in ["revenue", "n_income_attr_p"]:
                    if col in inc_df.columns:
                        wc.check_yoy_change("合并利润表", col, inc_df[col].tolist())

            # Audit risk check
            audit_df = self._safe_call("fina_audit", ts_code=ts_code,
                                       fields="ts_code,end_date,audit_agency,audit_opinion")
            if not audit_df.empty and "audit_opinion" in audit_df.columns:
                wc.check_audit_risk(str(audit_df.iloc[0].get("audit_opinion", "")))

            # Balance sheet risk checks (goodwill, debt ratio)
            bs_df = self._safe_call("balancesheet", ts_code=ts_code,
                                    fields="ts_code,end_date,goodwill,total_assets,total_liab")
            if not bs_df.empty:
                latest = bs_df.iloc[0]
                gw = latest.get("goodwill", 0) or 0
                ta = latest.get("total_assets", 0) or 0
                tl = latest.get("total_liab", 0) or 0
                wc.check_goodwill_ratio(float(gw), float(ta))
                wc.check_debt_ratio(float(tl), float(ta))
        except Exception:
            pass  # warnings are best-effort; don't block assembly

        # Build §13 with two sub-sections
        lines.append(format_header(2, "13. 风险警示"))
        lines.append("")
        lines.append("### 13.1 脚本自动检测")
        lines.append("")
        if wc.warnings:
            high = [w for w in wc.warnings if w["severity"] == "高"]
            medium = [w for w in wc.warnings if w["severity"] == "中"]
            low = [w for w in wc.warnings if w["severity"] == "低"]
            for sev_label, items in [("高风险", high), ("中风险", medium), ("低风险", low)]:
                if items:
                    lines.append(f"**{sev_label}:**")
                    for w in items:
                        lines.append(f"- [{w['type']}] {w['message']}")
                    lines.append("")
        else:
            lines.append("未检测到异常。")
            lines.append("")
        lines.append("### 13.2 Agent WebSearch 补充")
        lines.append("")
        lines.append("*[§13.2 待Agent WebSearch补充]*")
        lines.append("")

        lines.append("---")
        lines.append(f"*共 {completed}/{len(sections)} 个数据板块成功获取*")

        return "\n".join(lines)


class WarningsCollector:
    """Auto-detect anomalies during data collection (Feature #30)."""

    def __init__(self):
        self.warnings = []

    def check_missing_data(self, section_name: str, df: pd.DataFrame):
        """Warn if a data section returned empty."""
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            self.warnings.append({
                "type": "DATA_MISSING",
                "severity": "中",
                "message": f"{section_name} 数据缺失",
            })

    def check_yoy_change(self, section_name: str, field_name: str,
                         values: list, threshold: float = 3.0):
        """Warn if year-over-year change exceeds threshold (e.g., 300%)."""
        for i in range(len(values) - 1):
            curr, prev = values[i], values[i + 1]
            if prev and prev != 0 and curr is not None:
                try:
                    change = abs(float(curr) / float(prev) - 1)
                    if change > threshold:
                        self.warnings.append({
                            "type": "YOY_ANOMALY",
                            "severity": "高",
                            "message": f"{section_name}/{field_name}: "
                                       f"同比变化 {change*100:.0f}% 超过 {threshold*100:.0f}% 阈值",
                        })
                except (ValueError, ZeroDivisionError):
                    pass

    def check_audit_risk(self, audit_opinion: str):
        """Warn if audit opinion is not clean."""
        if audit_opinion and audit_opinion not in ("标准无保留意见", "—", ""):
            self.warnings.append({
                "type": "AUDIT_RISK",
                "severity": "高",
                "message": f"审计意见非标准: {audit_opinion}",
            })

    def check_goodwill_ratio(self, goodwill: float, total_assets: float):
        """Warn if goodwill/total_assets > 20%."""
        if goodwill and total_assets and total_assets > 0:
            ratio = float(goodwill) / float(total_assets)
            if ratio > 0.20:
                self.warnings.append({
                    "type": "GOODWILL_RISK",
                    "severity": "高",
                    "message": f"商誉占总资产比例 {ratio*100:.1f}% 超过 20%",
                })

    def check_debt_ratio(self, total_liab: float, total_assets: float):
        """Warn if debt ratio > 70%."""
        if total_liab and total_assets and total_assets > 0:
            ratio = float(total_liab) / float(total_assets)
            if ratio > 0.70:
                self.warnings.append({
                    "type": "LEVERAGE_RISK",
                    "severity": "中",
                    "message": f"资产负债率 {ratio*100:.1f}% 超过 70%",
                })

    def format_warnings(self) -> str:
        """Format all collected warnings as section 13 markdown."""
        lines = [format_header(2, "13. 风险警示 (脚本自动生成)"), ""]

        if not self.warnings:
            lines.append("未检测到异常。")
            return "\n".join(lines)

        # Group by severity
        high = [w for w in self.warnings if w["severity"] == "高"]
        medium = [w for w in self.warnings if w["severity"] == "中"]
        low = [w for w in self.warnings if w["severity"] == "低"]

        if high:
            lines.append("**高风险:**")
            for w in high:
                lines.append(f"- [{w['type']}] {w['message']}")
            lines.append("")
        if medium:
            lines.append("**中风险:**")
            for w in medium:
                lines.append(f"- [{w['type']}] {w['message']}")
            lines.append("")
        if low:
            lines.append("**低风险:**")
            for w in low:
                lines.append(f"- [{w['type']}] {w['message']}")
            lines.append("")

        lines.append(f"*共 {len(self.warnings)} 条自动警示*")
        return "\n".join(lines)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Collect financial data from Tushare Pro API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --code 600887.SH
  %(prog)s --code 600887 --output output/data_pack_market.md
  %(prog)s --code 00700.HK --extra-fields balancesheet.defer_tax_assets
        """,
    )
    parser.add_argument(
        "--code",
        required=True,
        help="Stock code (e.g., 600887.SH, 000858.SZ, 00700.HK, or plain digits)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Tushare API token (defaults to TUSHARE_TOKEN env var)",
    )
    parser.add_argument(
        "--output",
        default="output/data_pack_market.md",
        help="Output file path (default: output/data_pack_market.md)",
    )
    parser.add_argument(
        "--extra-fields",
        nargs="*",
        help="Additional fields to fetch (format: endpoint.field_name)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print parsed arguments and exit without calling API",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Validate and normalize stock code
    try:
        ts_code = validate_stock_code(args.code)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print("=== Dry Run ===")
        print(f"  Stock code: {args.code} -> {ts_code}")
        print(f"  Token: {'provided via --token' if args.token else 'from TUSHARE_TOKEN env'}")
        print(f"  Output: {args.output}")
        print(f"  Extra fields: {args.extra_fields or 'none'}")
        return

    # Get token
    token = args.token or get_token()
    client = TushareClient(token)

    print(f"Collecting data for {ts_code}...")
    data_pack = client.assemble_data_pack(ts_code)

    # Handle extra fields
    if args.extra_fields:
        extra_lines = ["\n", format_header(2, "附加字段"), ""]
        for field_spec in args.extra_fields:
            parts = field_spec.split(".", 1)
            if len(parts) != 2:
                extra_lines.append(f"- 无效字段格式: {field_spec} (应为 endpoint.field_name)")
                continue
            endpoint, field_name = parts
            try:
                df = client._safe_call(endpoint, ts_code=ts_code, fields=f"ts_code,end_date,{field_name}")
                if not df.empty:
                    extra_lines.append(f"**{endpoint}.{field_name}**:")
                    extra_lines.append(df.to_markdown(index=False))
                    extra_lines.append("")
                else:
                    extra_lines.append(f"- {endpoint}.{field_name}: 无数据")
            except Exception as e:
                extra_lines.append(f"- {endpoint}.{field_name}: 获取失败 ({e})")
        data_pack += "\n".join(extra_lines)

    # Write output
    import os
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(data_pack)
    print(f"Output written to {args.output}")
    print(f"File size: {os.path.getsize(args.output):,} bytes")


if __name__ == "__main__":
    main()
