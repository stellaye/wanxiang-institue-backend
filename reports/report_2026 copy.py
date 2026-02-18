"""
2026年运报告 - 两阶段并行调用方案

架构:
  阶段1（全并行）:
    - 7个主体板块: foundation, career, wealth, love, health, study_relations, lucky
    - 月度评分 (monthly_scores) — 隐藏，返回12个月的 keyword + score
    - 年度分项评分 (yearly_scores) — 隐藏，返回6项 score
  
  阶段2（等月度评分完成后，12路并行）:
    - 月运×12 (monthly_1 ~ monthly_12)，每月 prompt 注入对应的 keyword + score

总调用: 阶段1: 9路 → 阶段2: 12路
预计耗时: max(阶段1) + max(阶段2) ≈ 25-40秒
"""

import asyncio
import json
import time
import aiohttp
from openai import AsyncOpenAI
from typing import AsyncGenerator, Dict, Any, Callable


class BaziElementCalculator:
    def __init__(self):
        # 天干五行属性
        self.tian_gan_element = {
            '甲': 'wood', '乙': 'wood',
            '丙': 'fire', '丁': 'fire',
            '戊': 'earth', '己': 'earth',
            '庚': 'metal', '辛': 'metal',
            '壬': 'water', '癸': 'water'
        }
        
        # 地支五行属性（本气）
        self.di_zhi_element = {
            '子': 'water', '丑': 'earth', '寅': 'wood', '卯': 'wood',
            '辰': 'earth', '巳': 'fire', '午': 'fire', '未': 'earth',
            '申': 'metal', '酉': 'metal', '戌': 'earth', '亥': 'water'
        }
        
        # 地支藏干映射
        self.hidden_gan = {
            '子': ['癸'],
            '丑': ['己', '癸', '辛'],
            '寅': ['甲', '丙', '戊'],
            '卯': ['乙'],
            '辰': ['戊', '乙', '癸'],
            '巳': ['丙', '庚', '戊'],
            '午': ['丁', '己'],
            '未': ['己', '丁', '乙'],
            '申': ['庚', '壬', '戊'],
            '酉': ['辛'],
            '戌': ['戊', '辛', '丁'],
            '亥': ['壬', '甲']
        }

    def calculate_element_distribution(self, year_pillar, month_pillar, day_pillar, hour_pillar):
        """
        计算五行分布
        输入格式：四柱八字，如 ('甲子', '乙丑', '丙寅', '丁卯')
        """
        # 初始化五行分布
        element_distribution = {
            "wood": {"count": 0, "status": ""},
            "fire": {"count": 0, "status": ""},
            "earth": {"count": 0, "status": ""},
            "metal": {"count": 0, "status": ""},
            "water": {"count": 0, "status": ""}
        }
        
        pillars = [year_pillar, month_pillar, day_pillar, hour_pillar]
        
        for pillar in pillars:
            tian_gan = pillar[0]  # 天干
            di_zhi = pillar[1]    # 地支
            
            # 统计天干
            if tian_gan in self.tian_gan_element:
                element = self.tian_gan_element[tian_gan]
                element_distribution[element]["count"] += 1
            
            # 统计地支藏干
            if di_zhi in self.hidden_gan:
                for hidden in self.hidden_gan[di_zhi]:
                    if hidden in self.tian_gan_element:
                        element = self.tian_gan_element[hidden]
                        element_distribution[element]["count"] += 1
        
        # 计算状态（旺相休囚死）- 简化版
        self._calculate_status(element_distribution)
        
        return element_distribution
    
    def _calculate_status(self, element_distribution):
        """计算五行状态（简化版）"""
        max_count = max(v["count"] for v in element_distribution.values())
        
        for element, data in element_distribution.items():
            if data["count"] == 0:
                data["status"] = "无"
            elif data["count"] == max_count:
                data["status"] = "旺"
            elif data["count"] >= max_count * 0.7:
                data["status"] = "相"
            elif data["count"] >= max_count * 0.4:
                data["status"] = "休"
            elif data["count"] >= max_count * 0.1:
                data["status"] = "囚"
            else:
                data["status"] = "死"




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
# 7个主体板块的 System Prompt
# ============================================================

PROMPT_FOUNDATION = """
你是一位精通中国传统命理学的资深八字命理分析师。
请根据用户提供的八字、性别和当前大运，完成【八字基础解析】和【2026丙午年年度总评】。
年度关键字要参考十神组合关系,比如丙午为财,那么可以说财星代表的意象
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
    "keyword": "年度关键词（请你铁口直断）",
    "summary": { "text": "150字以内年度总评", "bazi_explanation": "" },
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
    "summary": { "text": "事业运通俗分析150字以内", "bazi_explanation": "" },
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
    "summary": { "text": "财运通俗分析150字以内", "bazi_explanation": "" },
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
    "summary": { "text": "感情运通俗分析150字以内", "bazi_explanation": "" },
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
    "summary": { "text": "健康运通俗分析150字以内", "bazi_explanation": "" },
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
    "summary": { "text": "学业运通俗分析150字以内", "bazi_explanation": "" },
    "advice": { "text": "", "bazi_explanation": "" }
  },
  "relationships": {
    "score": 0,
    "summary": { "text": "人际关系通俗分析150字以内", "bazi_explanation": "" },
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
# 月度评分 Prompt（阶段1调用，返回12个月的 score + keyword）

PROMPT_YEARLY_SCORES = """
你是一位精通中国传统命理学的资深八字命理分析师。
请根据用户提供的八字、性别和当前大运，对2026丙午年的6个运势维度进行**横向对比评分**。

## 核心要求
1. 必须将6个维度放在一起横向对比，体现各方面的强弱差异
2. 分数范围 40-90
3. **6个分数不能全部相同或接近**，最高分与最低分之间差距应不少于15分
4. 铁口直断，强则高分，弱则低分，不要和稀泥

## 6个评分维度
1. career（事业）：事业发展、职位变动、工作机遇
2. wealth（财运）：正财偏财、投资理财、财务安全
3. love（感情）：桃花运、感情稳定度、婚恋进展
4. health（健康）：身体状况、精神状态、疾病风险
5. study（学业）：学习进步、考试运、知识积累
6. relationships（人际）：贵人运、人际和谐度、社交质量

## 评分依据
- 流年丙午干支与命局的互动关系
- 流年对各领域对应十神的影响
- 当前大运与流年的配合
- 命局本身在各领域的先天强弱

### 干支关系参考
- 天干五合：甲己合、乙庚合、丙辛合、丁壬合、戊癸合
- 地支六合：子丑、寅亥、卯戌、辰酉、巳申、午未
- 地支三合：申子辰水、亥卯未木、寅午戌火、巳酉丑金
- 地支六冲：子午、丑未、寅申、卯酉、辰戌、巳亥
- 地支六害：子未、丑午、寅巳、卯辰、申亥、酉戌
- 地支三刑：寅巳申、丑戌未、子卯刑

## 输出规则
- 输出纯 JSON，不要任何其他文字、不要 markdown 代码块包裹
- score 为 40-90 的整数
- 全部简体中文

## 输出 JSON 结构

{
  "section": "yearly_scores",
  "scores": {
    "career": { "score": 0 },
    "wealth": { "score": 0 },
    "love": { "score": 0 },
    "health": { "score": 0 },
    "study": { "score": 0 },
    "relationships": { "score": 0 }
  }
}
"""


# ============================================================
# 月运相关常量和 Prompt 生成函数
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



"""
月运生成改动说明：
1. PROMPT_MONTHLY_SCORES — keywords 改为数组，基于十神象义
2. PROMPT_YEARLY_SCORES — 不变
3. make_single_month_prompt — 接收 keywords 数组，注入十神象义引导
4. generate_full_report 中 score overlay — keywords 改为数组处理
"""

# ============================================================
# 替换原有 PROMPT_MONTHLY_SCORES
# ============================================================

PROMPT_MONTHLY_SCORES = """
你是一位精通中国传统命理学的资深八字命理分析师。
请根据用户提供的八字、性别和当前大运，对2026丙午年12个月的运势进行**横向对比评分**，并基于十神象义生成月度关键词。

## 评分核心要求
1. 必须将12个月放在一起综合对比，体现月运的高低起伏
2. 分数范围 45-95，**各月分数必须有明显区分度**，不允许出现连续3个月以上相同分数
3. 最高分与最低分之间差距应不少于20分
4. 铁口直断，该高则高，该低则低

## 十神速查表
- 与日主同五行同阴阳 = 比肩，同五行异阴阳 = 劫财
- 日主所生同阴阳 = 食神，异阴阳 = 伤官
- 日主所克同阴阳 = 偏财，异阴阳 = 正财
- 克日主同阴阳 = 偏官(七杀)，异阴阳 = 正官
- 生日主同阴阳 = 偏印(枭神)，异阴阳 = 正印

## ★★★ 最重要的原则：十神象义是中性的，吉凶由喜用决定 ★★★

十神本身没有好坏之分。同一个十神组合，对不同命局的人意义完全不同。
你必须严格按照以下流程判断每月关键词的吉凶方向：

### 判断流程（每个月都必须走一遍）：
第一步：确定月干十神、月支十神，写出十神组合（如"劫财坐正财"）
第二步：判断月干十神对此命局是喜神还是忌神
第三步：判断月支十神对此命局是喜神还是忌神
第四步：分析月支与命局四柱、流年、大运的刑冲合害
第五步：综合以上四步，决定关键词的吉凶方向和具体内容

### 同一十神组合的不同表现（核心示例）：

**劫财坐正财：**
- 劫财为喜用 → "拼劲十足利求财" "合作竞争促进步" "积极行动有回报"
- 劫财为忌神 → "同行竞争压力大" "合作中利益分歧" "财务需防消耗"
- 若月支同时有合 → 可加"合作关系有牵绊"
- 若月支同时有冲 → 可加"财务计划需灵活调整"

**比肩坐偏财：**
- 比肩为喜用 → "朋友带来赚钱信息" "团队协作利财运" "社交助力事业"
- 比肩为忌神 → "人多眼杂需谨慎" "社交开销需节制" "投资忌跟风"

**伤官坐正官：**
- 伤官为喜用 → "锋芒毕露获赏识" "敢于创新有突破" "表达力强利谈判"
- 伤官为忌神 → "言辞锋利易得罪人" "与上级理念有分歧" "表达需注意分寸"

**正印坐正印：**
- 印星为喜用 → "贵人提携运势强" "学习高效有收获" "长辈关照有温暖"
- 印星为忌神 → "思虑过重行动慢" "依赖心强缺决断" "过度保守错时机"

**食神坐正官：**
- 食神为喜用 → "才华征服权威" "轻松应对考核" "创意获认可"
- 食神为忌神 → "才华外泄需收敛" "过度表现招嫉妒" "享乐分散精力"

**七杀坐比肩：**
- 七杀为喜用 → "压力催生行动力" "竞争激发潜能" "挑战带来成长"
- 七杀为忌神 → "外部压力突增" "与同行摩擦频繁" "需团队协作分压"

**正财坐七杀：**
- 正财为喜用 → "高压下收入增长" "付出必有回报" "财务纪律带来安全"
- 正财为忌神 → "为财奔波压力大" "收入伴随更多责任" "花钱消灾不得已"

**偏财坐偏印：**
- 偏财为喜用 → "非主流渠道有财运" "灵活理财有收益" "偏门知识能变现"
- 偏财为忌神 → "投资信息不透明" "偏门机会风险大" "计划易突然变化"

### 关键词生成规则：
1. 每月 2-4 个关键词，放在 keywords 数组中
2. 每个关键词 3-8 字大白话，普通人一眼能看懂
3. **关键词必须反映该月的多面性**：如果该十神组合既有利又有弊，关键词应该包含两面
4. **绝对禁止编造具体事件**：不能写"朋友找你借钱""领导给你升职"这类断言
5. 应该写象义方向：如"人脉活跃利求财""合作需明确权责""拼劲带来新机会"
6. 12个月的关键词组合**不能雷同**

### 关键词绝对禁止：
❌ 命理术语直接做关键词：偏财坐印、官印相生、食伤泄秀
❌ 空洞成语：稳中求进、破茧成蝶、厚积薄发
❌ 万能废话：机遇与挑战并存、身心俱疲
❌ 编造具体事件：朋友借钱周转、领导找你谈话、签下大合同
❌ 全部负面或全部正面：每月至少要有一个关键词体现另一面

### 关键词正确示例（注意吉凶兼有）：
✅ ["拼劲足利求财", "合作需划清边界", "社交带动机会"] — 劫财坐正财（劫财为喜用时）
✅ ["竞争环境加剧", "主动出击有转机", "财务需防消耗"] — 劫财坐正财（劫财为忌神时）
✅ ["贵人提携明显", "学习效率提升", "注意别过度依赖"] — 正印坐正财（印星为喜用时）
✅ ["才华获认可", "口舌后有转圜", "利于进修充电"] — 伤官坐正印（伤官为喜用时）
✅ ["压力催生行动力", "合作中有磨合", "果断决策是关键"] — 七杀坐比肩（七杀为喜用时）

## 评分依据
- 月干月支十神对日主是喜还是忌
- 各月月柱与命局四柱的干支互动（合冲刑害）
- 各月月柱与流年丙午的干支互动
- 各月月柱与当前大运的干支互动
- 十神组合对日主的综合利弊影响

### 2026丙午年各月干支
正月庚寅、二月辛卯、三月壬辰、四月癸巳、五月甲午、六月乙未、七月丙申、八月丁酉、九月戊戌、十月己亥、十一月庚子、十二月辛丑

### 干支关系参考
- 天干五合：甲己合、乙庚合、丙辛合、丁壬合、戊癸合
- 地支六合：子丑、寅亥、卯戌、辰酉、巳申、午未
- 地支三合：申子辰水、亥卯未木、寅午戌火、巳酉丑金
- 地支三会：寅卯辰木、巳午未火、申酉戌金、亥子丑水
- 地支六冲：子午、丑未、寅申、卯酉、辰戌、巳亥
- 地支六害：子未、丑午、寅巳、卯辰、申亥、酉戌
- 地支三刑：寅巳申、丑戌未、子卯刑、辰辰/午午/酉酉/亥亥自刑
- 地支相破：子酉、丑辰、寅亥、卯午、巳申、未戌

## 输出规则
- 输出纯 JSON，不要任何其他文字、不要 markdown 代码块包裹
- score 为 45-95 的整数
- keywords 为数组，2-4个元素，每个为3-8字大白话
- 必须先输出 stem_god / branch_god / is_stem_favorable / is_branch_favorable 字段
- 12个月的 keywords 组合不能雷同
- 全部简体中文

## 输出 JSON 结构

{
  "section": "monthly_scores",
  "scores": {
    "1":  { "score": 0, "stem_god": "月干对日主的十神", "branch_god": "月支对日主的十神", "combo": "X坐X", "is_stem_favorable": true/false, "is_branch_favorable": true/false, "keywords": ["关键词1", "关键词2", "关键词3"] },
    "2":  { "score": 0, "stem_god": "", "branch_god": "", "combo": "", "is_stem_favorable": true, "is_branch_favorable": true, "keywords": [] },
    "3":  { "score": 0, "stem_god": "", "branch_god": "", "combo": "", "is_stem_favorable": true, "is_branch_favorable": true, "keywords": [] },
    "4":  { "score": 0, "stem_god": "", "branch_god": "", "combo": "", "is_stem_favorable": true, "is_branch_favorable": true, "keywords": [] },
    "5":  { "score": 0, "stem_god": "", "branch_god": "", "combo": "", "is_stem_favorable": true, "is_branch_favorable": true, "keywords": [] },
    "6":  { "score": 0, "stem_god": "", "branch_god": "", "combo": "", "is_stem_favorable": true, "is_branch_favorable": true, "keywords": [] },
    "7":  { "score": 0, "stem_god": "", "branch_god": "", "combo": "", "is_stem_favorable": true, "is_branch_favorable": true, "keywords": [] },
    "8":  { "score": 0, "stem_god": "", "branch_god": "", "combo": "", "is_stem_favorable": true, "is_branch_favorable": true, "keywords": [] },
    "9":  { "score": 0, "stem_god": "", "branch_god": "", "combo": "", "is_stem_favorable": true, "is_branch_favorable": true, "keywords": [] },
    "10": { "score": 0, "stem_god": "", "branch_god": "", "combo": "", "is_stem_favorable": true, "is_branch_favorable": true, "keywords": [] },
    "11": { "score": 0, "stem_god": "", "branch_god": "", "combo": "", "is_stem_favorable": true, "is_branch_favorable": true, "keywords": [] },
    "12": { "score": 0, "stem_god": "", "branch_god": "", "combo": "", "is_stem_favorable": true, "is_branch_favorable": true, "keywords": [] }
  }
}
"""


# ============================================================
# 完整替换 make_single_month_prompt
# ============================================================

def make_single_month_prompt(
    m: int,
    keywords: list = None,
    score: int = 0,
    stem_god: str = "",
    branch_god: str = "",
    combo: str = "",
    is_stem_favorable: bool = None,
    is_branch_favorable: bool = None,
) -> str:
    """生成单月月运 prompt，注入十神信息、喜忌判断、关键词和分数"""
    sb = MONTH_STEM_BRANCH[m]
    ln = LUNAR_MONTH[m]

    keyword_guide = ""
    if keywords and score:
        kw_str = "、".join(f"「{k}」" for k in keywords)

        # 构建喜忌说明
        stem_favor_text = "喜用神（有利）" if is_stem_favorable else "忌神（不利）"
        branch_favor_text = "喜用神（有利）" if is_branch_favorable else "忌神（不利）"

        keyword_guide = f"""
## 本月核心信息（必须严格遵守）
- 本月十神组合：月干为**{stem_god}**（对此命局为{stem_favor_text}），月支为**{branch_god}**（对此命局为{branch_favor_text}），组合为 **{combo}**
- 本月关键词：{kw_str}
- 本月综合评分：{score}/100

### ★ 月度总结的核心写作逻辑 ★

你必须基于以下逻辑来写 summary.text：

1. **先明确十神象义方向**：
   - {stem_god}的象义包括哪些方面（参考下方十神象义表）
   - {branch_god}的象义包括哪些方面
   - {combo}这个组合的整体象义方向是什么

2. **再根据喜忌决定吉凶色彩**：
   - {stem_god}对此命局为{stem_favor_text}，所以{stem_god}带来的影响偏向{'正面积极' if is_stem_favorable else '需要注意防范'}
   - {branch_god}对此命局为{branch_favor_text}，所以{branch_god}带来的影响偏向{'正面积极' if is_branch_favorable else '需要注意防范'}

3. **结合刑冲合害调整**：如果月支与命局有冲/刑/害，即使十神为喜用，也要提及动荡面；如果有合，可能有牵绊或助力

4. **围绕关键词展开**：每个关键词至少有一两句对应的分析

### 十神象义参考表（中性描述，不预设吉凶）：
- **比肩/劫财**：同辈互动、竞争与合作、团队协作、独立行动、资源争夺与共享
- **食神/伤官**：才华表达、创意灵感、技术展示、口才沟通、享受生活、叛逆创新
- **正财/偏财**：收入变化、理财投资、消费支出、商业合作、务实行动、资源获取
- **正官/七杀**：事业压力、规则约束、上级互动、竞争挑战、责任担当、权力变化
- **正印/偏印**：学习进修、贵人相助、长辈关系、思维模式、保护与依赖、技术专研

### ★★ 绝对禁止的写法 ★★
❌ 编造具体事件："朋友找你借钱" "领导叫你谈话" "签下一个大合同"
❌ 预设全部负面："这个月处处碰壁" "钱财不断外流"
❌ 预设全部正面："一切顺风顺水" "财运滚滚而来"
❌ 万能废话："机遇与挑战并存" "需要你打起精神" "身心俱疲"

### ★★ 正确的写法 ★★
✅ 围绕象义展开分析："本月{combo}的组合，意味着在XX方面会比较活跃……"
✅ 吉凶兼顾："虽然XX方面有利，但在YY方面需要留意……"
✅ 给出方向而非断言："财务方面可能出现XX趋势，建议……"
"""

    return f"""
你是一位精通中国传统命理学的资深八字命理分析师。
请根据用户提供的八字、性别和当前大运，专门分析【2026丙午年{m}月（农历{ln}，月柱{sb}）的月度运势】。

重点分析该月月柱{sb}与命局四柱、流年丙午、当前大运之间的干支互动关系。
{keyword_guide}

{BAZI_ANALYSIS_GUIDE}
{COMMON_OUTPUT_RULES}

## 月度总结写作规则（极其重要！）

### summary.text 写作要求：
1. 字数控制在100-150字
2. 开头第一句直接从本月十神象义切入，**禁止**用"这个月对你而言""本月"开头
3. 全文必须围绕 {combo if combo else '本月十神组合'} 的象义展开，不能写与十神无关的内容
4. **必须体现多面性**：既写有利的一面，也写需注意的一面（除非分数极高>85或极低<50）
5. 如果月支与命局有刑冲合害，必须体现其影响
6. **绝对禁止编造具体事件和断言**

### 宜忌（do/dont）写作要求：
1. 宜忌必须基于十神象义方向，而不是编造具体行为
2. **宜**：顺应本月有利十神的象义方向去行动
3. **忌**：规避本月不利十神可能带来的问题
4. 不能写太绝对的禁令（如"绝对不能借钱"），而是方向性建议（如"大额资金往来需谨慎"）
5. 每条宜忌要简洁，5-12字

### 分项运势写作要求：
1. career/wealth/love/health 每项50字以内
2. 必须结合十神象义来分析，不能脱离本月{combo if combo else '十神组合'}
3. 同样禁止编造具体事件，围绕象义方向分析

打分时你客观一点,希望你铁口直断。

## 输出 JSON 结构

{{
  "section": "monthly_{m}",
  "month_number": {m},
  "lunar_month": "{ln}",
  "stem_branch": "{sb}",
  "stem_god": "{stem_god if stem_god else '请填写月干对日主的十神'}",
  "branch_god": "{branch_god if branch_god else '请填写月支对日主的十神'}",
  "combo": "{combo if combo else '请填写X坐X'}",
  "solar_range": "公历起止日期（请根据2026年节气推算）",
  "keywords": {json.dumps(keywords, ensure_ascii=False) if keywords else '["关键词1", "关键词2", "关键词3"]'},
  "summary": {{
    "text": "月度运势通俗概述100-150字，围绕十神象义展开，体现多面性，禁止编造事件",
    "bazi_explanation": "该月干支十神组合分析 + 喜忌判断 + 与命局及流年的刑冲合害互动分析"
  }},
  "career": {{ "text": "事业方面50字以内，基于十神象义分析", "bazi_explanation": "" }},
  "wealth": {{ "text": "财运方面50字以内，基于十神象义分析", "bazi_explanation": "" }},
  "love":   {{ "text": "感情方面50字以内，基于十神象义分析", "bazi_explanation": "" }},
  "health": {{ "text": "健康方面50字以内，基于十神象义分析", "bazi_explanation": "" }},
  "do": ["宜做的事1（基于象义方向）", "宜做的事2", "宜做的事3"],
  "dont": ["忌做的事1（基于象义方向）", "忌做的事2", "忌做的事3"]
}}

只输出这1个月的数据，不要输出其他月份。
"""


def _overlay_monthly_scores(report, score_data):
    """用月度评分覆盖各月 score、keywords、十神信息"""
    if not score_data or "scores" not in score_data:
        return

    scores_map = score_data["scores"]
    for month_data in report.get("monthly_fortune", []):
        m_num = str(month_data.get("month_number", ""))
        if m_num in scores_map:
            s_info = scores_map[m_num]
            if isinstance(s_info, dict):
                if "score" in s_info:
                    month_data["score"] = s_info["score"]
                if s_info.get("keywords"):
                    month_data["keywords"] = s_info["keywords"]
                if s_info.get("stem_god"):
                    month_data["stem_god"] = s_info["stem_god"]
                if s_info.get("branch_god"):
                    month_data["branch_god"] = s_info["branch_god"]
                if s_info.get("combo"):
                    month_data["combo"] = s_info["combo"]
                if "is_stem_favorable" in s_info:
                    month_data["is_stem_favorable"] = s_info["is_stem_favorable"]
                if "is_branch_favorable" in s_info:
                    month_data["is_branch_favorable"] = s_info["is_branch_favorable"]

    print(f"✅ 已用月度评分覆盖各月 score & keywords & 十神信息")

# ============================================================
# generate_full_report 中阶段2的调用改动（替换对应代码段）
# ============================================================

# 在 generate_full_report 函数的阶段2循环中，改为：

def _build_monthly_tasks_phase2(score_data, user_msg, ai_type, brand, on_section_complete):
    """阶段2：根据月度评分结果，构建12个月运详情的并行任务"""
    import asyncio
    monthly_tasks = {}

    for m in range(1, 13):
        m_keywords = []
        m_score = 0
        m_stem_god = ""
        m_branch_god = ""
        m_combo = ""
        m_is_stem_favorable = None
        m_is_branch_favorable = None

        if score_data and "scores" in score_data:
            m_info = score_data["scores"].get(str(m), {})
            if isinstance(m_info, dict):
                m_keywords = m_info.get("keywords", [])
                m_score = m_info.get("score", 0)
                m_stem_god = m_info.get("stem_god", "")
                m_branch_god = m_info.get("branch_god", "")
                m_combo = m_info.get("combo", "")
                m_is_stem_favorable = m_info.get("is_stem_favorable")
                m_is_branch_favorable = m_info.get("is_branch_favorable")

        month_prompt = make_single_month_prompt(
            m,
            keywords=m_keywords,
            score=m_score,
            stem_god=m_stem_god,
            branch_god=m_branch_god,
            combo=m_combo,
            is_stem_favorable=m_is_stem_favorable,
            is_branch_favorable=m_is_branch_favorable,
        )

        section_key = f"monthly_{m}"
        monthly_tasks[section_key] = asyncio.create_task(
            _generate_monthly_section(
                section_key=section_key,
                prompt=month_prompt,
                user_message=user_msg,
                score=m_score,
                keyword="",
                ai_type=ai_type,
                brand=brand,
                on_complete=on_section_complete,
            )
        )

    return monthly_tasks

# ============================================================
# 7个主体板块的 Section 配置（不含月运！月运在阶段2动态生成）
# ============================================================

SECTIONS = {
    "foundation":      {"prompt": PROMPT_FOUNDATION,       "max_tokens": 6000},
    "career":          {"prompt": PROMPT_CAREER,            "max_tokens": 3500},
    "wealth":          {"prompt": PROMPT_WEALTH,            "max_tokens": 3500},
    "love":            {"prompt": PROMPT_LOVE,              "max_tokens": 3500},
    "health":          {"prompt": PROMPT_HEALTH,            "max_tokens": 3000},
    "study_relations": {"prompt": PROMPT_STUDY_RELATIONS,   "max_tokens": 3500},
    "lucky":           {"prompt": PROMPT_LUCKY,             "max_tokens": 4000},
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
# 核心：生成单个主体 Section（阶段1用）
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
# 核心：生成单月月运（阶段2用，prompt 已包含 keyword + score）
# ============================================================

async def _generate_monthly_section(
    section_key: str,
    prompt: str,
    user_message: str,
    score: int,
    keyword: str,
    ai_type: str = "deepseek",
    brand: str = "deepseek",
    on_complete: Callable = None,
) -> dict:
    """生成单月月运（阶段2专用，prompt已包含关键词和分数）"""
    start = time.time()
    print(f"[{section_key}] 开始调用（关键词={keyword}, 分数={score}）...")

    raw = await call_ai_full(
        system_prompt=prompt,
        user_message=user_message,
        max_tokens=1500,
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
# 两阶段并行生成完整报告
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

    # ================================================================
    # 阶段1：7个主体板块 + 月度评分 + 年度分项评分（全并行）
    # ================================================================
    print(f"🚀 阶段1: 启动 7 + 2 路并行调用...")

    # 7个主体板块（计入前端进度）
    main_tasks = {
        key: asyncio.create_task(
            generate_section(key, user_msg, ai_type, brand, on_section_complete)
        )
        for key in SECTIONS
    }

    # 月度评分（隐藏，不计入前端进度）
    monthly_score_task = asyncio.create_task(
        call_ai_full(
            system_prompt=PROMPT_MONTHLY_SCORES,
            user_message=user_msg,
            max_tokens=2000,
            ai_type=ai_type,
            brand=brand,
        )
    )

    # 年度分项评分（隐藏，不计入前端进度）
    yearly_score_task = asyncio.create_task(
        call_ai_full(
            system_prompt=PROMPT_YEARLY_SCORES,
            user_message=user_msg,
            max_tokens=1000,
            ai_type=ai_type,
            brand=brand,
        )
    )

    # ---- 先等月度评分完成（阶段2依赖它） ----
    score_raw = await monthly_score_task
    score_data = None
    if score_raw and score_raw.strip():
        try:
            score_data = json.loads(clean_json_str(score_raw))
            print(f"✅ 阶段1: 月度评分完成, 解析成功")
        except json.JSONDecodeError as e:
            print(f"⚠️ 月度评分 JSON 解析失败: {e}")
            print(f"   原始内容前200字: {score_raw[:200]}")
    else:
        print(f"⚠️ 月度评分 API 返回空内容")

    # ================================================================
    # 阶段2：12个月运详情（全并行，每月带上关键词和分数）
    # ================================================================
    print(f"🚀 阶段2: 启动 12 路月运并行调用...")

    monthly_tasks = _build_monthly_tasks_phase2(score_data, user_msg, ai_type, brand, on_section_complete)
    # ---- 等待阶段1剩余的主体板块完成 ----
    main_results = {}
    for key, task in main_tasks.items():
        main_results[key] = await task

    # ---- 等待年度分项评分完成 ----
    yearly_score_raw = await yearly_score_task
    yearly_score_data = None
    if yearly_score_raw and yearly_score_raw.strip():
        try:
            yearly_score_data = json.loads(clean_json_str(yearly_score_raw))
            print(f"✅ 年度分项评分完成, 解析成功")
        except json.JSONDecodeError as e:
            print(f"⚠️ 年度分项评分 JSON 解析失败: {e}")
            print(f"   原始内容前200字: {yearly_score_raw[:200]}")
    else:
        print(f"⚠️ 年度分项评分 API 返回空内容")

    # ---- 等待阶段2的12个月运全部完成 ----
    monthly_results = {}
    for key, task in monthly_tasks.items():
        monthly_results[key] = await task

    # 合并所有结果
    all_results = {**main_results, **monthly_results}

    total_elapsed = time.time() - total_start
    print(f"\n✅ 全部完成! 两阶段并行, 总耗时: {total_elapsed:.1f}s")

    # ---- 合并报告 ----
    report = merge_report(all_results)

    _overlay_monthly_scores(report,score_data)
    # ---- 用年度分项评分覆盖各项 score ----
    if yearly_score_data and "scores" in yearly_score_data:
        ys_map = yearly_score_data["scores"]
        yearly = report.get("yearly_fortune", {})
        for dimension in ["career", "wealth", "love", "health", "study", "relationships"]:
            if dimension in ys_map and dimension in yearly:
                s_info = ys_map[dimension]
                if isinstance(s_info, dict) and "score" in s_info:
                    yearly[dimension]["score"] = s_info["score"]
        print(f"✅ 已用年度分项评分覆盖 6 项 score")

    # ---- 修正五行分布（原有逻辑不变） ----
    calculator = BaziElementCalculator()
    bazi_list = bazi_str.split(" ")
    year_pillar = bazi_list[0]
    month_pillar = bazi_list[1]
    day_pillar = bazi_list[2]
    hour_pillar = bazi_list[3]
    result = calculator.calculate_element_distribution(
        year_pillar, month_pillar, day_pillar, hour_pillar
    )
    for item in report["bazi_chart"]["element_distribution"]:
        report["bazi_chart"]["element_distribution"][item]["count"] = result[item]["count"]

    return report


def merge_report(results: Dict[str, dict]) -> dict:
    """将所有 section 的结果合并为完整报告"""
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