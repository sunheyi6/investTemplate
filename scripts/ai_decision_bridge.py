# -*- coding: utf-8 -*-
"""
AI 决策桥接脚本 V1.0

功能：
1. 读取 ai_decision_request.json
2. 构建标准化 prompt（读取模板 + 填充数据）
3. 调用 LLM API（OpenAI / Claude / DeepSeek 等）
4. 解析 JSON 响应
5. 风控硬约束拦截
6. 输出 ai_decision_response.json
7. 记录 AI 决策日志

环境变量：
    AI_PROVIDER      - 可选: openai, claude, deepseek (默认 openai)
    AI_API_KEY       - API Key
    AI_API_BASE      - 自定义 API Base URL（可选）
    AI_MODEL         - 模型名称（默认 gpt-4o）
    AI_MAX_TOKENS    - 最大 token（默认 4000）
    AI_TEMPERATURE   - 温度（默认 0.1，低温度确保决策一致性）

使用方式：
    python scripts/ai_decision_bridge.py [--request-file PATH] [--response-file PATH]
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# 尝试导入可选依赖
try:
    import urllib.request
    URLLIB_AVAILABLE = True
except ImportError:
    URLLIB_AVAILABLE = False

ROOT = Path(__file__).resolve().parents[1]
PROMPT_TEMPLATE = ROOT / "prompts" / "ai_trading_decision.md"
REQUEST_FILE = ROOT / "decision-tracking" / "ai_decision_request.json"
RESPONSE_FILE = ROOT / "decision-tracking" / "ai_decision_response.json"
AI_LOG_FILE = ROOT / "decision-tracking" / "AI决策记录.md"

# 风控硬约束
INITIAL_CAPITAL = 500_000.0
MIN_CASH_RESERVE_PCT = 0.10
MAX_POSITION_PCT_BEAR = 0.10
MAX_POSITION_PCT_BULL = 0.15
MAX_PE_SURFACE = 15.0
VHSI_HALT_NEW_BUY = 32.0


class LLMClient:
    """通用 LLM API 客户端"""

    def __init__(self):
        self.provider = os.getenv("AI_PROVIDER", "openai").lower().strip()
        self.api_key = os.getenv("AI_API_KEY", "").strip()
        self.api_base = os.getenv("AI_API_BASE", "").strip()
        self.model = os.getenv("AI_MODEL", "gpt-4o").strip()
        self.max_tokens = int(os.getenv("AI_MAX_TOKENS", "4000"))
        self.temperature = float(os.getenv("AI_TEMPERATURE", "0.1"))

        if not self.api_key:
            raise RuntimeError("环境变量 AI_API_KEY 未设置")

        # 设置默认 API base
        if not self.api_base:
            if self.provider == "openai":
                self.api_base = "https://api.openai.com/v1"
            elif self.provider == "claude":
                self.api_base = "https://api.anthropic.com/v1"
            elif self.provider == "deepseek":
                self.api_base = "https://api.deepseek.com/v1"
            elif self.provider == "moonshot":
                self.api_base = "https://api.moonshot.cn/v1"
            else:
                raise RuntimeError(f"不支持的 AI_PROVIDER: {self.provider}")

    def _call_openai(self, prompt: str) -> str:
        import urllib.request
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是一位遵循龟龟投资理论的防御型价值投资者。请严格按指令输出JSON格式决策。"},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]

    def _call_claude(self, prompt: str) -> str:
        import urllib.request
        url = f"{self.api_base}/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": "你是一位遵循龟龟投资理论的防御型价值投资者。请严格按指令输出JSON格式决策。",
            "messages": [{"role": "user", "content": prompt}],
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["content"][0]["text"]

    def _call_deepseek(self, prompt: str) -> str:
        import urllib.request
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是一位遵循龟龟投资理论的防御型价值投资者。请严格按指令输出JSON格式决策。"},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]

    def call(self, prompt: str) -> str:
        if self.provider == "openai":
            return self._call_openai(prompt)
        elif self.provider == "claude":
            return self._call_claude(prompt)
        elif self.provider in ("deepseek", "moonshot"):
            return self._call_openai(prompt)
        else:
            raise RuntimeError(f"不支持的 provider: {self.provider}")


def load_prompt_template() -> str:
    if not PROMPT_TEMPLATE.exists():
        raise FileNotFoundError(f"Prompt 模板不存在: {PROMPT_TEMPLATE}")
    return PROMPT_TEMPLATE.read_text(encoding="utf-8")


def build_prompt(request: Dict[str, Any]) -> str:
    template = load_prompt_template()
    subject = request.get("subject", {})
    context = request.get("context", {})
    portfolio = context.get("portfolio_state", {})

    # 计算当前仓位占比
    ticker = subject.get("ticker", "")
    positions = portfolio.get("positions", {})
    pos_info = positions.get(ticker, {})
    shares = int(pos_info.get("shares", 0))
    avg_cost = float(pos_info.get("avg_cost", 0))
    sell_trigger = pos_info.get("sell_trigger", 0)
    target_buy = pos_info.get("target_buy")
    lot_size = int(pos_info.get("lot_size", 1000))
    realized_pnl = float(pos_info.get("realized_pnl", 0))

    net_value = portfolio.get("net_value", INITIAL_CAPITAL)
    current_mv = shares * float(subject.get("current_price", 0))
    current_weight_pct = round((current_mv / net_value) * 100, 4) if net_value > 0 else 0.0

    # 填充模板
    replacements = {
        "{{date}}": request.get("date", ""),
        "{{trigger_type}}": request.get("trigger_type", ""),
        "{{vhsi}}": str(context.get("vhsi", "N/A")),
        "{{market_sentiment}}": context.get("market_sentiment", "未知"),
        "{{name}}": subject.get("name", ""),
        "{{code}}": subject.get("code", ""),
        "{{ticker}}": ticker,
        "{{current_price}}": str(subject.get("current_price", 0)),
        "{{trigger_reason}}": subject.get("trigger_reason", ""),
        "{{shares}}": str(shares),
        "{{avg_cost}}": str(avg_cost),
        "{{sell_trigger}}": str(sell_trigger) if sell_trigger else "未设置",
        "{{target_buy}}": str(target_buy) if target_buy else "未设置",
        "{{lot_size}}": str(lot_size),
        "{{realized_pnl}}": str(realized_pnl),
        "{{initial_capital}}": str(INITIAL_CAPITAL),
        "{{cash}}": str(portfolio.get("cash", 0)),
        "{{net_value}}": str(net_value),
        "{{total_return_pct}}": str(portfolio.get("total_return_pct", 0)),
        "{{current_weight_pct}}": str(current_weight_pct),
        "{{subject_data_json}}": json.dumps(subject, ensure_ascii=False, indent=2),
        "{{portfolio_context_json}}": json.dumps(context, ensure_ascii=False, indent=2),
    }

    for key, val in replacements.items():
        template = template.replace(key, val)

    return template


def parse_llm_response(raw: str) -> Dict[str, Any]:
    """从 LLM 响应中提取 JSON"""
    # 尝试直接解析
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 尝试从 markdown code block 中提取
    match = re.search(r"```(?:json)?\s*\n(.*?)\n```", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试从文本中找第一个 { ... }
    match = re.search(r"(\{.*\})", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    raise ValueError("无法从 LLM 响应中解析 JSON")


def hard_constraint_check(decision: Dict[str, Any], request: Dict[str, Any]) -> tuple[bool, list[str]]:
    """
    风控硬约束拦截。
    返回: (是否通过, [警告信息列表])
    """
    warnings = []
    action = decision.get("decision", "HOLD")
    shares = int(decision.get("shares", 0))
    price = float(decision.get("price", 0))

    context = request.get("context", {})
    portfolio = context.get("portfolio_state", {})
    cash = float(portfolio.get("cash", 0))
    net_value = float(portfolio.get("net_value", INITIAL_CAPITAL))

    subject = request.get("subject", {})
    ticker = subject.get("ticker", "")
    positions = portfolio.get("positions", {})
    pos_info = positions.get(ticker, {})
    current_shares = int(pos_info.get("shares", 0))
    current_price = float(subject.get("current_price", 0))
    current_mv = current_shares * current_price
    current_weight = current_mv / net_value if net_value > 0 else 0

    # 约束1: 现金储备不低于10%
    if action in ("BUY_OPEN", "BUY_ADD"):
        amount = shares * price
        if cash - amount < INITIAL_CAPITAL * MIN_CASH_RESERVE_PCT:
            warnings.append(
                f"[风控拦截] 买入后现金储备不足10%: 买入后现金={(cash-amount):.2f}"
            )

    # 约束2: 仓位上限
    if action in ("BUY_OPEN", "BUY_ADD"):
        new_mv = current_mv + shares * price
        new_weight = new_mv / net_value if net_value > 0 else 0
        if new_weight > MAX_POSITION_PCT_BULL:
            warnings.append(
                f"[风控拦截] 买入后仓位超限: 预计={new_weight*100:.2f}% > 上限={MAX_POSITION_PCT_BULL*100:.2f}%"
            )

    # 约束3: VHSI > 32 禁止新建仓
    vhsi = float(context.get("vhsi", 0))
    if action == "BUY_OPEN" and vhsi > VHSI_HALT_NEW_BUY:
        warnings.append(
            f"[风控拦截] VHSI={vhsi:.2f} > {VHSI_HALT_NEW_BUY}, 禁止新建仓"
        )

    # 约束4: PE 硬约束
    pe_surface = decision.get("valuation_pe_surface")
    if pe_surface is not None:
        try:
            pe_surface = float(pe_surface)
            if action in ("BUY_OPEN", "BUY_ADD") and pe_surface > MAX_PE_SURFACE:
                warnings.append(
                    f"[风控拦截] 表面PE={pe_surface:.2f} > {MAX_PE_SURFACE}, 禁止买入"
                )
        except (ValueError, TypeError):
            pass

    passed = len(warnings) == 0
    return passed, warnings


def apply_hard_constraints(decision: Dict[str, Any], warnings: list[str]) -> Dict[str, Any]:
    """若风控不通过，强制改为 HOLD"""
    if warnings:
        decision["decision"] = "HOLD"
        decision["shares"] = 0
        decision["risk_checks_passed"] = False
        decision["risk_warnings"] = warnings + decision.get("risk_warnings", [])
    else:
        decision["risk_checks_passed"] = True
    return decision


def append_ai_log(request: Dict[str, Any], decision: Dict[str, Any], raw_response: str, warnings: list[str]):
    """追加 AI 决策日志"""
    date = request.get("date", "")
    ticker = request.get("subject", {}).get("ticker", "")
    name = request.get("subject", {}).get("name", "")
    action = decision.get("decision", "HOLD")
    reason = decision.get("reason", "")
    confidence = decision.get("confidence", "N/A")

    lines = [
        f"\n## {date} {name}({ticker})",
        f"",
        f"**触发类型**: {request.get('trigger_type', '')}",
        f"**触发原因**: {request.get('subject', {}).get('trigger_reason', '')}",
        f"**当前价格**: {request.get('subject', {}).get('current_price', '')}",
        f"**AI决策**: {action}",
        f"**置信度**: {confidence}",
        f"**框架类型**: {decision.get('framework_type', 'N/A')}",
        f"**商业模式评级**: {decision.get('business_model_rating', 'N/A')}",
        f"**表面PE**: {decision.get('valuation_pe_surface', 'N/A')}",
        f"**TTM PE**: {decision.get('valuation_pe_ttm', 'N/A')}",
        f"**净现金/市值**: {decision.get('cash_to_mkt_pct', 'N/A')}%",
        f"**股息率**: {decision.get('dividend_yield_pct', 'N/A')}%",
        f"",
        f"**决策理由**: {reason}",
        f"",
    ]

    if warnings:
        lines.append("**风控拦截**:")
        for w in warnings:
            lines.append(f"- ⚠️ {w}")
        lines.append("")

    ai_warnings = decision.get("risk_warnings", [])
    if ai_warnings:
        lines.append("**AI识别的风险**:")
        for w in ai_warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append(f"**原始响应摘要**:\n```json\n{raw_response[:500]}...\n```\n")

    log_text = "\n".join(lines)

    if AI_LOG_FILE.exists():
        with open(AI_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_text)
    else:
        header = "# AI 投资决策记录\n\n> 自动生成的 AI 决策日志\n"
        with open(AI_LOG_FILE, "w", encoding="utf-8") as f:
            f.write(header + log_text)


def run() -> int:
    print("=" * 60)
    print("[START] AI 决策桥接 V1.0")
    print("=" * 60)

    # 读取请求
    if not REQUEST_FILE.exists():
        print("[ERROR] 请求文件不存在: %s" % REQUEST_FILE)
        return 1

    request = json.loads(REQUEST_FILE.read_text(encoding="utf-8"))
    print("[OK] 读取请求: %s - %s" % (request.get("date"), request.get("subject", {}).get("ticker")))

    # 构建 prompt
    try:
        prompt = build_prompt(request)
    except Exception as e:
        print("[ERROR] 构建 prompt 失败: %s" % e)
        return 1
    print("[OK] Prompt 构建完成")

    # 调用 LLM
    try:
        client = LLMClient()
        print("[OK] LLM 客户端初始化: provider=%s, model=%s" % (client.provider, client.model))
    except RuntimeError as e:
        print("[ERROR] %s" % e)
        print("[HINT] 请设置环境变量: AI_API_KEY=your_key [AI_PROVIDER=openai|claude|deepseek]")
        return 1

    print("[STEP] 调用 LLM API...")
    try:
        raw_response = client.call(prompt)
    except Exception as e:
        print("[ERROR] LLM API 调用失败: %s" % e)
        return 1
    print("[OK] LLM 响应接收完成")

    # 解析 JSON
    try:
        decision = parse_llm_response(raw_response)
    except ValueError as e:
        print("[ERROR] 解析响应失败: %s" % e)
        print("[DEBUG] 原始响应前500字:\n%s" % raw_response[:500])
        return 1
    print("[OK] JSON 解析成功")

    # 风控硬约束检查
    passed, warnings = hard_constraint_check(decision, request)
    if not passed:
        print("[WARN] 风控拦截触发，强制改为 HOLD:")
        for w in warnings:
            print("   - %s" % w)
    else:
        print("[OK] 风控硬约束检查通过")

    # 应用风控约束
    decision = apply_hard_constraints(decision, warnings)

    # 写入响应文件
    RESPONSE_FILE.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[OK] 响应已写入: %s" % RESPONSE_FILE)

    # 追加日志
    append_ai_log(request, decision, raw_response, warnings)
    print("[OK] 日志已追加: %s" % AI_LOG_FILE)

    print()
    print("=" * 60)
    print("[DONE] AI 决策: %s -> %s" % (request.get("subject", {}).get("ticker"), decision.get("decision")))
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(run())
