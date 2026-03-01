"""
佣金分配工具函数
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

    # 5. 创建默认佣金配置（默认给下级20%）
    await CommissionConfig.aio_create(
        parent_user_id=parent_user.id,
        child_user_id=new_user_id,
        commission_rate=20.00
    )

    return True


async def distribute_multi_level_commission(order):
    """
    多级佣金分配 - 改进版

    算法逻辑：
    1. 直接推荐人获得固定比例（如20%）
    2. 上级们按层级递减分配剩余佣金

    示例：订单100元，总佣金45%=45元
    - B（直接推荐人）：获得20% = 20元
    - A（B的上级）：获得10% = 10元
    - 您（A的上级）：获得15% = 15元
    总计：45元

    配置说明：
    - commission_rate 表示"给下级的比例"
    - 上级实际获得 = 上级被分配的比例 - 给下级的比例
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
    commission_configs = {}
    for i in range(len(chain_user_ids) - 1):
        parent_id = chain_user_ids[i]
        child_id = chain_user_ids[i + 1]

        config = await CommissionConfig.aio_get_or_none(
            CommissionConfig.parent_user_id == parent_id,
            CommissionConfig.child_user_id == child_id
        )

        rate = float(config.commission_rate) if config else 20.0
        commission_configs[(parent_id, child_id)] = rate

    # 6. 分配佣金 - 新算法
    # 从最底层（推荐人）开始往上分配
    remaining_rate = total_commission_rate  # 剩余可分配的比例

    for i in range(len(chain_user_ids) - 1, -1, -1):
        user_id = chain_user_ids[i]

        if i == len(chain_user_ids) - 1:
            # 最底层（直接推荐人）
            if i > 0:
                parent_id = chain_user_ids[i - 1]
                my_rate = min(commission_configs.get((parent_id, user_id), 20.0), remaining_rate)
            else:
                # 推荐人就是顶级用户，拿全部
                my_rate = remaining_rate
        else:
            # 上级用户
            # 先看下级拿了多少
            child_id = chain_user_ids[i + 1]
            child_rate = commission_configs.get((user_id, child_id), 20.0)

            # 上级获得：自己被分配的比例 - 给下级的比例
            if i > 0:
                parent_id = chain_user_ids[i - 1]
                allocated_to_me = commission_configs.get((parent_id, user_id), 20.0)
                my_rate = max(0, allocated_to_me - child_rate)
            else:
                # 顶级用户，拿剩余的全部
                my_rate = remaining_rate

        remaining_rate -= my_rate

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
                f"用户{user_id}, 层级L{i}, 金额{commission_final}分, 比例{my_rate}%"
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
