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

OPENID = "o9n7P66kMb_mI68EV2ru0P2JmmPk"

# 微信支付商户号（直连模式）或服务商商户号（服务商模式，即sp_mchid)
MCHID = '1648741001'

APPSECRECT = "cf470bb039092b3d7672e241f984b7d9"
# 获取当前文件的绝对路径
file_path = os.path.abspath(__file__)

# 获取当前文件所在的目录
directory = os.path.dirname(file_path)

# 商户证书私钥
with open(os.path.join(directory,'apiclient_key.pem')) as f:
    PRIVATE_KEY = f.read()

# 商户证书序列号
CERT_SERIAL_NO = '4E4BC0E611B8DF18071DB8B5215CA305474CF931'

# API v3密钥， https://pay.weixin.qq.com/wiki/doc/apiv3/wechatpay/wechatpay3_2.shtml
APIV3_KEY = '8ze4ou2eBmpnYbAYheThghA3ZDsv2Cgs'

# APPID，应用ID或服务商模式下的sp_appid
APPID = 'wx50afdd19b43f590e'

# 回调地址，也可以在调用接口的时候覆盖
NOTIFY_URL = 'https://stellarsmart.cn/wechatbot_pay_notify'

# 微信支付平台证书缓存目录，减少证书下载调用次数，首次使用确保此目录为空目录.
# 初始调试时可不设置，调试通过后再设置，示例值:'./cert'
CERT_DIR = None

# 代理设置，None或者{"https": "http://10.10.1.10:1080"}，详细格式参见https://docs.python-requests.org/zh_CN/latest/user/advanced.html
PROXY = None

# 转账限额配置（单位：元）
TRANSFER_LIMITS = {
    "daily_total": 50000.00,     # 单日总转账额度
    "single_transfer": 200.00,   # 单笔转账额度
    "daily_to_user": 2000.00     # 单日向单用户转账额度
}

# 转账场景ID（需要根据实际场景设置）
TRANSFER_SCENE_ID = '1005'  # 示例值，需要根据实际业务设置

# 转账记录跟踪（用于控制限额）
_transfer_records = {
    "daily_total": 0.00,          # 今日已用总额度
    "user_records": {},           # 用户今日转账记录 {openid: amount}
    "last_reset_date": None       # 上次重置日期
}

# 初始化
wxpay = WeChatPay(
    wechatpay_type=WeChatPayType.JSAPI,
    mchid=MCHID,
    private_key=PRIVATE_KEY,
    cert_serial_no=CERT_SERIAL_NO,
    apiv3_key=APIV3_KEY,
    appid=APPID,
    notify_url=NOTIFY_URL,
    cert_dir=CERT_DIR,
    logger=None,  # 不使用logger
    partner_mode=False,
    proxy=PROXY)


def transfer_to_openid(openid, amount, out_bill_no=None, transfer_remark="转账", 
                      user_name=None, auto_split=True):
    """
    向指定openid转账（使用新接口 mch_transfer_bills）
    
    :param openid: 收款用户的openid
    :param amount: 转账总金额（单位：元）
    :param out_bill_no: 商户单号，不传则自动生成
    :param transfer_remark: 转账备注
    :param user_name: 收款用户姓名（转账金额 >= 2000元时必须填写）
    :param auto_split: 是否自动拆分超过限额的转账
    :return: (success, result) 成功状态和结果信息
    """
    try:
        # 检查限额
        amount_float = float(amount)
        
        # 检查是否超过单日向单用户限额
        user_daily_limit = check_user_daily_limit(openid, amount_float)
        if not user_daily_limit["can_transfer"]:
            return False, {
                "error": f"超过单日向该用户转账限额",
                "detail": user_daily_limit
            }
        
        # 检查是否超过单日总限额
        daily_total_limit = check_daily_total_limit(amount_float)
        if not daily_total_limit["can_transfer"]:
            return False, {
                "error": f"超过单日总转账限额",
                "detail": daily_total_limit
            }
        
        # 检查是否需要填写用户姓名（转账金额 >= 2000元）
        if amount_float >= 2000.00 and not user_name:
            return False, {
                "error": f"转账金额{amount_float}元超过2000元，必须填写收款用户姓名(user_name)",
                "detail": {"amount": amount_float, "required_name": True}
            }
        
        # 如果金额超过单笔限额且启用自动拆分
        if amount_float > TRANSFER_LIMITS["single_transfer"] and auto_split:
            print(f"金额{amount_float}元超过单笔限额，启用自动拆分")
            return split_and_transfer(openid, amount_float, out_bill_no, transfer_remark, user_name)
        
        # 直接转账（金额在限额内）
        if amount_float <= TRANSFER_LIMITS["single_transfer"]:
            return execute_single_transfer(openid, amount_float, out_bill_no, transfer_remark, user_name)
        else:
            return False, {
                "error": f"单笔转账金额{amount_float}元超过{TRANSFER_LIMITS['single_transfer']}元限额",
                "suggestion": "请启用auto_split参数自动拆分"
            }
            
    except ValueError as e:
        print(f"金额格式错误: {str(e)}")
        return False, {"error": "金额格式不正确"}
    except Exception as e:
        print(f"转账异常: {str(e)}")
        return False, {"error": str(e)}


def split_and_transfer(openid, total_amount, out_bill_no=None, transfer_remark="转账", user_name=None):
    """
    拆分大额转账为多笔小额转账
    
    :param openid: 收款用户的openid
    :param total_amount: 总金额（元）
    :param out_bill_no: 商户单号
    :param transfer_remark: 转账备注
    :param user_name: 收款用户姓名
    :return: 转账结果
    """
    # 计算需要拆分的笔数
    single_limit = TRANSFER_LIMITS["single_transfer"]
    num_transfers = ceil(total_amount / single_limit)
    
    # 计算每笔金额（最后一笔可能小于限额）
    base_amount = total_amount / num_transfers
    last_amount = total_amount - (base_amount * (num_transfers - 1))
    
    results = []
    batch_prefix = out_bill_no or f"TF{int(time.time())}{get_random_string(6)}"
    
    print(f"将{total_amount}元拆分为{num_transfers}笔转账，批次前缀: {batch_prefix}")
    
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
        user_check = check_user_daily_limit(openid, current_amount)
        daily_check = check_daily_total_limit(current_amount)
        
        if not user_check["can_transfer"] or not daily_check["can_transfer"]:
            print(f"第{i+1}笔转账因限额检查失败")
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
            openid, 
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
    
    print(f"拆分转账完成: 成功{success_count}笔，失败{num_transfers-success_count}笔，实际转账{total_transferred}元")
    
    # 更新转账记录
    if success_count > 0:
        update_transfer_records(openid, total_transferred)
    
    return success_count > 0, {
        "batch_prefix": batch_prefix,
        "total_amount": total_amount,
        "transferred_amount": total_transferred,
        "success_count": success_count,
        "failed_count": num_transfers - success_count,
        "results": results,
        "is_split": True
    }


def execute_single_transfer(openid, amount, out_bill_no=None, transfer_remark="转账", user_name=None):
    """
    执行单笔转账
    
    :param openid: 收款用户的openid
    :param amount: 转账金额（元）
    :param out_bill_no: 商户单号
    :param transfer_remark: 转账备注
    :param user_name: 收款用户姓名
    :return: 转账结果
    """
    try:
        # 生成商户单号（如果未提供）
        if not out_bill_no:
            out_bill_no = f"TF{int(time.time())}{get_random_string(8)}"
        
        # 转换金额为分
        transfer_amount = int(float(amount) * 100)
        
        print(f"执行转账: out_bill_no={out_bill_no}, openid={openid}, amount={amount}元")
        
        # 调用新的转账接口 mch_transfer_bills
        code, message = wxpay.mch_transfer_bills(
            out_bill_no=out_bill_no,
            transfer_scene_id=TRANSFER_SCENE_ID,
            openid=openid,
            transfer_amount=transfer_amount,
            transfer_remark=transfer_remark,
            user_name=user_name if amount >= 2000.00 else None,  # 超过2000元才传user_name,
            transfer_scene_report_infos= [{
    "info_type" :   "岗位类型",
    "info_content" : "推广员"
},{
    "info_type" : "报酬说明",
    "info_content" : "推广佣金"
  }]
        )
        
        print(f"转账结果 - code: {code}, message: {message}")
        
        # 解析返回结果
        if code == 200:
            response = json.loads(message)
            print(f"单笔转账成功: {response}")
            
            # 更新转账记录
            update_transfer_records(openid, amount)
            
            return True, {
                "transfer_bill_no": response.get("transfer_bill_no"),
                "out_bill_no": response.get("out_bill_no"),
                "create_time": response.get("create_time"),
                "amount": amount,
                "status": response.get("status")
            }
        else:
            print(f"单笔转账失败: {message}")
            return False, json.loads(message) if message else {"error": "转账失败"}
            
    except Exception as e:
        print(f"执行单笔转账异常: {str(e)}")
        return False, {"error": str(e)}


def cancel_transfer(out_bill_no):
    """
    撤销转账
    
    :param out_bill_no: 商户单号
    :return: (success, result) 成功状态和结果信息
    """
    try:
        print(f"尝试撤销转账: {out_bill_no}")
        code, message = wxpay.mch_transfer_bills_cancel(out_bill_no)
        
        if code == 200:
            response = json.loads(message) if message else {}
            print(f"撤销成功: {response}")
            return True, response
        else:
            print(f"撤销失败: {message}")
            return False, json.loads(message) if message else {"error": "撤销失败"}
    except Exception as e:
        print(f"撤销转账异常: {str(e)}")
        return False, {"error": str(e)}


def query_transfer(out_bill_no=None, transfer_bill_no=None):
    """
    查询转账单
    
    :param out_bill_no: 商户单号
    :param transfer_bill_no: 微信转账单号
    :return: (success, result) 查询结果
    """
    try:
        print(f"查询转账: out_bill_no={out_bill_no}, transfer_bill_no={transfer_bill_no}")
        code, message = wxpay.mch_transfer_bills_query(
            out_bill_no=out_bill_no,
            transfer_bill_no=transfer_bill_no
        )
        
        if code == 200:
            response = json.loads(message) if message else {}
            print(f"查询成功: {response}")
            return True, response
        else:
            print(f"查询失败: {message}")
            return False, json.loads(message) if message else {"error": "查询失败"}
    except Exception as e:
        print(f"查询转账异常: {str(e)}")
        return False, {"error": str(e)}


def check_user_daily_limit(openid, amount):
    """
    检查单日向单用户转账限额
    
    :param openid: 用户openid
    :param amount: 计划转账金额（元）
    :return: 检查结果字典
    """
    reset_daily_records()
    
    user_transferred = _transfer_records["user_records"].get(openid, 0.00)
    remaining = TRANSFER_LIMITS["daily_to_user"] - user_transferred
    
    can_transfer = amount <= remaining
    
    return {
        "can_transfer": can_transfer,
        "user_transferred": user_transferred,
        "daily_limit": TRANSFER_LIMITS["daily_to_user"],
        "remaining": remaining,
        "request_amount": amount
    }


def check_daily_total_limit(amount):
    """
    检查单日总转账限额
    
    :param amount: 计划转账金额（元）
    :return: 检查结果字典
    """
    reset_daily_records()
    
    daily_transferred = _transfer_records["daily_total"]
    remaining = TRANSFER_LIMITS["daily_total"] - daily_transferred
    
    can_transfer = amount <= remaining
    
    return {
        "can_transfer": can_transfer,
        "daily_transferred": daily_transferred,
        "daily_limit": TRANSFER_LIMITS["daily_total"],
        "remaining": remaining,
        "request_amount": amount
    }


def reset_daily_records():
    """
    重置每日转账记录（如果是新的一天）
    """
    today = datetime.now().date()
    
    if _transfer_records["last_reset_date"] != today:
        _transfer_records["daily_total"] = 0.00
        _transfer_records["user_records"] = {}
        _transfer_records["last_reset_date"] = today
        print(f"重置每日转账记录，新日期: {today}")


def update_transfer_records(openid, amount):
    """
    更新转账记录
    
    :param openid: 用户openid
    :param amount: 转账金额（元）
    """
    reset_daily_records()
    
    # 更新总转账记录
    _transfer_records["daily_total"] += amount
    
    # 更新用户转账记录
    if openid not in _transfer_records["user_records"]:
        _transfer_records["user_records"][openid] = 0.00
    _transfer_records["user_records"][openid] += amount
    
    print(f"更新转账记录: openid={openid}, amount={amount}, "
          f"daily_total={_transfer_records['daily_total']}, "
          f"user_total={_transfer_records['user_records'][openid]}")


def get_transfer_status():
    """
    获取当前转账状态
    
    :return: 状态信息字典
    """
    reset_daily_records()
    
    return {
        "current_date": _transfer_records["last_reset_date"].strftime("%Y-%m-%d") if _transfer_records["last_reset_date"] else "未记录",
        "daily_total_transferred": _transfer_records["daily_total"],
        "daily_total_remaining": TRANSFER_LIMITS["daily_total"] - _transfer_records["daily_total"],
        "user_records": _transfer_records["user_records"],
        "limits": TRANSFER_LIMITS
    }


def clear_transfer_records():
    """
    清空转账记录（用于测试或重置）
    """
    _transfer_records["daily_total"] = 0.00
    _transfer_records["user_records"] = {}
    _transfer_records["last_reset_date"] = None
    print("转账记录已清空")


def get_random_string(length=8):
    """生成随机字符串"""
    return ''.join(sample(ascii_letters + digits, length))


def pay_with_native_url(out_trade_no, amount):
    """创建支付链接"""
    description = 'AI 服务'
    amount = int(float(amount) / 0.01)
    print(f"make trade ,no:{out_trade_no} amount:{amount}")
    code, message = wxpay.pay(
        description=description,
        out_trade_no=out_trade_no,
        amount={'total': amount},
        pay_type=WeChatPayType.NATIVE
    )
    print(json.loads(message))
    wx_pay_url = json.loads(message)["code_url"]
    return wx_pay_url


def pay_with_native_qr(wechatcode, amount):
    """生成支付二维码"""
    out_trade_no = str(time.time()).split(".")[0] + "wx" + wechatcode
    description = 'AI 服务'
    amount = int(float(amount) / 0.01)
    print(out_trade_no)
    print(amount)
    code, message = wxpay.pay(
        description=description,
        out_trade_no=out_trade_no,
        amount={'total': amount},
        pay_type=WeChatPayType.NATIVE
    )
    print(json.loads(message))
    wx_pay_url = json.loads(message)["code_url"]
    save_path = os.path.join(setting.QRCODE_PATH, f"{wechatcode}.jpg")
    amzqr.run(
        wx_pay_url,
        save_name=save_path
    )
    return save_path


def make_trade_no():
    """生成交易单号"""
    key = get_random_bytes(16)
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
    print("=== 转账功能测试 ===")
    
    # 1. 测试小额转账（200元以内）
    print("\n1. 测试小额转账（150元）:")
    success, result = transfer_to_openid(
        openid=OPENID,
        amount="0.1",
        transfer_remark="测试小额转账"
    )
    print(f"结果: {'成功' if success else '失败'}")
    print(f"详情: {result}")
    
    # # 2. 测试大额转账（超过200元，自动拆分）
    # print("\n2. 测试大额转账（500元，自动拆分）:")
    # success, result = transfer_to_openid(
    #     openid=OPENID,
    #     amount="500.00",
    #     transfer_remark="测试大额转账",
    #     auto_split=True
    # )
    # print(f"结果: {'成功' if success else '失败'}")
    # print(f"详情: {result}")
    
    # # 3. 测试大额转账（超过2000元，需要姓名）
    # print("\n3. 测试大额转账（2500元，需要姓名）:")
    # success, result = transfer_to_openid(
    #     openid=OPENID,
    #     amount="2500.00",
    #     transfer_remark="测试大额转账",
    #     user_name="测试用户",
    #     auto_split=True
    # )
    # print(f"结果: {'成功' if success else '失败'}")
    # print(f"详情: {result}")
    
    # # 4. 查看当前转账状态
    # print("\n4. 当前转账状态:")
    # status = get_transfer_status()
    # print(f"今日已转账总额: {status['daily_total_transferred']}元")
    # print(f"今日剩余额度: {status['daily_total_remaining']}元")
    # print(f"当前用户今日已收: {status['user_records'].get(OPENID, 0)}元")
    
    # # 5. 测试限额检查
    # print("\n5. 测试限额检查（向同一用户转账1500元）:")
    # limit_check = check_user_daily_limit(OPENID, 1500.00)
    # print(f"是否可转账: {limit_check['can_transfer']}")
    # print(f"用户今日已收: {limit_check['user_transferred']}元")
    # print(f"剩余额度: {limit_check['remaining']}元")