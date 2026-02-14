"""
2026年运报告 - 19路全并行调用方案

架构: 所有调用同时发出，无依赖关系
  - 基础+总评 (foundation)
  - 事业运   (career)
  - 财运     (wealth)
  - 感情运   (love)
  - 健康运   (health)
  - 学业+人际 (study_relations)
  - 开运指南  (lucky)
  - 月运×12  (monthly_1 ~ monthly_12)

总调用: 19次，全部并行
预计耗时: max(所有调用) ≈ 15-30秒
"""

import asyncio
import json
import time
import aiohttp
from openai import AsyncOpenAI
from typing import AsyncGenerator, Dict, Any, Callable

# ============================================================
# 配置
# ============================================================

KEY_DICT = {
    "deepseek": {
        "api_key": "sk-4d7e22ff18b0495498e78dd7730af602",
        "base_url": "https://api.deepseek.com/v1"
    },
    "piqixiao": {
        "api_key": "sk-xxx",
        "base_url": "https://api.flyupai.com"
    },
    "xiangliang": {
        "api_key": "sk-bfnQrn7oIKShpFXJysJNEb91qXh99iEuSr7WdL8Z2iqYjHJ9",
        "base_url": "https://api.vectorengine.ai/v1"
    },
}

MODEL_DICT = {
    "deepseek": "deepseek-chat",
    "claude": "claude-sonnet-4-5-20250929"
}


# ============================================================
# 通用 Prompt 片段
# ============================================================

BAZI_ANALYSIS_GUIDE = """
## 八字分析指引（请先完成以下分析再输出结果）

你需要先在内部完成以下分析步骤（不需要输出这些中间步骤，只需要输出最终 JSON）：

1. 解析四柱天干地支，确定日主及其阴阳五行
2. 分析命局五行分布，判断偏旺偏弱
3. 确定日主强弱（身强/身弱/从格等）
4. 推导十神关系，确定用神和忌神
5. 分析四柱之间的干支关系（合冲刑害破）
6. 分析流年丙午与命局各柱的干支互动
7. 分析大运与流年的干支互动
8. 综合以上分析得出结论

### 干支关系参考
- 天干五合：甲己合、乙庚合、丙辛合、丁壬合、戊癸合
- 地支六合：子丑、寅亥、卯戌、辰酉、巳申、午未
- 地支三合：申子辰水、亥卯未木、寅午戌火、巳酉丑金
- 地支三会：寅卯辰木、巳午未火、申酉戌金、亥子丑水
- 地支六冲：子午、丑未、寅申、卯酉、辰戌、巳亥
- 地支六害：子未、丑午、寅巳、卯辰、申亥、酉戌
- 地支三刑：寅巳申、丑戌未、子卯刑、辰辰/午午/酉酉/亥亥自刑
- 地支相破：子酉、丑辰、寅亥、卯午、巳申、未戌

### 2026丙午年各月干支
正月庚寅、二月辛卯、三月壬辰、四月癸巳、五月甲午、六月乙未、七月丙申、八月丁酉、九月戊戌、十月己亥、十一月庚子、十二月辛丑
"""

COMMON_OUTPUT_RULES = """
## 输出规则
1. 所有含分析内容的字段必须使用 { "text": "通俗版", "bazi_explanation": "命理版" } 配对结构
2. "text" 面向普通用户：通俗、温暖、绝对不含任何命理术语（天干、地支、十神、五行生克等词汇都不能出现）
3. "bazi_explanation" 面向懂命理的用户：必须包含具体的干支、十神、五行术语和推理过程
4. 所有 score 为 1-100 整数，根据命理分析合理赋值
5. 全部简体中文
6. 输出纯 JSON，不要任何其他文字、不要 markdown 代码块包裹
"""


# ============================================================
# 10个 Section 的 System Prompt（非月运）
# ============================================================

PROMPT_FOUNDATION = """
你是一位精通中国传统命理学的资深八字命理分析师。
请根据用户提供的八字、性别和当前大运，完成【八字基础解析】和【2026丙午年年度总评】。

""" + BAZI_ANALYSIS_GUIDE + COMMON_OUTPUT_RULES + """

## 输出 JSON 结构

{
  "section": "foundation",
  "report_meta": {
    "report_title": "2026丙午年八字运势详批",
    "report_year": "2026",
    "year_stem_branch": "丙午",
    "year_element": "火",
    "year_nayin": "天河水",
    "version": "2.0"
  },
  "user_input": {
    "bazi_raw": "原始八字字符串",
    "gender": "男/女",
    "current_dayun": "当前大运干支"
  },
  "bazi_chart": {
    "four_pillars": {
      "year":  { "stem": "", "branch": "", "stem_element": "", "branch_element": "", "nayin": "", "hidden_stems": [] },
      "month": { "stem": "", "branch": "", "stem_element": "", "branch_element": "", "nayin": "", "hidden_stems": [] },
      "day":   { "stem": "", "branch": "", "stem_element": "", "branch_element": "", "nayin": "", "hidden_stems": [] },
      "hour":  { "stem": "", "branch": "", "stem_element": "", "branch_element": "", "nayin": "", "hidden_stems": [] }
    },
    "day_master": {
      "character": "", "element": "", "yin_yang": "", "strength": "",
      "strength_analysis": { "text": "", "bazi_explanation": "" }
    },
    "element_distribution": {
      "wood": { "count": 0, "status": "" }, "fire": { "count": 0, "status": "" },
      "earth": { "count": 0, "status": "" }, "metal": { "count": 0, "status": "" },
      "water": { "count": 0, "status": "" }
    },
    "ten_gods": {
      "year_stem": { "god": "", "relation": "" },
      "month_stem": { "god": "", "relation": "" },
      "hour_stem": { "god": "", "relation": "" }
    },
    "useful_god": { "text": "", "bazi_explanation": "" },
    "unfavorable_god": { "text": "", "bazi_explanation": "" }
  },
  "interactions_analysis": {
    "natal_interactions": {
      "text": "", "bazi_explanation": "",
      "details": [
        { "type": "", "elements": [], "pillars": [], "text": "", "bazi_explanation": "" }
      ]
    },
    "flow_year_interactions": {
      "text": "", "bazi_explanation": "",
      "details": [
        { "flow_element": "", "natal_element": "", "natal_pillar": "", "type": "", "text": "", "bazi_explanation": "" }
      ]
    },
    "dayun_flow_year_interaction": {
      "dayun": "", "flow_year": "丙午", "text": "", "bazi_explanation": ""
    }
  },
  "yearly_fortune_overall": {
    "score": 75,
    "level": "上吉/吉/中吉/平/中凶/凶/大凶",
    "keyword": "年度主题词",
    "summary": { "text": "300字以内年度总评", "bazi_explanation": "" },
    "highlights": [ { "text": "", "bazi_explanation": "" } ],
    "warnings": [ { "text": "", "bazi_explanation": "" } ]
  }
}
"""

PROMPT_CAREER = """
你是一位精通中国传统命理学的资深八字命理分析师。
请根据用户提供的八字、性别和当前大运，专门分析【2026丙午年事业运势】。

""" + BAZI_ANALYSIS_GUIDE + COMMON_OUTPUT_RULES + """

## 输出 JSON 结构

{
  "section": "career",
  "career": {
    "score": 0,
    "summary": { "text": "事业运通俗分析300字以内", "bazi_explanation": "" },
    "opportunities": [ { "text": "", "bazi_explanation": "" } ],
    "risks": [ { "text": "", "bazi_explanation": "" } ],
    "advice": { "text": "", "bazi_explanation": "" },
    "noble_person": { "text": "贵人特征通俗描述", "bazi_explanation": "" }
  }
}
"""

PROMPT_WEALTH = """
你是一位精通中国传统命理学的资深八字命理分析师。
请根据用户提供的八字、性别和当前大运，专门分析【2026丙午年财运运势】。

""" + BAZI_ANALYSIS_GUIDE + COMMON_OUTPUT_RULES + """

## 输出 JSON 结构

{
  "section": "wealth",
  "wealth": {
    "score": 0,
    "summary": { "text": "财运通俗分析300字以内", "bazi_explanation": "" },
    "regular_income": { "trend": "上升/平稳/下降", "text": "", "bazi_explanation": "" },
    "windfall": { "trend": "上升/平稳/下降", "text": "", "bazi_explanation": "" },
    "loss_risk": { "level": "高/中/低", "text": "", "bazi_explanation": "" },
    "advice": { "text": "", "bazi_explanation": "" }
  }
}
"""

PROMPT_LOVE = """
你是一位精通中国传统命理学的资深八字命理分析师。
请根据用户提供的八字、性别和当前大运，专门分析【2026丙午年感情运势】。

""" + BAZI_ANALYSIS_GUIDE + COMMON_OUTPUT_RULES + """

## 输出 JSON 结构

{
  "section": "love",
  "love": {
    "score": 0,
    "summary": { "text": "感情运通俗分析300字以内", "bazi_explanation": "" },
    "single_advice": { "text": "", "bazi_explanation": "" },
    "relationship_advice": { "text": "", "bazi_explanation": "" },
    "peach_blossom": {
      "active": true, "direction": "", "months": [],
      "text": "", "bazi_explanation": ""
    }
  }
}
"""

PROMPT_HEALTH = """
你是一位精通中国传统命理学的资深八字命理分析师。
请根据用户提供的八字、性别和当前大运，专门分析【2026丙午年健康运势】。

""" + BAZI_ANALYSIS_GUIDE + COMMON_OUTPUT_RULES + """

## 输出 JSON 结构

{
  "section": "health",
  "health": {
    "score": 0,
    "summary": { "text": "健康运通俗分析300字以内", "bazi_explanation": "" },
    "risk_areas": [ { "text": "", "bazi_explanation": "" } ],
    "advice": { "text": "", "bazi_explanation": "" },
    "caution_months": []
  }
}
"""

PROMPT_STUDY_RELATIONS = """
你是一位精通中国传统命理学的资深八字命理分析师。
请根据用户提供的八字、性别和当前大运，专门分析【2026丙午年学业运与人际关系运】。

""" + BAZI_ANALYSIS_GUIDE + COMMON_OUTPUT_RULES + """

## 输出 JSON 结构

{
  "section": "study_relations",
  "study": {
    "score": 0,
    "summary": { "text": "学业运通俗分析300字以内", "bazi_explanation": "" },
    "advice": { "text": "", "bazi_explanation": "" }
  },
  "relationships": {
    "score": 0,
    "summary": { "text": "人际关系通俗分析300字以内", "bazi_explanation": "" },
    "noble_direction": "",
    "villain_warning": { "text": "", "bazi_explanation": "" },
    "advice": { "text": "", "bazi_explanation": "" }
  }
}
"""

PROMPT_LUCKY = """
你是一位精通中国传统命理学的资深八字命理分析师。
请根据用户提供的八字、性别和当前大运，生成【2026丙午年开运指南、化解建议与年度策略】。

""" + BAZI_ANALYSIS_GUIDE + COMMON_OUTPUT_RULES + """

## 输出 JSON 结构

{
  "section": "lucky",
  "lucky_guide": {
    "colors": { "items": [], "text": "", "bazi_explanation": "" },
    "numbers": { "items": [], "text": "", "bazi_explanation": "" },
    "directions": { "items": [], "text": "", "bazi_explanation": "" },
    "industries": { "items": [], "text": "", "bazi_explanation": "" },
    "zodiac_allies": [], "zodiac_conflicts": [],
    "favorable_months": [], "unfavorable_months": []
  },
  "remedies": [
    { "issue": { "text": "", "bazi_explanation": "" }, "method": { "text": "", "bazi_explanation": "" } }
  ],
  "annual_advice": {
    "overall_strategy": { "text": "120字以内", "bazi_explanation": "" },
    "best_months": [ { "months": [], "text": "", "bazi_explanation": "" } ],
    "cautious_months": [ { "months": [], "text": "", "bazi_explanation": "" } ],
    "final_words": "80字以内的寄语祝福"
  },
  "disclaimer": "本报告基于中国传统命理学理论生成，仅供参考娱乐。命理分析不能替代专业的医疗、法律、财务建议。人生际遇受多种因素影响，命由天定，运由己造，积极的心态和努力才是改变命运的关键。"
}
"""


# ============================================================
# 12个月运 Prompt - 每月单独调用
# ============================================================

MONTH_STEM_BRANCH = {
    1: "庚寅", 2: "辛卯", 3: "壬辰", 4: "癸巳",
    5: "甲午", 6: "乙未", 7: "丙申", 8: "丁酉",
    9: "戊戌", 10: "己亥", 11: "庚子", 12: "辛丑"
}

LUNAR_MONTH = {
    1: "正月", 2: "二月", 3: "三月", 4: "四月",
    5: "五月", 6: "六月", 7: "七月", 8: "八月",
    9: "九月", 10: "十月", 11: "十一月", 12: "十二月"
}


def make_single_month_prompt(m: int) -> str:
    """生成单月月运 prompt"""
    sb = MONTH_STEM_BRANCH[m]
    ln = LUNAR_MONTH[m]
    return f"""
你是一位精通中国传统命理学的资深八字命理分析师。
请根据用户提供的八字、性别和当前大运，专门分析【2026丙午年{m}月（农历{ln}，月柱{sb}）的月度运势】。

重点分析该月月柱{sb}与命局四柱、流年丙午、当前大运之间的干支互动关系。

{BAZI_ANALYSIS_GUIDE}
{COMMON_OUTPUT_RULES}

## 输出 JSON 结构

{{
  "section": "monthly_{m}",
  "month_number": {m},
  "lunar_month": "{ln}",
  "stem_branch": "{sb}",
  "solar_range": "公历起止日期（请根据2026年节气推算）",
  "score": 0,
  "keyword": "月度主题词（2-4字）",
  "summary": {{
    "text": "月度运势通俗概述150字以内",
    "bazi_explanation": "该月干支与命局及流年的互动分析"
  }},
  "career": {{ "text": "事业方面50字以内", "bazi_explanation": "" }},
  "wealth": {{ "text": "财运方面50字以内", "bazi_explanation": "" }},
  "love":   {{ "text": "感情方面50字以内", "bazi_explanation": "" }},
  "health": {{ "text": "健康方面50字以内", "bazi_explanation": "" }},
  "do": ["宜做的事1", "宜做的事2", "宜做的事3"],
  "dont": ["忌做的事1", "忌做的事2"]
}}

只输出这1个月的数据，不要输出其他月份。
"""


# ============================================================
# 所有 Section 配置 (7 + 12 = 19)
# ============================================================

SECTIONS = {
    # === 7个主体板块 ===
    "foundation":     {"prompt": PROMPT_FOUNDATION,       "max_tokens": 6000},
    "career":         {"prompt": PROMPT_CAREER,            "max_tokens": 3500},
    "wealth":         {"prompt": PROMPT_WEALTH,            "max_tokens": 3500},
    "love":           {"prompt": PROMPT_LOVE,              "max_tokens": 3500},
    "health":         {"prompt": PROMPT_HEALTH,            "max_tokens": 3000},
    "study_relations": {"prompt": PROMPT_STUDY_RELATIONS,  "max_tokens": 3500},
    "lucky":          {"prompt": PROMPT_LUCKY,             "max_tokens": 4000},
}

# === 12个月运，每月独立 ===
for m in range(1, 13):
    SECTIONS[f"monthly_{m}"] = {
        "prompt": make_single_month_prompt(m),
        "max_tokens": 1500,
    }


# ============================================================
# AI 调用
# ============================================================

async def call_ai_stream(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 4000,
    ai_type: str = "deepseek",
    brand: str = "deepseek"
) -> AsyncGenerator[str, None]:
    """通用流式 AI 调用（OpenAI 兼容接口）"""
    client = AsyncOpenAI(
        api_key=KEY_DICT[brand]['api_key'],
        base_url=KEY_DICT[brand]['base_url']
    )
    try:
        stream = await client.chat.completions.create(
            model=MODEL_DICT[ai_type],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
            stream=True,
        )
        async for chunk in stream:
            content = chunk.choices[0].delta.content if chunk.choices else None
            if content:
                yield content
    except Exception as e:
        print(f"[ERROR] API调用异常: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


async def call_ai_full(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 4000,
    ai_type: str = "deepseek",
    brand: str = "deepseek"
) -> str:
    """非流式，返回完整结果"""
    buf = ""
    async for c in call_ai_stream(system_prompt, user_message, max_tokens, ai_type, brand):
        buf += c
    return buf


def clean_json_str(raw: str) -> str:
    """清理 AI 返回的可能带 markdown 包裹的 JSON"""
    s = raw.strip()
    if s.startswith("```json"):
        s = s[7:]
    elif s.startswith("```"):
        s = s[3:]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()


# ============================================================
# 核心：生成单个 Section
# ============================================================

async def generate_section(
    section_key: str,
    user_message: str,
    ai_type: str = "deepseek",
    brand: str = "deepseek",
    on_complete: Callable = None,
) -> dict:
    cfg = SECTIONS[section_key]
    start = time.time()
    print(f"[{section_key}] 开始调用...")

    raw = await call_ai_full(
        system_prompt=cfg["prompt"],
        user_message=user_message,
        max_tokens=cfg["max_tokens"],
        ai_type=ai_type,
        brand=brand,
    )

    elapsed = time.time() - start
    print(f"[{section_key}] 完成, 耗时 {elapsed:.1f}s, 长度 {len(raw)}")

    if not raw.strip():
        print(f"[{section_key}] ⚠️ API返回空内容!")
        data = {"section": section_key, "error": "empty_response"}
    else:
        try:
            data = json.loads(clean_json_str(raw))
        except json.JSONDecodeError as e:
            print(f"[{section_key}] JSON 解析失败: {e}")
            print(f"[{section_key}] 原始内容前200字: {raw[:200]}")
            data = {"section": section_key, "error": str(e), "raw": raw[:500]}

    if on_complete:
        await on_complete(section_key, data)

    return data


# ============================================================
# 全并行生成完整报告 (19路并行)
# ============================================================

async def generate_full_report(
    bazi_str: str,
    gender: str,
    current_dayun: str,
    ai_type: str = "deepseek",
    brand: str = "deepseek",
    on_section_complete: Callable = None,
) -> dict:
    user_msg = f"用户的八字为'{bazi_str}' 性别为{gender} 当前大运为{current_dayun} 当前流年为丙午"

    total_start = time.time()
    print(f"🚀 启动 {len(SECTIONS)} 路并行调用...")

    # 19 个任务全部并行
    tasks = {
        key: asyncio.create_task(
            generate_section(key, user_msg, ai_type, brand, on_section_complete)
        )
        for key in SECTIONS
    }

    results = {}
    for key, task in tasks.items():
        results[key] = await task

    total_elapsed = time.time() - total_start
    print(f"\n✅ 全部完成! {len(SECTIONS)}路并行, 总耗时: {total_elapsed:.1f}s")

    report = merge_report(results)
    return report


def merge_report(results: Dict[str, dict]) -> dict:
    """将 19 个 section 的结果合并为完整报告"""
    foundation = results.get("foundation", {})

    # 按月份排序收集12个月运
    monthly_fortune = []
    for m in range(1, 13):
        mdata = results.get(f"monthly_{m}", {})
        # 单月数据本身就是完整结构，无需再取 monthly_fortune 子键
        if "error" not in mdata:
            monthly_fortune.append(mdata)
        else:
            monthly_fortune.append({"month_number": m, "error": mdata.get("error")})

    report = {
        "report_meta": foundation.get("report_meta", {}),
        "user_input": foundation.get("user_input", {}),
        "bazi_chart": foundation.get("bazi_chart", {}),
        "interactions_analysis": foundation.get("interactions_analysis", {}),
        "yearly_fortune": {
            "overall": foundation.get("yearly_fortune_overall", {}),
            "career": results.get("career", {}).get("career", {}),
            "wealth": results.get("wealth", {}).get("wealth", {}),
            "love": results.get("love", {}).get("love", {}),
            "health": results.get("health", {}).get("health", {}),
            "study": results.get("study_relations", {}).get("study", {}),
            "relationships": results.get("study_relations", {}).get("relationships", {}),
        },
        "monthly_fortune": monthly_fortune,
        "lucky_guide": results.get("lucky", {}).get("lucky_guide", {}),
        "remedies": results.get("lucky", {}).get("remedies", []),
        "annual_advice": results.get("lucky", {}).get("annual_advice", {}),
        "disclaimer": results.get("lucky", {}).get("disclaimer", ""),
    }
    return report


# ============================================================
# 测试入口
# ============================================================

async def main():
    start = time.time()
    ai_type = "claude"
    report = await generate_full_report(
        bazi_str="癸酉 己未 辛丑 戊子",
        gender="女",
        current_dayun="壬戌",
        ai_type=ai_type,
        brand="xiangliang",
    )

    print(f"\n总耗时: {time.time() - start:.1f}s")
    with open(f"report_output_{ai_type}.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"报告已写入 report_output.json")


if __name__ == "__main__":
    asyncio.run(main())