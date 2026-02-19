"""
28星宿合盘 API Handler
GET /api/constellation/relation
    ?your_birth_year=1990&your_birth_month=6&your_birth_day=15
    &other_birth_year=1992&other_birth_month=3&other_birth_day=20

Response JSON:
{
    "your_benmin_cons":      "角宿",
    "other_benmin_cons":     "心宿",
    "benmin_relation":       "近距离安坏",
    "benmin_relation_type":  "anhuai",
    "benmin_distance":       "close",
    "your_benmin_role":      "an",
    "other_benmin_role":     "huai",
    "your_zhiri_cons":       "虚宿",
    "other_zhiri_cons":      "斗宿",
    "zhiri_relation":        "中距离荣亲",
    "zhiri_relation_type":   "rongqin",
    "zhiri_distance":        "medium",
    "your_zhiri_role":       "rong",
    "other_zhiri_role":      "qin"
}
"""

import traceback
import sxtwl
from consts.ganzhi import Zhi
from logger import logger
from cons_common import (
    benmin_cons_list,
    all_cons,
    relation_dict,
    calculate_zhiri_constellation,
)


# ── 中文角色 → 前端 role key 映射 ──
ROLE_MAP = {
    "安": "an",
    "坏": "huai",
    "危": "wei",
    "成": "cheng",
    "业": "ye",
    "胎": "tai",
    "荣": "rong",
    "亲": "qin",
    "友": "you",
    "衰": "shuai",
    "命": "ming",
}

# ── 中文关系名 → 前端 relation type key ──
# relation_dict 值示例: "近距离安坏" / "业胎" / "命之星"
RELATION_TYPE_MAP = {
    "安坏": "anhuai",
    "危成": "weicheng",
    "业胎": "yetai",
    "荣亲": "rongqin",
    "友衰": "youshuai",
    "命之星": "mingzhixing",
}

DISTANCE_MAP = {
    "近距离": "close",
    "中距离": "medium",
    "远距离": "far",
}


def _parse_relation(relation_name):
    """
    把 relation_dict 的中文关系名解析为前端需要的 type + distance
    例: "近距离安坏" → ("anhuai", "close")
         "业胎"       → ("yetai", "medium")   # 业胎无远近之分，默认 medium
         "命之星"     → ("mingzhixing", "close")
    """
    # 命之星 特殊处理
    if relation_name == "命之星":
        return "mingzhixing", "close"

    # 业胎 特殊处理（无距离前缀）
    if relation_name == "业胎":
        return "yetai", "medium"

    # 其余格式: "X距离YY"
    distance = "medium"
    core = relation_name
    for cn_dist, en_dist in DISTANCE_MAP.items():
        if relation_name.startswith(cn_dist):
            distance = en_dist
            core = relation_name[len(cn_dist):]
            break

    rel_type = RELATION_TYPE_MAP.get(core, "normal")
    return rel_type, distance


def calculate_constellation_relation(your_cons, other_cons):
    """计算两个星宿之间的关系，返回 relation_dict 中的 tuple"""
    if your_cons == "牛宿":
        your_cons = "女宿"
    if other_cons == "牛宿":
        other_cons = "女宿"

    your_idx = all_cons.index(your_cons)
    other_idx = all_cons.index(other_cons)
    diff = other_idx - your_idx

    if abs(diff) > 13:
        diff = -(27 - abs(diff)) if diff > 0 else (27 - abs(diff))

    return relation_dict[diff]


def _build_relation_result(your_cons, other_cons, prefix):
    """
    为本命或值日构建一组结果字段
    prefix: "benmin" | "zhiri"
    """
    rel_tuple = calculate_constellation_relation(your_cons, other_cons)
    rel_name = rel_tuple[0]       # e.g. "近距离安坏"
    your_role_cn = rel_tuple[1]   # e.g. "安"
    other_role_cn = rel_tuple[2]  # e.g. "坏"

    rel_type, distance = _parse_relation(rel_name)

    return {
        f"your_{prefix}_cons": your_cons,
        f"other_{prefix}_cons": other_cons,
        f"{prefix}_relation": rel_name,
        f"{prefix}_relation_type": rel_type,
        f"{prefix}_distance": distance,
        f"your_{prefix}_role": ROLE_MAP.get(your_role_cn, "none"),
        f"other_{prefix}_role": ROLE_MAP.get(other_role_cn, "none"),
    }


class CalculateConstellationRelation(LoggedRequestHandler):
    """
    GET /api/constellation/relation
    """

    def get(self):
        try:
            # ── 1. 读取参数 ──
            your_year = int(self.get_argument("your_birth_year"))
            your_month = int(self.get_argument("your_birth_month"))
            your_day = int(self.get_argument("your_birth_day"))
            other_year = int(self.get_argument("other_birth_year"))
            other_month = int(self.get_argument("other_birth_month"))
            other_day = int(self.get_argument("other_birth_day"))

            # ── 2. 阳历 → sxtwl Day 对象 ──
            your_day_obj = sxtwl.fromSolar(your_year, your_month, your_day)
            other_day_obj = sxtwl.fromSolar(other_year, other_month, other_day)

            # ── 3. 本命星宿（农历月日查表）──
            your_lunar_m = your_day_obj.getLunarMonth()
            your_lunar_d = your_day_obj.getLunarDay()
            your_benmin = benmin_cons_list[your_lunar_d - 1][your_lunar_m - 1]

            other_lunar_m = other_day_obj.getLunarMonth()
            other_lunar_d = other_day_obj.getLunarDay()
            other_benmin = benmin_cons_list[other_lunar_d - 1][other_lunar_m - 1]

            # ── 4. 值日星宿（地支 + 星期）──
            your_dizhi = Zhi[your_day_obj.getDayGZ().dz]
            your_week = your_day_obj.getWeek()
            your_zhiri = calculate_zhiri_constellation(your_dizhi, your_week)

            other_dizhi = Zhi[other_day_obj.getDayGZ().dz]
            other_week = other_day_obj.getWeek()
            other_zhiri = calculate_zhiri_constellation(other_dizhi, other_week)

            # ── 5. 构建结果 ──
            result = {}
            result.update(_build_relation_result(your_benmin, other_benmin, "benmin"))
            result.update(_build_relation_result(your_zhiri, other_zhiri, "zhiri"))

            logger.info(f"[Constellation] result={result}")
            self.write(result)

        except ValueError as e:
            logger.warning(f"[Constellation] bad params: {e}")
            self.write_error_json("Invalid date parameters", 400)
        except Exception:
            logger.error(traceback.format_exc())
            self.write_error_json("Internal server error", 500)


# ── URL 路由（添加到你的 tornado Application 中）──
# app = tornado.web.Application([
#     (r"/api/constellation/relation", CalculateConstellationRelation),
#     ...
# ])