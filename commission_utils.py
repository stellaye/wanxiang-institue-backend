"""
佣金分配工具函数 - 改进版

核心逻辑说明：
commission_rate 的含义是"给这一支（包括下级）分配的总比例"

示例：
您 → A → B → 用户下单

配置：
- 您给A这一支：30%
- A给B：20%

分配结果：
- B（直接推荐人）：20%
- A（B的上级）：30% - 20% = 10%
- 您（A的上级）：45% - 30% = 15%
"""
from models import User, ReferralChain, CommissionConfig, CommissionRecord, Order
from logger import logger


async def create_referral_chain(new_user_id, parent_ref_code):
    """
    创建推广关系链

    Args:
        new_user_id: 新用户ID
        parent_ref_code: 推荐人的ref_code

    Returns:
        bool: 是否成功建立关系
    """
    # 1. 查找推荐人
    parent_user = await User.aio_get_or_none(User.ref_code == parent_ref_code)
    if not parent_user:
        # 推荐码无效，创建为顶级用户
        await ReferralChain.aio_create(
            user_id=new_user_id,
            parent_user_id=None,
            ancestor_path='/',
            level=0
        )
        return False

    # 2. 防止循环推广
    parent_chain = await ReferralChain.aio_get_or_none(
        ReferralChain.user_id == parent_user.id
    )

    if parent_chain and f"/{new_user_id}/" in parent_chain.ancestor_path:
        logger.warning(f"检测到循环推广: user {new_user_id} -> {parent_user.id}")
        # 创建为顶级用户
        await ReferralChain.aio_create(
            user_id=new_user_id,
            parent_user_id=None,
            ancestor_path='/',
            level=0
        )
        return False

    # 3. 构建祖先路径和层级
    if parent_chain:
        ancestor_path = f"{parent_chain.ancestor_path}{parent_user.id}/"
        level = parent_chain.level + 1
    else:
        ancestor_path = f"/{parent_user.id}/"
        level = 1

    # 4. 创建推广链记录
    await ReferralChain.aio_create(
        user_id=new_user_id,
        parent_user_id=parent_user.id,
        ancestor_path=ancestor_path,
        level=level
    )

    # 5. 创建默认佣金配置
    # 默认给下级这一支30%（这样下级可以再分配给他的下级，自己还能留一些）
    await CommissionConfig.aio_create(
        parent_user_id=parent_user.id,
        child_user_id=new_user_id,
        commission_rate=30.00
    )

    return True


async def distribute_multi_level_commission(order):
    """
    多级佣金分配 - 清晰版

    配置含义：
    commission_rate = 给这个下级分支分配的总比例

    计算方式：
    - 从下往上遍历
    - 每个人获得 = 分配给自己的比例 - 分配给下级的比例

    示例：
    您(L0) → A(L1) → B(L2) → 用户下单99元

    配置：
    - 您 → A: 30%  (A这一支最多拿30%)
    - A → B: 20%   (B拿20%)

    计算：
    - B: 20%
    - A: 30% - 20% = 10%
    - 您: 45% - 30% = 15%
    """
    if not order.ref_code:
        return

    # 1. 查找直接推荐人
    referrer = await User.aio_get_or_none(User.ref_code == order.ref_code)
    if not referrer:
        return

    # 2. 获取推广链
    referrer_chain = await ReferralChain.aio_get_or_none(
        ReferralChain.user_id == referrer.id
    )

    # 3. 计算总佣金
    total_commission_rate = 45
    order_amount = order.amount
    total_commission_fen = order_amount * total_commission_rate / 100
    total_commission_yuan = round(total_commission_fen / 100)
    total_commission = total_commission_yuan * 100

    # 4. 构建推广链（从顶级到推荐人）
    chain_user_ids = []
    if referrer_chain and referrer_chain.ancestor_path and referrer_chain.ancestor_path != '/':
        ancestor_ids = [
            int(uid) for uid in referrer_chain.ancestor_path.strip('/').split('/')
            if uid
        ]
        chain_user_ids.extend(ancestor_ids)
    chain_user_ids.append(referrer.id)

    # 5. 获取每一级的佣金配置
    # allocated_rates[i] = 分配给第i个人这一支的总比例
    allocated_rates = {}

    for i in range(len(chain_user_ids)):
        user_id = chain_user_ids[i]

        if i == 0:
            # 顶级用户，分配全部45%
            allocated_rates[user_id] = total_commission_rate
        else:
            # 查询上级给自己分配的比例
            parent_id = chain_user_ids[i - 1]
            config = await CommissionConfig.aio_get_or_none(
                CommissionConfig.parent_user_id == parent_id,
                CommissionConfig.child_user_id == user_id
            )
            rate = float(config.commission_rate) if config else 20.0
            allocated_rates[user_id] = rate

    # 6. 计算每个人实际获得的佣金
    for i in range(len(chain_user_ids)):
        user_id = chain_user_ids[i]

        # 分配给我这一支的总比例
        my_allocated = allocated_rates[user_id]

        # 我分配给下级的比例
        if i < len(chain_user_ids) - 1:
            child_id = chain_user_ids[i + 1]
            child_allocated = allocated_rates[child_id]
        else:
            child_allocated = 0

        # 我实际获得的比例 = 分配给我的 - 分配给下级的
        my_rate = my_allocated - child_allocated

        # 计算佣金金额
        commission_fen = total_commission * my_rate / total_commission_rate
        commission_yuan = round(commission_fen / 100)
        commission_final = commission_yuan * 100

        if commission_final > 0:
            # 更新用户余额
            user = await User.aio_get(User.id == user_id)
            user.balance = (user.balance or 0) + commission_final
            user.total_earned = (user.total_earned or 0) + commission_final
            await user.aio_save()

            # 记录佣金分配
            await CommissionRecord.aio_create(
                order_no=order.out_trade_no,
                user_id=user_id,
                level=i,
                commission_amount=commission_final,
                commission_rate=my_rate,
                order_amount=order_amount
            )

            logger.info(
                f"佣金分配: 订单{order.out_trade_no}, "
                f"用户{user_id}, 层级L{i}, 分配{my_allocated}%, 下级{child_allocated}%, "
                f"实得{my_rate}%, 金额{commission_final}分"
            )


async def get_referral_chain(user_id):
    """
    获取用户的推广链

    Args:
        user_id: 用户ID

    Returns:
        list: 推广链列表，从顶级到当前用户
    """
    chain = await ReferralChain.aio_get_or_none(ReferralChain.user_id == user_id)
    if not chain:
        return []

    chain_user_ids = []
    if chain.ancestor_path and chain.ancestor_path != '/':
        ancestor_ids = [
            int(uid) for uid in chain.ancestor_path.strip('/').split('/')
            if uid
        ]
        chain_user_ids.extend(ancestor_ids)
    chain_user_ids.append(user_id)

    # 获取用户信息
    result = []
    for idx, uid in enumerate(chain_user_ids):
        user = await User.aio_get_or_none(User.id == uid)
        if user:
            result.append({
                'user_id': uid,
                'nickname': user.nickname or f'用户{uid}',
                'level': idx
            })

    return result


async def validate_commission_rate(parent_user_id, child_user_id, rate):
    """
    验证佣金比例设置是否合法

    Args:
        parent_user_id: 上级用户ID
        child_user_id: 下级用户ID
        rate: 要设置的佣金比例

    Returns:
        tuple: (是否合法, 错误信息)
    """
    # 1. 比例范围检查
    if rate < 0 or rate > 45:
        return False, "佣金比例必须在0-45%之间"

    # 2. 检查是否为直接下级
    child_chain = await ReferralChain.aio_get_or_none(
        ReferralChain.user_id == child_user_id
    )
    if not child_chain or child_chain.parent_user_id != parent_user_id:
        return False, "只能设置直接下级的佣金比例"

    # 3. 检查上级能获得的比例
    parent_chain = await ReferralChain.aio_get_or_none(
        ReferralChain.user_id == parent_user_id
    )

    if parent_chain and parent_chain.parent_user_id:
        # 有上级，需要检查上级给自己的比例
        parent_config = await CommissionConfig.aio_get_or_none(
            CommissionConfig.parent_user_id == parent_chain.parent_user_id,
            CommissionConfig.child_user_id == parent_user_id
        )
        max_rate = float(parent_config.commission_rate) if parent_config else 20.0
    else:
        # 顶级用户，最多45%
        max_rate = 45.0

    if rate > max_rate:
        return False, f"给下级的比例不能超过您能获得的比例({max_rate}%)"

    return True, ""
