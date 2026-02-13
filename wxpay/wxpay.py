# -*- coding: utf-8 -*-
import json
import os
import time
from Crypto.Random import get_random_bytes
from random import sample
from string import ascii_letters, digits
from math import ceil
from datetime import datetime, timedelta
from wechatpayv3 import SignType, WeChatPay, WeChatPayType
import uuid

# 多客户端配置（示例配置）
CLIENTS_CONFIG = {
    # 客户端1：主应用
    "web_app": {
        "name": "万象web",
        "appid": 'wxd642d4eeae08b232',
        "mchid": '1648741001',
        "apiv3_key": '8ze4ou2eBmpnYbAYheThghA3ZDsv2Cgs',
        "private_key": None,  # 会在初始化时加载
        "cert_serial_no": '4E4BC0E611B8DF18071DB8B5215CA305474CF931',
        "notify_url": 'https://stellarsmart.cn/wechatbot_pay_notify'
    },
    # 客户端2：子应用1
    "mobile_app": {
        "name": "移动端",
        "appid": 'wx50afdd19b43f590e',  # 替换为实际AppID
        "mchid": '1648741001',
        "apiv3_key":  '8ze4ou2eBmpnYbAYheThghA3ZDsv2Cgs',
        "private_key": None,
        "cert_serial_no": '4E4BC0E611B8DF18071DB8B5215CA305474CF931',
        "notify_url": 'https://stellarsmart.cn/wechatbot_pay_notify1'
    }
    # 可以添加更多客户端...
}

# 获取当前文件的绝对路径
file_path = os.path.abspath(__file__)
directory = os.path.dirname(file_path)


def generate_out_bill_no():
    """生成32位商户单号（无client_id）"""
    # 格式：前缀 + 时间戳 + 随机字符串
    
    # 1. 前缀（固定2位，如"TF"）
    prefix = "TF"
    
    # 2. 时间戳（毫秒级，13位数字）
    timestamp_ms = str(int(time.time() * 1000))  # 13位
    
    # 3. 计算需要多少随机字符
    # 总32 = 前缀2 + 时间戳13 + 随机串17
    random_len = 32 - len(prefix) - len(timestamp_ms)
    
    # 4. 生成随机部分
    random_part = get_random_string(random_len)
    
    # 5. 组合
    out_bill_no = f"{prefix}{timestamp_ms}{random_part}"
    
    return out_bill_no


# 加载每个客户端的私钥
for client_id, config in CLIENTS_CONFIG.items():
    key_file = os.path.join(directory, f'apiclient_key_{client_id}.pem')
    if os.path.exists(key_file):
        with open(key_file) as f:
            config["private_key"] = f.read()
    else:
        # 如果没找到专属文件，尝试使用通用文件
        key_file = os.path.join(directory, 'apiclient_key.pem')
        if os.path.exists(key_file):
            with open(key_file) as f:
                config["private_key"] = f.read()

# 转账限额配置（可以按客户端单独配置，也可以使用全局配置）
TRANSFER_LIMITS = {
    "global": {  # 全局默认限额
        "daily_total": 50000.00,     # 单日总转账额度
        "single_transfer": 200.00,   # 单笔转账额度
        "daily_to_user": 2000.00     # 单日向单用户转账额度
    },
    # 可以按客户端自定义限额
    "main_app": {
        "daily_total": 50000.00,
        "single_transfer": 200.00,
        "daily_to_user": 2000.00
    },
    "sub_app1": {
        "daily_total": 10000.00,     # 子应用限额较小
        "single_transfer": 100.00,
        "daily_to_user": 1000.00
    }
}

# 转账场景ID
TRANSFER_SCENE_ID = '1005'

# 初始化所有支付客户端
_wxpay_clients = {}

for client_id, config in CLIENTS_CONFIG.items():
    if config["private_key"]:
        try:
            wxpay = WeChatPay(
                wechatpay_type=WeChatPayType.JSAPI,
                mchid=config["mchid"],
                private_key=config["private_key"],
                cert_serial_no=config["cert_serial_no"],
                apiv3_key=config["apiv3_key"],
                appid=config["appid"],
                notify_url=config["notify_url"],
                cert_dir=None,
                logger=None,
                partner_mode=False,
                proxy=None
            )
            _wxpay_clients[client_id] = {
                "client": wxpay,
                "config": config
            }
            print(f"客户端 '{client_id}' ({config['name']}) 初始化成功")
        except Exception as e:
            print(f"客户端 '{client_id}' 初始化失败: {str(e)}")

# 默认客户端（第一个可用的）
DEFAULT_CLIENT = next(iter(_wxpay_clients.keys())) if _wxpay_clients else None

# 转账记录跟踪 - 按客户端存储
_transfer_records = {
    "clients": {},  # 按客户端存储记录
    "last_reset_date": None
}

def init_client_transfer_records(client_id):
    """初始化客户端的转账记录"""
    if client_id not in _transfer_records["clients"]:
        _transfer_records["clients"][client_id] = {
            "daily_total": 0.00,
            "user_records": {},  # {openid: amount}
            "last_reset_date": None
        }

def transfer_to_openid(openid, amount, client_id=DEFAULT_CLIENT, out_bill_no=None, 
                      transfer_remark="转账", user_name=None, auto_split=True):
    """
    向指定openid转账（区分客户端）
    
    :param openid: 收款用户的openid
    :param amount: 转账总金额（单位：元）
    :param client_id: 客户端标识，必须是CLIENTS_CONFIG中的key
    :param out_bill_no: 商户单号，不传则自动生成
    :param transfer_remark: 转账备注
    :param user_name: 收款用户姓名（转账金额 >= 2000元时必须填写）
    :param auto_split: 是否自动拆分超过限额的转账
    :return: (success, result) 成功状态和结果信息
    """
    try:
        # 检查客户端是否存在
        if client_id not in _wxpay_clients:
            available_clients = list(_wxpay_clients.keys())
            return False, {
                "error": f"客户端 '{client_id}' 不存在或未初始化",
                "available_clients": available_clients,
                "suggestion": f"请使用以下客户端之一: {available_clients}"
            }
        
        # 初始化该客户端的转账记录
        init_client_transfer_records(client_id)
        
        # 获取该客户端的限额配置
        client_limits = TRANSFER_LIMITS.get(client_id, TRANSFER_LIMITS["global"])
        
        # 检查限额
        amount_float = float(amount)
        
        # 检查是否超过单日向单用户限额
        user_daily_limit = check_user_daily_limit(client_id, openid, amount_float)
        if not user_daily_limit["can_transfer"]:
            return False, {
                "error": f"超过单日向该用户转账限额",
                "detail": user_daily_limit,
                "client_id": client_id
            }
        
        # 检查是否超过单日总限额
        daily_total_limit = check_daily_total_limit(client_id, amount_float)
        if not daily_total_limit["can_transfer"]:
            return False, {
                "error": f"超过单日总转账限额",
                "detail": daily_total_limit,
                "client_id": client_id
            }
        
        # 检查是否需要填写用户姓名（转账金额 >= 2000元）
        if amount_float >= 2000.00 and not user_name:
            return False, {
                "error": f"转账金额{amount_float}元超过2000元，必须填写收款用户姓名(user_name)",
                "detail": {"amount": amount_float, "required_name": True},
                "client_id": client_id
            }
        
        # 如果金额超过单笔限额且启用自动拆分
        if amount_float > client_limits["single_transfer"] and auto_split:
            print(f"客户端 '{client_id}' 金额{amount_float}元超过单笔限额{client_limits['single_transfer']}元，启用自动拆分")
            return split_and_transfer(client_id, openid, amount_float, out_bill_no, transfer_remark, user_name)
        
        # 直接转账（金额在限额内）
        if amount_float <= client_limits["single_transfer"]:
            return execute_single_transfer(client_id, openid, amount_float, out_bill_no, transfer_remark, user_name)
        else:
            return False, {
                "error": f"单笔转账金额{amount_float}元超过{client_limits['single_transfer']}元限额",
                "suggestion": "请启用auto_split参数自动拆分",
                "client_id": client_id
            }
            
    except ValueError as e:
        print(f"金额格式错误: {str(e)}")
        return False, {"error": "金额格式不正确", "client_id": client_id}
    except Exception as e:
        print(f"转账异常: {str(e)}")
        return False, {"error": str(e), "client_id": client_id}

def split_and_transfer(client_id, openid, total_amount, out_bill_no=None, 
                      transfer_remark="转账", user_name=None):
    """
    拆分大额转账为多笔小额转账
    
    :param client_id: 客户端标识
    :param openid: 收款用户的openid
    :param total_amount: 总金额（元）
    :param out_bill_no: 商户单号
    :param transfer_remark: 转账备注
    :param user_name: 收款用户姓名
    :return: 转账结果
    """
    # 获取客户端的限额配置
    client_limits = TRANSFER_LIMITS.get(client_id, TRANSFER_LIMITS["global"])
    
    # 计算需要拆分的笔数
    single_limit = client_limits["single_transfer"]
    num_transfers = ceil(total_amount / single_limit)
    
    # 计算每笔金额
    base_amount = total_amount / num_transfers
    last_amount = total_amount - (base_amount * (num_transfers - 1))
    
    results = []
    batch_prefix = out_bill_no or f"TF{client_id}_{int(time.time())}{get_random_string(6)}"
    
    print(f"客户端 '{client_id}' 将{total_amount}元拆分为{num_transfers}笔转账，批次前缀: {batch_prefix}")
    
    for i in range(num_transfers):
        # 计算当前笔次的金额
        if i == num_transfers - 1:
            current_amount = round(last_amount, 2)
        else:
            current_amount = round(base_amount, 2)
        
        # 生成商户单号
        current_out_bill_no = f"{batch_prefix}_{i+1:03d}"
        
        # 生成明细备注
        current_remark = f"{transfer_remark} ({i+1}/{num_transfers})"
        
        # 检查限额（动态检查）
        user_check = check_user_daily_limit(client_id, openid, current_amount)
        daily_check = check_daily_total_limit(client_id, current_amount)
        
        if not user_check["can_transfer"] or not daily_check["can_transfer"]:
            print(f"客户端 '{client_id}' 第{i+1}笔转账因限额检查失败")
            results.append({
                "success": False,
                "index": i+1,
                "amount": current_amount,
                "out_bill_no": current_out_bill_no,
                "error": "限额检查失败",
                "user_check": user_check,
                "daily_check": daily_check
            })
            continue
        
        # 执行单笔转账
        success, result = execute_single_transfer(
            client_id, openid, 
            current_amount, 
            current_out_bill_no, 
            current_remark,
            user_name
        )
        
        results.append({
            "success": success,
            "index": i+1,
            "amount": current_amount,
            "out_bill_no": current_out_bill_no,
            "result": result
        })
        
        # 等待一小段时间，避免请求过于频繁
        if i < num_transfers - 1:
            time.sleep(0.5)
    
    # 统计结果
    success_count = sum(1 for r in results if r["success"])
    total_transferred = sum(r["amount"] for r in results if r["success"])
    
    print(f"客户端 '{client_id}' 拆分转账完成: 成功{success_count}笔，失败{num_transfers-success_count}笔，实际转账{total_transferred}元")
    
    # 更新转账记录
    if success_count > 0:
        update_transfer_records(client_id, openid, total_transferred)
    
    return success_count > 0, {
        "client_id": client_id,
        "batch_prefix": batch_prefix,
        "total_amount": total_amount,
        "transferred_amount": total_transferred,
        "success_count": success_count,
        "failed_count": num_transfers - success_count,
        "results": results,
        "is_split": True
    }

def execute_single_transfer(client_id, openid, amount, out_bill_no=None, 
                           transfer_remark="转账", user_name=None):
    """
    执行单笔转账
    
    :param client_id: 客户端标识
    :param openid: 收款用户的openid
    :param amount: 转账金额（元）
    :param out_bill_no: 商户单号
    :param transfer_remark: 转账备注
    :param user_name: 收款用户姓名
    :return: 转账结果
    """
    try:
        # 检查客户端
        if client_id not in _wxpay_clients:
            return False, {"error": f"客户端 '{client_id}' 不存在"}
        
        wxpay = _wxpay_clients[client_id]["client"]
        client_config = _wxpay_clients[client_id]["config"]
        
        # 生成商户单号（如果未提供）
        if not out_bill_no:
            out_bill_no = generate_out_bill_no()
        
        # 转换金额为分
        transfer_amount = int(float(amount) * 100)
        
        print(f"客户端 '{client_id}' 执行转账: out_bill_no={out_bill_no}, openid={openid}, amount={amount}元, AppID={client_config['appid']}")
        
        # 调用转账接口
        code, message = wxpay.mch_transfer_bills(
            out_bill_no=out_bill_no,
            transfer_scene_id=TRANSFER_SCENE_ID,
            openid=openid,
            transfer_amount=transfer_amount,
            transfer_remark=transfer_remark,
            user_name=user_name if amount >= 2000.00 else None,
            transfer_scene_report_infos=[{
                "info_type": "岗位类型",
                "info_content": "推广员"
            }, {
                "info_type": "报酬说明",
                "info_content": "推广佣金"
            }]
        )
        
        print(f"客户端 '{client_id}' 转账结果 - code: {code}, message: {message}")
        
        # 解析返回结果
        if code == 200:
            response = json.loads(message)
            print(f"客户端 '{client_id}' 单笔转账成功: {response}")
            
            # 更新转账记录
            update_transfer_records(client_id, openid, amount)
            
            return True, {
                "client_id": client_id,
                "appid": client_config['appid'],
                "transfer_bill_no": response.get("transfer_bill_no"),
                "out_bill_no": response.get("out_bill_no"),
                "create_time": response.get("create_time"),
                "amount": amount,
                "state": response.get("state"),
                "package_info": response.get('package_info', '')  
            }
        else:
            print(f"客户端 '{client_id}' 单笔转账失败: {message}")
            return False, json.loads(message) if message else {"error": "转账失败", "client_id": client_id}
            
    except Exception as e:
        print(f"客户端 '{client_id}' 执行单笔转账异常: {str(e)}")
        return False, {"error": str(e), "client_id": client_id}

def cancel_transfer(client_id, out_bill_no):
    """
    撤销转账
    
    :param client_id: 客户端标识
    :param out_bill_no: 商户单号
    :return: (success, result) 成功状态和结果信息
    """
    try:
        if client_id not in _wxpay_clients:
            return False, {"error": f"客户端 '{client_id}' 不存在"}
        
        wxpay = _wxpay_clients[client_id]["client"]
        
        print(f"客户端 '{client_id}' 尝试撤销转账: {out_bill_no}")
        code, message = wxpay.mch_transfer_bills_cancel(out_bill_no)
        
        if code == 200:
            response = json.loads(message) if message else {}
            print(f"客户端 '{client_id}' 撤销成功: {response}")
            return True, response
        else:
            print(f"客户端 '{client_id}' 撤销失败: {message}")
            return False, json.loads(message) if message else {"error": "撤销失败", "client_id": client_id}
    except Exception as e:
        print(f"客户端 '{client_id}' 撤销转账异常: {str(e)}")
        return False, {"error": str(e), "client_id": client_id}

def query_transfer(client_id, out_bill_no=None, transfer_bill_no=None):
    """
    查询转账单
    
    :param client_id: 客户端标识
    :param out_bill_no: 商户单号
    :param transfer_bill_no: 微信转账单号
    :return: (success, result) 查询结果
    """
    try:
        if client_id not in _wxpay_clients:
            return False, {"error": f"客户端 '{client_id}' 不存在"}
        
        wxpay = _wxpay_clients[client_id]["client"]
        
        print(f"客户端 '{client_id}' 查询转账: out_bill_no={out_bill_no}, transfer_bill_no={transfer_bill_no}")
        code, message = wxpay.mch_transfer_bills_query(
            out_bill_no=out_bill_no,
            transfer_bill_no=transfer_bill_no
        )
        
        if code == 200:
            response = json.loads(message) if message else {}
            print(f"客户端 '{client_id}' 查询成功: {response}")
            return True, response
        else:
            print(f"客户端 '{client_id}' 查询失败: {message}")
            return False, json.loads(message) if message else {"error": "查询失败", "client_id": client_id}
    except Exception as e:
        print(f"客户端 '{client_id}' 查询转账异常: {str(e)}")
        return False, {"error": str(e), "client_id": client_id}

def check_user_daily_limit(client_id, openid, amount):
    """
    检查单日向单用户转账限额
    
    :param client_id: 客户端标识
    :param openid: 用户openid
    :param amount: 计划转账金额（元）
    :return: 检查结果字典
    """
    # 初始化客户端记录
    init_client_transfer_records(client_id)
    
    # 重置每日记录（如果是新的一天）
    reset_daily_records(client_id)
    
    # 获取限额配置
    client_limits = TRANSFER_LIMITS.get(client_id, TRANSFER_LIMITS["global"])
    
    client_records = _transfer_records["clients"][client_id]
    user_transferred = client_records["user_records"].get(openid, 0.00)
    remaining = client_limits["daily_to_user"] - user_transferred
    
    can_transfer = amount <= remaining
    
    return {
        "can_transfer": can_transfer,
        "client_id": client_id,
        "user_transferred": user_transferred,
        "daily_limit": client_limits["daily_to_user"],
        "remaining": remaining,
        "request_amount": amount
    }

def check_daily_total_limit(client_id, amount):
    """
    检查单日总转账限额
    
    :param client_id: 客户端标识
    :param amount: 计划转账金额（元）
    :return: 检查结果字典
    """
    # 初始化客户端记录
    init_client_transfer_records(client_id)
    
    # 重置每日记录（如果是新的一天）
    reset_daily_records(client_id)
    
    # 获取限额配置
    client_limits = TRANSFER_LIMITS.get(client_id, TRANSFER_LIMITS["global"])
    
    client_records = _transfer_records["clients"][client_id]
    daily_transferred = client_records["daily_total"]
    remaining = client_limits["daily_total"] - daily_transferred
    
    can_transfer = amount <= remaining
    
    return {
        "can_transfer": can_transfer,
        "client_id": client_id,
        "daily_transferred": daily_transferred,
        "daily_limit": client_limits["daily_total"],
        "remaining": remaining,
        "request_amount": amount
    }

def reset_daily_records(client_id=None):
    """
    重置每日转账记录（如果是新的一天）
    
    :param client_id: 客户端标识，None表示重置所有客户端
    """
    today = datetime.now().date()
    
    if client_id:
        # 重置指定客户端
        if client_id in _transfer_records["clients"]:
            client_records = _transfer_records["clients"][client_id]
            if client_records["last_reset_date"] != today:
                client_records["daily_total"] = 0.00
                client_records["user_records"] = {}
                client_records["last_reset_date"] = today
                print(f"客户端 '{client_id}' 重置每日转账记录，新日期: {today}")
    else:
        # 重置所有客户端
        for cid in _transfer_records["clients"]:
            client_records = _transfer_records["clients"][cid]
            if client_records["last_reset_date"] != today:
                client_records["daily_total"] = 0.00
                client_records["user_records"] = {}
                client_records["last_reset_date"] = today
                print(f"客户端 '{cid}' 重置每日转账记录，新日期: {today}")

def update_transfer_records(client_id, openid, amount):
    """
    更新转账记录
    
    :param client_id: 客户端标识
    :param openid: 用户openid
    :param amount: 转账金额（元）
    """
    # 确保客户端记录已初始化
    init_client_transfer_records(client_id)
    
    # 重置每日记录（如果是新的一天）
    reset_daily_records(client_id)
    
    client_records = _transfer_records["clients"][client_id]
    
    # 更新总转账记录
    client_records["daily_total"] += amount
    
    # 更新用户转账记录
    if openid not in client_records["user_records"]:
        client_records["user_records"][openid] = 0.00
    client_records["user_records"][openid] += amount
    
    print(f"客户端 '{client_id}' 更新转账记录: openid={openid}, amount={amount}, "
          f"daily_total={client_records['daily_total']}, "
          f"user_total={client_records['user_records'][openid]}")

def get_transfer_status(client_id=None):
    """
    获取当前转账状态
    
    :param client_id: 客户端标识，None表示获取所有客户端状态
    :return: 状态信息字典
    """
    reset_daily_records(client_id)
    
    if client_id:
        # 获取指定客户端状态
        if client_id not in _transfer_records["clients"]:
            return {"error": f"客户端 '{client_id}' 不存在"}
        
        client_records = _transfer_records["clients"][client_id]
        client_limits = TRANSFER_LIMITS.get(client_id, TRANSFER_LIMITS["global"])
        
        return {
            "client_id": client_id,
            "client_name": CLIENTS_CONFIG.get(client_id, {}).get("name", "未知"),
            "appid": CLIENTS_CONFIG.get(client_id, {}).get("appid", "未知"),
            "current_date": client_records["last_reset_date"].strftime("%Y-%m-%d") if client_records["last_reset_date"] else "未记录",
            "daily_total_transferred": client_records["daily_total"],
            "daily_total_remaining": client_limits["daily_total"] - client_records["daily_total"],
            "user_records": client_records["user_records"],
            "limits": client_limits
        }
    else:
        # 获取所有客户端状态
        status = {
            "clients": {},
            "global_summary": {
                "total_daily_transferred": 0.00,
                "total_daily_remaining": 0.00
            }
        }
        
        for cid in _transfer_records["clients"]:
            client_status = get_transfer_status(cid)
            if "error" not in client_status:
                status["clients"][cid] = client_status
                status["global_summary"]["total_daily_transferred"] += client_status["daily_total_transferred"]
                status["global_summary"]["total_daily_remaining"] += client_status["daily_total_remaining"]
        
        return status

def clear_transfer_records(client_id=None):
    """
    清空转账记录（用于测试或重置）
    
    :param client_id: 客户端标识，None表示清空所有客户端
    """
    if client_id:
        if client_id in _transfer_records["clients"]:
            _transfer_records["clients"][client_id]["daily_total"] = 0.00
            _transfer_records["clients"][client_id]["user_records"] = {}
            _transfer_records["clients"][client_id]["last_reset_date"] = None
            print(f"客户端 '{client_id}' 转账记录已清空")
    else:
        _transfer_records["clients"] = {}
        _transfer_records["last_reset_date"] = None
        print("所有客户端转账记录已清空")

def get_random_string(length=8):
    """生成随机字符串"""
    return ''.join(sample(ascii_letters + digits, length))

def get_available_clients():
    """获取可用的客户端列表"""
    return list(_wxpay_clients.keys())

def get_client_info(client_id):
    """获取客户端信息（不包含敏感信息）"""
    if client_id in CLIENTS_CONFIG:
        config = CLIENTS_CONFIG[client_id].copy()
        # 移除敏感信息
        if "private_key" in config:
            del config["private_key"]
        if "apiv3_key" in config:
            del config["apiv3_key"]
        return config
    return None

# 保持原有的支付函数，添加客户端参数
def pay_with_native_url(out_trade_no, amount, client_id=DEFAULT_CLIENT):
    """创建支付链接"""
    if client_id not in _wxpay_clients:
        raise ValueError(f"客户端 '{client_id}' 不存在")
    
    wxpay = _wxpay_clients[client_id]["client"]
    
    description = 'AI 服务'
    amount = int(float(amount) / 0.01)
    print(f"客户端 '{client_id}' 创建支付链接, no:{out_trade_no} amount:{amount}")
    code, message = wxpay.pay(
        description=description,
        out_trade_no=out_trade_no,
        amount={'total': amount},
        pay_type=WeChatPayType.NATIVE
    )
    print(json.loads(message))
    wx_pay_url = json.loads(message)["code_url"]
    return wx_pay_url

def make_trade_no():
    """生成交易单号"""
    key = get_random_bytes(16)
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    
    cipher = AES.new(key, AES.MODE_ECB)
    timestamp = int(time.time())
    
    def int_to_bytes(timestamp):
        return timestamp.to_bytes(8, byteorder='big')
    
    bytes_data = int_to_bytes(timestamp)
    data = bytes_data
    padded_data = pad(data, 16)
    ciphertext = cipher.encrypt(padded_data)
    return ciphertext.hex()

if __name__ == '__main__':
    print("=== 多客户端转账功能测试 ===")
    
    # 显示可用客户端
    available_clients = get_available_clients()
    print(f"可用客户端: {available_clients}")
    
    if not available_clients:
        print("错误: 没有可用的支付客户端")
        exit(1)
    
    # 测试用OpenID
    TEST_OPENID = "o9n7P66kMb_mI68EV2ru0P2JmmPk"
    
    # 1. 测试默认客户端小额转账
    print(f"\n1. 测试默认客户端('{DEFAULT_CLIENT}')小额转账:")
    success, result = transfer_to_openid(
        openid=TEST_OPENID,
        amount="0.1",
        client_id=DEFAULT_CLIENT,
        transfer_remark="测试多客户端转账"
    )
    print(f"结果: {'成功' if success else '失败'}")
    print(f"详情: {result}")
    
    # 2. 查看所有客户端状态
    print(f"\n2. 查看所有客户端状态:")
    status = get_transfer_status()
    for client_id, client_status in status.get("clients", {}).items():
        print(f"客户端 '{client_id}':")
        print(f"  今日已转账: {client_status['daily_total_transferred']}元")
        print(f"  今日剩余额度: {client_status['daily_total_remaining']}元")
    
    # 3. 测试限额检查
    print(f"\n3. 测试限额检查:")
    limit_check = check_user_daily_limit(DEFAULT_CLIENT, TEST_OPENID, 1500.00)
    print(f"客户端 '{DEFAULT_CLIENT}' 向用户转账1500元:")
    print(f"  是否可转账: {limit_check['can_transfer']}")
    print(f"  用户今日已收: {limit_check['user_transferred']}元")
    print(f"  剩余额度: {limit_check['remaining']}元")
    
    # 4. 测试客户端信息获取
    print(f"\n4. 客户端信息:")
    for client_id in available_clients:
        info = get_client_info(client_id)
        if info:
            print(f"  客户端 '{client_id}': {info.get('name')}, AppID: {info.get('appid')}")