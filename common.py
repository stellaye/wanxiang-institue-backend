import hashlib
import time
import random


def generate_unique_invite_code(user_id=None, length=8):
    """
    生成唯一邀请码
    :param user_id: 可选，用户ID（用于进一步确保唯一性）
    :param length: 邀请码长度，默认8位
    :return: 唯一邀请码字符串
    """
    # 1. 定义安全字符集（剔除易混淆字符：0/O, 1/I/l）
    safe_chars = '23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz'
    chars_length = len(safe_chars)
    
    # 2. 生成基础随机种子（毫秒级时间戳 + 随机数，确保唯一性）
    timestamp = int(time.time() * 1000)  # 毫秒级时间戳，避免秒级重复
    random_seed = random.randint(100000, 999999)  # 6位随机数
    base_number = timestamp + random_seed
    
    # 3. 如果传入用户ID，融合进种子（进一步确保唯一）
    if user_id is not None:
        base_number += int(user_id) * 1000000  # 放大用户ID，避免覆盖时间戳
    
    # 4. 将数字转换为自定义进制（压缩长度，提升可读性）
    invite_code = []
    while base_number > 0 and len(invite_code) < length:
        remainder = base_number % chars_length
        invite_code.append(safe_chars[remainder])
        base_number = base_number // chars_length
    
    # 5. 若长度不足，补充随机字符（确保固定长度）
    while len(invite_code) < length:
        invite_code.append(random.choice(safe_chars))
    
    # 6. 打乱顺序（避免邀请码尾部全是补充的随机字符）
    random.shuffle(invite_code)
    
    # 7. 拼接为最终邀请码
    return ''.join(invite_code)