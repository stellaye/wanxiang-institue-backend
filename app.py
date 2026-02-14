import tornado.ioloop
import tornado.web
import json
from logger import logger
import tornado.httpclient  # 这是解决错误的关键
from models import User,Order,Product,UserProductPrice,Report
from wxpay.wxpay import transfer_to_openid
import hashlib
import time
import string
import random
# wechat_pay_backend.py
# 微信支付 JSAPI 后端 (Python Tornado)
# 包含：下单、签名、回调通知、查单
import json
import time
import uuid
import hashlib
import logging
import tornado.web
import tornado.ioloop
import tornado.httpclient
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.x509 import load_pem_x509_certificate
import os
import base64
import time
import json
import tornado.web
from logger import logger
from common import generate_unique_invite_code
import datetime
import traceback
from reports.report_2026 import generate_full_report
from bazi.bazi_common import get_bazi_natal_info
import asyncio


logger = logging.getLogger(__name__)
current_dir = os.path.dirname(os.path.abspath(__file__))
key_path = os.path.join(os.path.join(current_dir,"wxpay"),"apiclient_key.pem")




# 商品价格（单位：分）
PRODUCT_PRICE_FEN = 990  # ¥9.9 = 990分

# ============================================================
# 配置 - 请替换为你的真实配置
# ============================================================
WECHAT_PAY_CONFIG = {
    "appid": "wx50afdd19b43f590e",           # 公众号 AppID
    "mchid": "1648741001",                # 商户号
    "notify_url": "https://stellarsmart.cn/wanxiang/api/wechat/pay/notify",  # 回调地址(必须https)
    "apiclient_key_path": key_path,      # 商户API私钥路径
    "mch_serial_no": "4E4BC0E611B8DF18071DB8B5215CA305474CF931",                      # 商户证书序列号
    "apiV3_key": "8ze4ou2eBmpnYbAYheThghA3ZDsv2Cgs",                              # APIv3密钥(用于解密回调)
    "wechat_cert_path": None,        # 微信平台证书路径(验签用)
}


_report_tasks = {}

class LoggedRequestHandler(tornado.web.RequestHandler):
    """带请求/响应日志的基类，替换原有 MainHandler 作为所有 Handler 的父类"""

    def prepare(self):
        """请求进入时打印日志"""
        self._start_time = time.time()
        # 基本信息
        logger.info(
            f"[REQ] {self.request.method} {self.request.uri} "
            f"| IP: {self.request.remote_ip} "
            f"| Content-Length: {len(self.request.body) if self.request.body else 0}"
        )
        # 打印请求头（可选，按需开启）
        # logger.debug(f"[REQ HEADERS] {dict(self.request.headers)}")

        # 打印请求体（POST/PUT 等有 body 的请求）
        if self.request.body:
            body_str = self.request.body.decode("utf-8", errors="replace")
            # 截断过长的 body，防止日志爆炸
            if len(body_str) > 2000:
                body_str = body_str[:2000] + "...(truncated)"
            logger.info(f"[REQ BODY] {body_str}")

    def on_finish(self):
        """请求结束时打印响应日志"""
        duration = (time.time() - self._start_time) * 1000  # 毫秒
        logger.info(
            f"[RES] {self.request.method} {self.request.uri} "
            f"| Status: {self.get_status()} "
            f"| Duration: {duration:.1f}ms"
        )

    def write_json(self, data):
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(data, ensure_ascii=False))

    def write_error_json(self, msg, code=400):
        self.set_status(code)
        self.write_json({"success": False, "msg": msg})


# 全局缓存 jsapi_ticket
jsapi_ticket_cache = {"ticket": "", "expires_at": 0}


def parse_wx_time_to_datetime(time_str):
    """
    将微信的 ISO 8601 时间字符串转为 datetime 对象
    例如: '2026-02-14T16:22:39+08:00' -> datetime(2026, 2, 14, 16, 22, 39)
    """
    if not time_str:
        return None
    try:
        dt = datetime.datetime.fromisoformat(time_str)
        return dt.replace(tzinfo=None)  # 去掉时区信息，存本地时间
    except Exception:
        try:
            dt = datetime.datetime.strptime(time_str[:19], "%Y-%m-%dT%H:%M:%S")
            return dt
        except Exception:
            return None


class PayNotifyHandler(LoggedRequestHandler):
    """
    微信支付结果回调通知（已修复）
    """

    async def post(self):
        try:
            notify_data = json.loads(self.request.body)
            logger.info(f"收到微信支付回调: {notify_data}")

            resource = notify_data.get("resource", {})
            plaintext = decrypt_aes_gcm(
                nonce=resource["nonce"],
                ciphertext=resource["ciphertext"],
                associated_data=resource.get("associated_data", ""),
            )
            payment_info = json.loads(plaintext)
            logger.info(f"解密后的支付信息: {payment_info}")

            # ========== 提现回调 ==========
            if notify_data["event_type"] == "MCHTRANSFER.BILL.FINISHED":
                state = payment_info["state"]
                out_trade_no = payment_info["out_bill_no"]
                target_order = await Order.aio_get_or_none(Order.out_trade_no == out_trade_no)

                if target_order:
                    if state == "SUCCESS" and target_order.status != "SUCCESS":
                        target_order.status = state
                        target_order.transaction_id = payment_info.get("transfer_bill_no", "")
                        # 【修复】存 datetime
                        update_time_str = payment_info.get("update_time", "") or payment_info.get("create_time", "")
                        target_order.pay_time = parse_wx_time_to_datetime(update_time_str)
                        await target_order.aio_save()

                        target_user = await User.aio_get_or_none(User.id == target_order.user_id)
                        if target_user:
                            origin_balance = target_user.balance or 0
                            new_balance = origin_balance - payment_info["transfer_amount"]
                            target_user.balance = max(new_balance, 0)
                            await target_user.aio_save()
                    elif state != "SUCCESS":
                        target_order.status = state
                        await target_order.aio_save()

            # ========== 支付回调 ==========
            if notify_data["event_type"] == "TRANSACTION.SUCCESS":
                out_trade_no = payment_info["out_trade_no"]
                trade_state = payment_info["trade_state"]
                target_order = await Order.aio_get_or_none(Order.out_trade_no == out_trade_no)

                if target_order:
                    old_status = target_order.status
                    target_order.status = trade_state

                    if trade_state == "SUCCESS" and old_status != "SUCCESS":
                        target_order.transaction_id = payment_info.get("transaction_id", "")
                        # 【修复】用 payment_info 的 success_time，不是 notify_data 的 create_time
                        success_time_str = payment_info.get("success_time", "") or notify_data.get("create_time", "")
                        target_order.pay_time = parse_wx_time_to_datetime(success_time_str)
                        logger.info(f"订单支付成功: {out_trade_no}, pay_time={target_order.pay_time}")

                    await target_order.aio_save()

                    if trade_state == "SUCCESS" and old_status != "SUCCESS" and target_order.ref_code:
                        ref_user = await User.aio_get_or_none(User.ref_code == target_order.ref_code)
                        if ref_user:
                            commission_rate = 45
                            price = target_order.amount
                            commission_fen = price * commission_rate / 100
                            commission_yuan = round(commission_fen / 100)
                            commission_final = commission_yuan * 100
                            ref_user.balance = (ref_user.balance or 0) + commission_final
                            ref_user.total_earned = (ref_user.total_earned or 0) + commission_final
                            await ref_user.aio_save()

            self.set_status(200)
            self.write({"code": "SUCCESS", "message": "成功"})

        except Exception as e:
            logger.exception("处理支付回调失败")
            self.set_status(500)
            self.write({"code": "FAIL", "message": str(e)})


class WithdrawHandler(LoggedRequestHandler):
    """提现接口（已修复）"""

    async def post(self):
        try:
            body = json.loads(self.request.body)
            login_type = body.get("login_type")
            openid = body.get("openid")
            amount = body.get("amount")  # 前端传的是元（如 200）

            if not openid or not amount:
                self.write_json({"success": False, "msg": "缺少必要参数"})
                return

            if login_type == "mobile":
                user = await User.aio_get_or_none(User.mobile_openid == openid)
            else:
                user = await User.aio_get_or_none(User.web_openid == openid)

            if not user:
                self.write_json({"success": False, "msg": "用户不存在"})
                return

            if login_type == "mobile":
                client_id = "mobile_app"
                app_id = WX_MP_APP_ID
            else:
                client_id = "web_app"
                app_id = WX_OPEN_APP_ID

            # 【修复】前端传的 amount 是元，转换为分
            amount_yuan = float(amount)
            amount_fen = int(amount_yuan * 100)

            out_bill_no = generate_out_trade_no()

            # transfer_to_openid 的 amount 参数单位需要确认
            # 如果 transfer_to_openid 接受的是分，传 amount_fen
            # 如果接受的是元，传 amount_yuan
            # 根据微信转账API，amount 单位是「分」
            raw_result = transfer_to_openid(
                openid=openid,
                amount=amount_yuan,
                out_bill_no=out_bill_no,
                client_id=client_id,
                notify_url=WECHAT_PAY_CONFIG["notify_url"]
            )
            logger.info(f"转账结果: {raw_result}")

            # 【修复】创建订单时 amount 存分
            newOrder = Order(
                out_trade_no=out_bill_no,
                amount=amount_fen,        # 单位：分
                order_name="提现",
                user_id=user.id,
                status="NOTPAY"
            )
            await newOrder.aio_save(force_insert=True)

            if isinstance(raw_result, tuple):
                success, result = raw_result
            else:
                success = False
                result = raw_result

            if not success or not result:
                self.write_json({"success": False, "msg": raw_result[1]["code"]})
                return

            package_info = result.get("package_info", "")
            state = result.get("status") or result.get("state", "")

            if package_info and state in ("WAIT_USER_CONFIRM", None):
                self.write_json({
                    "success": True,
                    "msg": "转账已发起，请确认收款",
                    "package_info": package_info,
                    "mch_id": "1648741001",
                    "app_id": app_id,
                })
            else:
                self.write_json({
                    "success": True,
                    "msg": "提现成功",
                    "direct": True
                })

        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f"提现接口异常: {e}")
            self.write_json({"success": False, "msg": f"服务器异常: {str(e)}"})


# ============================================================
# OrderListHandler 也需要修复时间格式化
# pay_time 现在是 int 时间戳，需要转为可读字符串
# ============================================================

class OrderListHandler(LoggedRequestHandler):

    async def get(self):
        openid = self.get_argument("openid", "")
        login_type = self.get_argument("login_type", "mobile")
        page = max(int(self.get_argument("page", "1")), 1)
        page_size = min(max(int(self.get_argument("page_size", "15")), 1), 50)
        offset = (page - 1) * page_size

        if not openid:
            self.write_json({"success": False, "msg": "缺少openid"})
            return

        if login_type == "mobile":
            user = await User.aio_get_or_none(User.mobile_openid == openid)
        else:
            user = await User.aio_get_or_none(User.web_openid == openid)

        if not user:
            self.write_json({"success": True, "orders": [], "total": 0, "has_more": False})
            return

        ref_code = user.ref_code
        if not ref_code:
            self.write_json({"success": True, "orders": [], "total": 0, "has_more": False})
            return

        try:
            total = await (Order
                .select(fn.COUNT(Order.id))
                .where(
                    Order.ref_code == ref_code,
                    Order.status == 'SUCCESS',
                    Order.order_name != '提现'
                )
                .aio_scalar()) or 0

            rows = await (Order
                .select()
                .where(
                    Order.ref_code == ref_code,
                    Order.status == 'SUCCESS',
                    Order.order_name != '提现'
                )
                .order_by(Order.id.desc())
                .offset(offset)
                .limit(page_size)
                .aio_execute())

            orders = []
            for o in rows:
                commission_rate = 45
                price = o.amount or 0
                commission_fen = price * commission_rate / 100
                commission_yuan = round(commission_fen / 100)
                commission_final = commission_yuan * 100

                buyer_nickname = ""
                if o.user_id:
                    try:
                        buyer = await User.aio_get_or_none(User.id == o.user_id)
                        if buyer:
                            buyer_nickname = buyer.nickname or ""
                    except Exception:
                        pass

                # 【修复】pay_time 是 int 时间戳，转为可读字符串
                pay_time_str = ""
                if o.pay_time and isinstance(o.pay_time, datetime.datetime):
                    pay_time_str = o.pay_time.strftime('%Y-%m-%d %H:%M:%S')
                elif o.pay_time:
                    pay_time_str = str(o.pay_time)


                orders.append({
                    "id": o.id,
                    "order_no": o.out_trade_no,
                    "product_name": o.order_name or "未知产品",
                    "product_icon": "📦",
                    "paid_amount": int(o.amount or 0),
                    "commission": int(commission_final),
                    "commission_rate": commission_rate,
                    "paid_at": pay_time_str,
                    "buyer_nickname": buyer_nickname,
                })

            self.write_json({
                "success": True,
                "orders": orders,
                "total": int(total),
                "has_more": (offset + page_size) < int(total),
            })

        except Exception as e:
            logger.error(f"获取订单列表失败: {e}")
            logger.error(traceback.format_exc())
            self.write_json({"success": False, "msg": "服务器错误"})


# ============================================================
# WithdrawalListHandler 也修复时间
# ============================================================

class WithdrawalListHandler(LoggedRequestHandler):

    async def get(self):
        openid = self.get_argument("openid", "")
        login_type = self.get_argument("login_type", "mobile")
        page = max(int(self.get_argument("page", "1")), 1)
        page_size = min(max(int(self.get_argument("page_size", "15")), 1), 50)
        offset = (page - 1) * page_size

        if not openid:
            self.write_json({"success": False, "msg": "缺少openid"})
            return

        if login_type == "mobile":
            user = await User.aio_get_or_none(User.mobile_openid == openid)
        else:
            user = await User.aio_get_or_none(User.web_openid == openid)

        if not user:
            self.write_json({"success": True, "withdrawals": [], "total": 0, "has_more": False})
            return

        try:
            total = await (Order
                .select(fn.COUNT(Order.id))
                .where(
                    Order.user_id == user.id,
                    Order.order_name == '提现',
                    Order.status == 'SUCCESS'
                )
                .aio_scalar()) or 0

            rows = await (Order
                .select()
                .where(
                    Order.user_id == user.id,
                    Order.order_name == '提现',
                    Order.status == 'SUCCESS'
                )
                .order_by(Order.id.desc())
                .offset(offset)
                .limit(page_size)
                .aio_execute())

            withdrawals = []
            for o in rows:
                # 【修复】pay_time 是 int 时间戳
                created_str = ""
                if o.pay_time and isinstance(o.pay_time, datetime.datetime):
                    created_str = o.pay_time.strftime('%Y-%m-%d %H:%M:%S')
                elif o.pay_time:
                    created_str = str(o.pay_time)

                withdrawals.append({
                    "id": o.id,
                    "order_no": o.out_trade_no,
                    "amount": int(o.amount or 0),   # 单位：分
                    "status": "success",
                    "created_at": created_str,
                })

            self.write_json({
                "success": True,
                "withdrawals": withdrawals,
                "total": int(total),
                "has_more": (offset + page_size) < int(total),
            })

        except Exception as e:
            logger.error(f"获取提现记录失败: {e}")
            logger.error(traceback.format_exc())
            self.write_json({"success": False, "msg": "服务器错误"})


# ============================================================
# 新增: Native 支付（PC扫码支付）Handler
# 添加到你的 main.py 中
# ============================================================

class CreateNativeOrderHandler(LoggedRequestHandler):
    """
    PC端扫码支付 - Native下单
    POST /wanxiang/api/wechat/pay/create_native
    Body: {
        "order_name": "2026年丙午年运势报告",
        "amount": 990,
        "ref_code": "分销码(可选)",
        "birth_info": { ... }
    }
    返回: { "code_url": "weixin://wxpay/...", "order_no": "..." }
    """

    async def post(self):
        try:
            data = json.loads(self.request.body)
            order_name = data.get("order_name", "2026年丙午年运势报告")
            ref_code = data.get("ref_code", "")
            amount = data.get("amount", 990)
            openid = data.get("openid")
            login_type = data.get("login_type","")
            out_trade_no = generate_out_trade_no()
            # 1. 调用微信 Native 下单接口
            code_url = await self._create_native_order(out_trade_no, order_name, amount)

            if login_type == "mobile":
                target_user = await User.aio_get(User.mobile_openid == openid)
                user_id = target_user.id
            else:
                target_user = await User.aio_get(User.web_openid == openid)
                user_id = target_user.id

            if not code_url:
                self.set_status(500)
                self.write({"error": "微信下单失败"})
                return

            # 2. 存储订单
            new_order = Order(
                out_trade_no=out_trade_no,
                order_name=order_name,
                user_id=user_id,
                ref_code=ref_code,
                amount=amount,
                prepay_id="",       # Native 支付没有 prepay_id
                status="NOTPAY"
            )
            await new_order.aio_save(force_insert=True)

            # 3. 返回二维码链接
            self.write({
                "code_url": code_url,
                "order_no": out_trade_no,
            })

        except Exception as e:
            logger.exception("创建Native订单失败")
            self.set_status(500)
            self.write({"error": str(e)})

    async def _create_native_order(self, out_trade_no: str, order_name: str, amount: int) -> str:
        """调用微信 Native 下单接口，返回 code_url"""
        url = "https://api.mch.weixin.qq.com/v3/pay/transactions/native"
        url_path = "/v3/pay/transactions/native"

        body = {
            "appid": WECHAT_PAY_CONFIG["appid"],
            "mchid": WECHAT_PAY_CONFIG["mchid"],
            "description": order_name,
            "out_trade_no": out_trade_no,
            "notify_url": WECHAT_PAY_CONFIG["notify_url"],
            "amount": {
                "total": amount,
                "currency": "CNY"
            }
            # Native 支付不需要 payer.openid
        }

        body_str = json.dumps(body, ensure_ascii=False)
        auth_header = build_authorization_header("POST", url_path, body_str)

        http_client = tornado.httpclient.AsyncHTTPClient()
        request = tornado.httpclient.HTTPRequest(
            url=url,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": auth_header,
            },
            body=body_str,
        )

        response = await http_client.fetch(request, raise_error=False)

        if response.code == 200:
            result = json.loads(response.body)
            code_url = result.get("code_url")
            logger.info(f"Native下单成功: out_trade_no={out_trade_no}, code_url={code_url}")
            return code_url
        else:
            logger.error(f"微信Native下单失败: code={response.code}, body={response.body}")
            return None



class JsapiSignatureHandler(LoggedRequestHandler):
    """微信JSSDK签名接口"""

    async def post(self):
        try:
            body = json.loads(self.request.body)
            url = body.get("url", "")

            if not url:
                self.write_json({"success": False, "msg": "缺少url参数"})
                return

            ticket = await self._get_jsapi_ticket()
            if not ticket:
                self.write_json({"success": False, "msg": "获取jsapi_ticket失败"})
                return

            nonce_str = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
            timestamp = str(int(time.time()))

            # 按字典序拼接签名字符串
            sign_str = f"jsapi_ticket={ticket}&noncestr={nonce_str}&timestamp={timestamp}&url={url}"
            signature = hashlib.sha1(sign_str.encode('utf-8')).hexdigest()

            self.write_json({
                "success": True,
                "nonceStr": nonce_str,
                "timestamp": timestamp,
                "signature": signature,
            })
        except Exception as e:
            logger.error(f"签名接口异常: {e}")
            self.write_json({"success": False, "msg": str(e)})

    async def _get_jsapi_ticket(self):
        global jsapi_ticket_cache
        now = time.time()

        # 缓存有效直接返回
        if jsapi_ticket_cache["ticket"] and jsapi_ticket_cache["expires_at"] > now:
            return jsapi_ticket_cache["ticket"]

        # 先获取 access_token（注意这里是公众号的普通access_token，不是OAuth的）
        token_url = (
            f"https://api.weixin.qq.com/cgi-bin/token"
            f"?grant_type=client_credential"
            f"&appid={WX_MP_APP_ID}"
            f"&secret={WX_MP_APP_SECRET}"
        )
        token_data = await self._http_get(token_url)
        if not token_data or "access_token" not in token_data:
            logger.error(f"获取access_token失败: {token_data}")
            return None

        access_token = token_data["access_token"]

        # 用 access_token 获取 jsapi_ticket
        ticket_url = (
            f"https://api.weixin.qq.com/cgi-bin/ticket/getticket"
            f"?access_token={access_token}&type=jsapi"
        )
        ticket_data = await self._http_get(ticket_url)
        if not ticket_data or ticket_data.get("errcode") != 0:
            logger.error(f"获取jsapi_ticket失败: {ticket_data}")
            return None

        jsapi_ticket_cache["ticket"] = ticket_data["ticket"]
        jsapi_ticket_cache["expires_at"] = now + 7000  # 提前200秒过期

        return ticket_data["ticket"]

    async def _http_get(self, url):
        client = tornado.httpclient.AsyncHTTPClient()
        try:
            resp = await client.fetch(url, request_timeout=10)
            return json.loads(resp.body.decode("utf-8"))
        except Exception as e:
            logger.error(f"HTTP请求失败: {e}")
            return None




# JSON API 示例
class APIHandler(LoggedRequestHandler):
    def get(self):
        self.write({
            "status": "success",
            "message": "Tornado API is running",
            "timestamp": tornado.ioloop.IOLoop.current().time()
        })

# 动态路由示例
class UserHandler(LoggedRequestHandler):
    def get(self, user_id):
        self.write(f"User ID: {user_id}")

# 静态文件服务配置
settings = {
    "static_path": "static",  # 静态文件目录
    "debug": True  # 开发模式
}


# ========== 微信配置 ==========
# 网站应用的App secret
WX_REDIRECT_URI = "https://stellarsmart.cn/commission_web/"

# ========== 微信登录接口 ==========
WX_ACCESS_TOKEN_URL = "https://api.weixin.qq.com/sns/oauth2/access_token"
WX_USERINFO_URL = "https://api.weixin.qq.com/sns/userinfo"
WX_REFRESH_TOKEN_URL = "https://api.weixin.qq.com/sns/oauth2/refresh_token"
WX_AUTH_CHECK_URL = "https://api.weixin.qq.com/sns/auth"

# 在配置区增加服务号的密钥
WX_MP_APP_ID = "wx50afdd19b43f590e"        # 服务号 appId
WX_MP_APP_SECRET = "b143a473bd9cc93478d33d471f7354f7"       # 服务号 appSecret

WX_OPEN_APP_ID = "wxd642d4eeae08b232"    # 开放平台网站应用 appId（PC扫码用）
WX_OPEN_APP_SECRET = "02a3d0bed716644e9d5253ac3ab175c8"   # 开放平台网站应用 appSecret


class WechatLoginHandler(LoggedRequestHandler):
    """
    微信登录接口
    POST /api/wechat/login
    Body: { "code": "微信授权code" }
    """

    def write_json(self, data):
        self.write(json.dumps(data, ensure_ascii=False))


    def write_error_json(self, msg, code=400):
        self.set_status(code)
        self.write_json({"success": False, "msg": msg})


    async def post(self):
        try:
            body = json.loads(self.request.body)
            code = body.get("code")
            login_type = body.get("login_type", "mobile")  # 默认mobile
        except (json.JSONDecodeError, TypeError):
            self.write_error_json("请求参数格式错误")
            return

        if not code:
            self.write_error_json("缺少 code 参数")
            return

        # 第一步：用 code 换取 access_token
        token_data = await self._get_access_token(code,login_type)
        if not token_data:
            self.write_error_json("获取 access_token 失败")
            return

        if "errcode" in token_data:
            msg = token_data.get("errmsg", "未知错误")
            logger.error(f"微信返回错误: {token_data}")
            self.write_error_json(f"微信授权失败: {msg}")
            return

        access_token = token_data["access_token"]
        openid = token_data["openid"]
        refresh_token = token_data.get("refresh_token", "")
        unionid = token_data.get("unionid", "")
        logger.info(f"Get Token info:{token_data}")
        if login_type == "mobile":
            target_user = await User.aio_get_or_none(((User.mobile_openid == openid) | (User.wechat_unionid == unionid) ))
            if target_user:
                if not target_user.mobile_openid:
                    target_user.mobile_openid = openid
                    await target_user.aio_save()
            else:
                target_user = User(wechat_unionid = unionid,mobile_openid = openid,ref_code = generate_unique_invite_code())
                await target_user.aio_save()
        else:
            target_user = await User.aio_get_or_none(((User.web_openid == openid) | (User.wechat_unionid == unionid) ))
            if target_user:
                if not target_user.web_openid:
                    target_user.web_openid = openid
                    await target_user.aio_save()
            else:
                target_user = User(wechat_unionid = unionid,web_openid = openid,ref_code = generate_unique_invite_code())
                await target_user.aio_save()     

        # 第二步：用 access_token 获取用户信息
        user_info = await self._get_user_info(access_token, openid)
        logger.info(f"user_info:{user_info}")
        if not user_info or "errcode" in user_info:
            logger.error(f"获取用户信息失败: {user_info}")
            self.write_error_json("获取用户信息失败")
            return

        # 第三步：处理用户数据（存库 / 更新 / 生成业务token等）
        user = await self._save_or_update_user(user_info, target_user)

        # 第四步：返回给前端
        self.write_json({
            "success": True,
            "user": user
        })

    # _get_access_token 方法改为接收 login_type 参数
    async def _get_access_token(self, code, login_type="mobile"):
        if login_type == "mobile":
            app_id = WX_MP_APP_ID
            app_secret = WX_MP_APP_SECRET
        else:
            app_id = WX_OPEN_APP_ID
            app_secret = WX_OPEN_APP_SECRET

        url = (
            f"{WX_ACCESS_TOKEN_URL}"
            f"?appid={app_id}"
            f"&secret={app_secret}"
            f"&code={code}"
            f"&grant_type=authorization_code"
        )
        logger.info(f"Url is :{url}")
        return await self._http_get(url)


    async def _get_user_info(self, access_token, openid):
        """用 access_token 获取用户基本信息"""
        url = (
            f"{WX_USERINFO_URL}"
            f"?access_token={access_token}"
            f"&openid={openid}"
            f"&lang=zh_CN"
        )
        return await self._http_get(url)

    async def _http_get(self, url):
        """通用 HTTP GET 请求"""
        client = tornado.httpclient.AsyncHTTPClient()
        try:
            resp = await client.fetch(url, request_timeout=10)
            return json.loads(resp.body.decode("utf-8"))
        except tornado.httpclient.HTTPError as e:
            logger.error(f"HTTP请求失败: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            return None

    async def _save_or_update_user(self, user_info, target_user):
        """
        保存或更新用户信息到数据库
        这里给出示例结构，请根据实际数据库替换
        """
        openid = user_info.get("openid", "")
        unionid = user_info.get("unionid", "")
        nickname = user_info.get("nickname", "微信用户")
        headimgurl = user_info.get("headimgurl", "")
        sex = user_info.get("sex", 0)       # 1=男, 2=女, 0=未知
        country = user_info.get("country", "")
        province = user_info.get("province", "")
        city = user_info.get("city", "")
        target_user.unionid = unionid
        target_user.nickname = nickname
        await target_user.aio_save()
        return {
            "openid": openid,
            "unionid": unionid,
            "nickname": nickname,
            "headimgurl": headimgurl,
            "sex": sex,
            "province": province,
            "city": city,
            "ref_code":target_user.ref_code
        }


# ============================================================
# 工具函数
# ============================================================

def load_private_key():
    """加载商户API私钥"""
    with open(WECHAT_PAY_CONFIG["apiclient_key_path"], "rb") as f:
        return load_pem_private_key(f.read(), password=None)


def generate_nonce_str():
    """生成随机字符串"""
    return uuid.uuid4().hex


def generate_out_trade_no():
    """生成商户订单号"""
    return f"FORTUNE{int(time.time())}{uuid.uuid4().hex[:8].upper()}"


def sign_message(message: str) -> str:
    """
    使用商户私钥对消息进行RSA-SHA256签名
    """
    private_key = load_private_key()
    signature = private_key.sign(
        message.encode("utf-8"),
        PKCS1v15(),
        SHA256()
    )
    return base64.b64encode(signature).decode("utf-8")


def build_authorization_header(method: str, url_path: str, body: str) -> str:
    """
    构建微信支付API请求的 Authorization 头
    签名格式：HTTP请求方法\nURL\n请求时间戳\n请求随机串\n请求报文主体\n
    """
    timestamp = str(int(time.time()))
    nonce_str = generate_nonce_str()

    sign_str = f"{method}\n{url_path}\n{timestamp}\n{nonce_str}\n{body}\n"
    signature = sign_message(sign_str)

    mchid = WECHAT_PAY_CONFIG["mchid"]
    serial_no = WECHAT_PAY_CONFIG["mch_serial_no"]

    return (
        f'WECHATPAY2-SHA256-RSA2048 '
        f'mchid="{mchid}",'
        f'nonce_str="{nonce_str}",'
        f'signature="{signature}",'
        f'timestamp="{timestamp}",'
        f'serial_no="{serial_no}"'
    )


def build_jsapi_pay_sign(appid: str, timestamp: str, nonce_str: str, package: str) -> str:
    """
    构建前端 WeixinJSBridge 调起支付的签名 paySign
    签名串：appId\ntimeStamp\nnonceStr\npackage\n
    """
    sign_str = f"{appid}\n{timestamp}\n{nonce_str}\n{package}\n"
    return sign_message(sign_str)


def decrypt_aes_gcm(nonce: str, ciphertext: str, associated_data: str) -> str:
    """
    解密微信回调通知中的密文（AEAD_AES_256_GCM）
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = WECHAT_PAY_CONFIG["apiV3_key"].encode("utf-8")
    nonce_bytes = nonce.encode("utf-8")
    ciphertext_bytes = base64.b64decode(ciphertext)
    associated_data_bytes = associated_data.encode("utf-8") if associated_data else b""

    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce_bytes, ciphertext_bytes, associated_data_bytes)
    return plaintext.decode("utf-8")


# ============================================================
# API Handlers
# ============================================================

class CreateOrderHandler(LoggedRequestHandler):
    """
    创建订单 + 调用微信JSAPI下单接口
    前端 POST /api/wechat/pay/create
    Body: {
        "openid": "用户的openid",
        "birth_info": { "year": "1990", "month": "6", "day": "15", "hour": "09-11" },
        "ref_code": "分销码(可选)"
    }
    返回: { "pay_params": { appId, timeStamp, nonceStr, package, signType, paySign }, "order_no": "..." }
    """

    async def post(self):
        try:
            data = json.loads(self.request.body)
            openid = data.get("openid")
            order_name = data.get("order_name", "2026年丙午年运势报告")
            ref_code = data.get("ref_code", "")
            login_type = data.get("login_type","")
            amount = data.get("amount",1)
            
            if not openid:
                self.set_status(400)
                self.write({"error": "缺少openid参数"})
                return

            out_trade_no = generate_out_trade_no()

            # 1. 调用微信 JSAPI下单接口
            prepay_id = await self._create_prepay_order(out_trade_no, openid,order_name,amount)

            if not prepay_id:
                self.set_status(500)
                self.write({"error": "微信下单失败"})
                return

            if login_type == "mobile":
                target_user = await User.aio_get(User.mobile_openid == openid)
                user_id = target_user.id
            else:
                target_user = await User.aio_get(User.web_openid == openid)
                user_id = target_user.id

            # 2. 存储订单
            newOrder = Order(
                out_trade_no = out_trade_no,
                order_name = order_name,
                user_id = user_id,
                ref_code = ref_code,
                amount = amount,
                prepay_id = prepay_id,
                status = "NOTPAY"
            )
            await newOrder.aio_save(force_insert=True)

            # 3. 构建前端调起支付所需的参数
            appid = WECHAT_PAY_CONFIG["appid"]
            timestamp = str(int(time.time()))
            nonce_str = generate_nonce_str()
            package = f"prepay_id={prepay_id}"
            pay_sign = build_jsapi_pay_sign(appid, timestamp, nonce_str, package)

            pay_params = {
                "appId": appid,
                "timeStamp": timestamp,
                "nonceStr": nonce_str,
                "package": package,
                "signType": "RSA",
                "paySign": pay_sign,
            }

            self.write({
                "pay_params": pay_params,
                "order_no": out_trade_no,
            })

        except Exception as e:
            logger.exception("创建订单失败")
            self.set_status(500)
            self.write({"error": str(e)})

    async def _create_prepay_order(self, out_trade_no: str, openid: str,order_name:str,amount:int) -> str:
        """调用微信 JSAPI 下单接口，返回 prepay_id"""
        url = "https://api.mch.weixin.qq.com/v3/pay/transactions/jsapi"
        url_path = "/v3/pay/transactions/jsapi"

        body = {
            "appid": WECHAT_PAY_CONFIG["appid"],
            "mchid": WECHAT_PAY_CONFIG["mchid"],
            "description": order_name,
            "out_trade_no": out_trade_no,
            "notify_url": WECHAT_PAY_CONFIG["notify_url"],
            "amount": {
                "total": amount,
                "currency": "CNY"
            },
            "payer": {
                "openid": openid
            }
        }

        body_str = json.dumps(body, ensure_ascii=False)
        auth_header = build_authorization_header("POST", url_path, body_str)

        http_client = tornado.httpclient.AsyncHTTPClient()
        request = tornado.httpclient.HTTPRequest(
            url=url,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": auth_header,
            },
            body=body_str,
        )

        response = await http_client.fetch(request, raise_error=False)

        if response.code == 200:
            result = json.loads(response.body)
            prepay_id = result.get("prepay_id")
            logger.info(f"下单成功: out_trade_no={out_trade_no}, prepay_id={prepay_id}")
            return prepay_id
        else:
            logger.error(f"微信下单失败: code={response.code}, body={response.body}")
            return None


class QueryOrderHandler(LoggedRequestHandler):
    """
    查询订单支付状态
    GET /api/wechat/pay/query?order_no=xxx
    前端轮询用，确认支付是否成功
    """

    async def get(self):
        order_no = self.get_argument("order_no", "")
        target_order = await Order.aio_get_or_none(Order.out_trade_no == order_no)

        if not target_order:
            self.set_status(404)
            self.write({"error": "订单不存在"})
            return

        # 如果本地状态还是未支付，主动去微信查一次（防止回调丢失）
        if target_order.status == "NOTPAY":
            wx_status = await self._query_wechat_order(order_no)
            if wx_status:
                target_order.status = wx_status
                await target_order.aio_save()

        self.write({
            "order_no": order_no,
            "status": target_order.status,  # NOTPAY / SUCCESS / CLOSED / REFUND 等
        })

    async def _query_wechat_order(self, out_trade_no: str) -> str:
        """主动查询微信订单状态"""
        mchid = WECHAT_PAY_CONFIG["mchid"]
        url_path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}?mchid={mchid}"
        url = f"https://api.mch.weixin.qq.com{url_path}"

        auth_header = build_authorization_header("GET", url_path, "")

        http_client = tornado.httpclient.AsyncHTTPClient()
        request = tornado.httpclient.HTTPRequest(
            url=url,
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": auth_header,
            },
        )

        response = await http_client.fetch(request, raise_error=False)

        if response.code == 200:
            result = json.loads(response.body)
            return result.get("trade_state", "")
        else:
            logger.error(f"查询订单失败: {response.body}")
            return None



import json
from peewee import fn

# ---- 1. 仪表盘接口 ----
class DashboardHandler(LoggedRequestHandler):
    """
    GET /wanxiang/api/dashboard?openid=xxx&login_type=mobile
    返回用户的余额、累计收益、订单数、推广人数
    """
    async def get(self):
        openid = self.get_argument("openid", "")
        login_type = self.get_argument("login_type", "mobile")

        if not openid:
            self.write_json({"success": False, "msg": "缺少openid"})
            return

        # 查找用户
        if login_type == "mobile":
            user = await User.aio_get_or_none(User.mobile_openid == openid)
        else:
            user = await User.aio_get_or_none(User.web_openid == openid)

        if not user:
            self.write_json({"success": False, "msg": "用户不存在"})
            return

        ref_code = user.ref_code

        # 统计数据（通过我的推荐码成交的订单）
        order_count = 0
        referral_count = 0
        total_earnings_fen = 0

        try:
            # 成交订单数
            count_query = (Order
                .select(fn.COUNT(Order.out_trade_no))
                .where(Order.ref_code == ref_code, Order.status == 'SUCCESS'))
            order_count = await count_query.aio_scalar() or 0

            # 推广人数（不同的 user_id 去重）
            ref_query = (Order
                .select(fn.COUNT(fn.DISTINCT(Order.user_id)))
                .where(Order.ref_code == ref_code, Order.status == 'SUCCESS'))
            referral_count = await ref_query.aio_scalar() or 0

            # 累计收益 - 优先用 user.total_earned，备选从订单算
            total_earnings_fen = int(user.total_earned or 0)
            
            # 如果 total_earned 为0但有订单，从订单重新计算
            if total_earnings_fen == 0 and order_count > 0:
                sum_query = (Order
                    .select(fn.SUM(Order.amount))
                    .where(Order.ref_code == ref_code, Order.status == 'SUCCESS'))
                total_amount = await sum_query.aio_scalar() or 0
                # 按45%佣金计算，四舍五入到元
                total_earnings_fen = round(total_amount * 45 / 100 / 100) * 100

        except Exception as e:
            logger.error(f"统计数据查询失败: {e}")

        self.write_json({
            "success": True,
            "data": {
                "balance": int(user.balance or 0),          # 可提现余额(分)
                "total_earnings": total_earnings_fen,         # 累计收益(分)
                "order_count": order_count,                   # 成交订单数
                "referral_count": referral_count,             # 推广人数
            }
        })


# ---- 2. 产品列表接口 ----
class ProductListHandler(LoggedRequestHandler):
    """
    GET /wanxiang/api/products?openid=xxx&login_type=mobile
    返回产品列表 + 用户对每个产品的自定义价格
    """
    async def get(self):
        openid = self.get_argument("openid", "")
        login_type = self.get_argument("login_type", "mobile")

        # 获取所有上架产品
        products = await Product.select().where(Product.is_active == True).aio_execute()
        product_list = []

        # 查找用户（获取自定义价格）
        user = None
        user_prices = {}
        if openid:
            if login_type == "mobile":
                user = await User.aio_get_or_none(User.mobile_openid == openid)
            else:
                user = await User.aio_get_or_none(User.web_openid == openid)

            if user:
                # 查询该用户的所有自定义价格
                price_records = await (UserProductPrice
                    .select()
                    .where(UserProductPrice.user_id == user.id)
                    .aio_execute())
                for p in price_records:
                    user_prices[p.product_id] = p.custom_price

        for prod in products:
            custom = user_prices.get(prod.id, None)
            # 计算佣金（基于自定义价格或推荐价）
            active_price = custom if custom else prod.recommended_price
            commission = round(active_price * prod.commission_rate / 100 / 100) * 100  # 四舍五入到元(分)

            product_list.append({
                "id": prod.id,
                "name": prod.name,
                "desc": prod.desc,
                "icon": prod.icon,
                "url_path": prod.url_path,
                "base_price": prod.base_price,
                "recommended_price": prod.recommended_price,
                "max_price": prod.max_price,
                "commission_rate": prod.commission_rate,
                "custom_price": custom,             # 用户自定义价格，null表示未设置
                "active_price": active_price,       # 当前生效价格
                "commission": commission,            # 当前佣金(分)
            })

        self.write_json({
            "success": True,
            "products": product_list
        })


# ---- 3. 设置自定义价格接口 ----
class SetUserPriceHandler(LoggedRequestHandler):
    """
    POST /wanxiang/api/user/set_price
    Body: { "openid": "xxx", "login_type": "mobile", "product_id": 1, "price": 12800 }
    price 单位为分
    """
    async def post(self):
        try:
            body = json.loads(self.request.body)
            openid = body.get("openid")
            login_type = body.get("login_type", "mobile")
            product_id = body.get("product_id")
            price = body.get("price")  # 分

            if not all([openid, product_id, price]):
                self.write_json({"success": False, "msg": "参数不完整"})
                return

            price = int(price)

            # 查找用户
            if login_type == "mobile":
                user = await User.aio_get_or_none(User.mobile_openid == openid)
            else:
                user = await User.aio_get_or_none(User.web_openid == openid)

            if not user:
                self.write_json({"success": False, "msg": "用户不存在"})
                return

            # 查找产品
            product = await Product.aio_get_or_none(Product.id == product_id)
            if not product:
                self.write_json({"success": False, "msg": "产品不存在"})
                return

            # 校验价格范围
            if price < product.base_price:
                self.write_json({
                    "success": False,
                    "msg": f"价格不能低于保底价 ¥{product.base_price / 100:.2f}"
                })
                return

            if price > product.max_price:
                self.write_json({
                    "success": False,
                    "msg": f"价格不能高于最高价 ¥{product.max_price / 100:.2f}"
                })
                return

            # 更新或插入自定义价格
            existing = await UserProductPrice.aio_get_or_none(
                UserProductPrice.user_id == user.id,
                UserProductPrice.product_id == product_id
            )

            if existing:
                existing.custom_price = price
                existing.updated_time = datetime.datetime.now()
                await existing.aio_save()
            else:
                new_price = UserProductPrice(
                    user_id=user.id,
                    product_id=product_id,
                    custom_price=price
                )
                await new_price.aio_save(force_insert=True)

            # 返回新的佣金
            commission = round(price * product.commission_rate / 100 / 100) * 100

            self.write_json({
                "success": True,
                "msg": "价格设置成功",
                "active_price": price,
                "commission": commission
            })

        except Exception as e:
            logger.error(f"设置价格失败: {e}")
            self.write_json({"success": False, "msg": str(e)})


# ---- 4. 查询推荐人定价接口（给产品购买页调用）----
class GetRefPriceHandler(LoggedRequestHandler):
    """
    GET /wanxiang/api/product/ref_price?ref=XXXX&product_id=1
    或 GET /wanxiang/api/product/ref_price?ref=XXXX&url_path=2026-yearly-report
    购买页面调用，获取推荐人对该产品的定价
    如果推荐人没设置自定义价格，返回推荐价
    """
    async def get(self):
        ref_code = self.get_argument("ref", "")
        product_id = self.get_argument("product_id", "")
        url_path = self.get_argument("url_path", "")

        # 支持 product_id 或 url_path 两种查找方式
        product = None
        if product_id:
            product = await Product.aio_get_or_none(Product.id == int(product_id))
        elif url_path:
            product = await Product.aio_get_or_none(Product.url_path == url_path)
        else:
            self.write_json({"success": False, "msg": "缺少product_id或url_path"})
            return

        if not product:
            self.write_json({"success": False, "msg": "产品不存在"})
            return

        active_price = product.recommended_price  # 默认推荐价

        if ref_code:
            ref_user = await User.aio_get_or_none(User.ref_code == ref_code)
            if ref_user:
                user_price = await UserProductPrice.aio_get_or_none(
                    UserProductPrice.user_id == ref_user.id,
                    UserProductPrice.product_id == product.id
                )
                if user_price:
                    active_price = user_price.custom_price

        self.write_json({
            "success": True,
            "product_id": product.id,
            "name": product.name,
            "price": active_price,              # 当前生效价格(分)
            "original_price": product.max_price, # 划线原价(分)，用最高价作为"原价"
            "max_price": product.max_price,
            "base_price": product.base_price,
            "ref_code": ref_code
        })



report_tasks = {}  # report_id -> { status, sections, report, error }


# ============================================================
# 1. 获取报告（已有则直接返回）
# ============================================================
class GetReportHandler(LoggedRequestHandler):
    """
    GET /wanxiang/api/report?order_no=xxx
    或  GET /wanxiang/api/report?report_id=xxx
    返回完整报告（如果已生成）
    """
    async def get(self):
        order_no = self.get_argument("order_no", "")
        report_id = self.get_argument("report_id", "")

        try:
            rpt = None
            if report_id:
                rpt = await Report.aio_get_or_none(Report.id == int(report_id))
            elif order_no:
                rpt = await Report.aio_get_or_none(Report.order_no == order_no)

            if not rpt:
                self.write_json({"success": False, "msg": "报告不存在"})
                return

            if rpt.status != "completed":
                self.write_json({
                    "success": False,
                    "msg": "报告生成中",
                    "status": rpt.status,
                })
                return

            report_data = json.loads(rpt.report_json) if rpt.report_json else {}
            self.write_json({
                "success": True,
                "report": report_data,
                "report_id": rpt.id,
                "created_at": rpt.created_at.strftime('%Y-%m-%d %H:%M:%S') if rpt.created_at else "",
            })

        except Exception as e:
            logger.error(f"获取报告失败: {e}")
            logger.error(traceback.format_exc())
            self.write_json({"success": False, "msg": str(e)})


# ============================================================
# 2. 触发报告生成
# ============================================================
class GenerateReportHandler(LoggedRequestHandler):
    """
    POST /wanxiang/api/report/generate
    Body: {
        "order_no": "FORTUNE...",
        "birth_info": { "year": "1993", "month": "7", "day": "15", "hour": "09-11" }
    }
    返回: { "success": true, "report_id": 123 }
    """
    async def post(self):
        try:
            body = json.loads(self.request.body)
            order_no = body.get("order_no", "")
            birth_info = body.get("birth_info", {})

            if not order_no:
                self.write_json({"success": False, "msg": "缺少 order_no"})
                return

            # 检查订单是否已支付
            order = await Order.aio_get_or_none(Order.out_trade_no == order_no)
            if not order or order.status != "SUCCESS":
                self.write_json({"success": False, "msg": "订单未支付或不存在"})
                return

            # 检查是否已有报告
            existing = await Report.aio_get_or_none(Report.order_no == order_no)
            if existing and existing.status == "completed":
                self.write_json({
                    "success": True,
                    "report_id": existing.id,
                    "msg": "报告已存在",
                })
                return

            # 计算八字
            bazi_str, gender, current_dayun = self._calc_bazi(birth_info)

            # 创建报告记录
            if existing:
                rpt = existing
                rpt.status = "generating"
                rpt.bazi_str = bazi_str
                rpt.birth_info_json = json.dumps(birth_info, ensure_ascii=False)
                await rpt.aio_save()
            else:
                rpt = Report(
                    order_no=order_no,
                    user_id=order.user_id,
                    status="generating",
                    bazi_str=bazi_str,
                    birth_info_json=json.dumps(birth_info, ensure_ascii=False),
                    created_at=datetime.datetime.now(),
                )
                await rpt.aio_save(force_insert=True)

            report_id = rpt.id

            # 初始化任务状态
            _report_tasks[report_id] = {
                "status": "generating",
                "sections": {},
                "report": None,
                "error": None,
            }

            # 异步启动生成任务
            asyncio.create_task(self._run_generation(
                report_id, bazi_str, gender, current_dayun
            ))

            self.write_json({
                "success": True,
                "report_id": report_id,
            })

        except Exception as e:
            logger.error(f"触发报告生成失败: {e}")
            logger.error(traceback.format_exc())
            self.write_json({"success": False, "msg": str(e)})

    def _calc_bazi(self, birth_info):
        """
        根据用户出生信息计算八字
        返回 (bazi_str, gender, current_dayun)
        """
        from datetime import datetime as dt


        year = int(birth_info.get("year", 1990))
        month = int(birth_info.get("month", 1))
        day = int(birth_info.get("day", 1))
        hour_str = birth_info.get("hour", "unknown")
        gender_str = birth_info.get("gender", "男")
        gender = 1 if gender_str == "男" else 0

        # 时辰转换为具体小时
        if hour_str == "unknown":
            hour = 12  # 默认午时
            minute = 0
        else:
            # hour_str 格式: "09-11" 取中间值
            parts = hour_str.split("-")
            h_start = int(parts[0])
            h_end = int(parts[1]) if len(parts) > 1 else h_start + 2
            hour = (h_start + h_end) // 2
            minute = 0

        born_time = dt(year, month, day, hour, minute)
        # 2026年用于计算大运
        yunshi_time = dt(2026, 6, 1, 12, 0)

        bazi_info = get_bazi_natal_info(
            born_time=born_time,
            gender=gender,
            timezoneOffset=8,
            born_lon=116.4,  # 默认北京经度
            yunshi_time=yunshi_time,
        )

        bazi_str = (
            f"{bazi_info['niangan']}{bazi_info['nianzhi']} "
            f"{bazi_info['yuegan']}{bazi_info['yuezhi']} "
            f"{bazi_info['rigan']}{bazi_info['rizhi']} "
            f"{bazi_info['shigan']}{bazi_info['shizhi']}"
        )

        dayun = bazi_info.get("dayun_wuxing", "未知")
        gender_label = "男" if gender == 1 else "女"

        return bazi_str, gender_label, dayun

    async def _run_generation(self, report_id, bazi_str, gender, current_dayun):
        """异步运行19路并行生成"""
        try:
            async def on_section_done(section_key, section_data):
                """每完成一个 section 的回调"""
                if report_id in _report_tasks:
                    _report_tasks[report_id]["sections"][section_key] = True
                logger.info(f"[Report {report_id}] Section {section_key} 完成")

            report = await generate_full_report(
                bazi_str=bazi_str,
                gender=gender,
                current_dayun=current_dayun,
                ai_type="deepseek",
                brand="deepseek",
                on_section_complete=on_section_done,
            )

            # 保存到数据库
            rpt = await Report.aio_get_or_none(Report.id == report_id)
            if rpt:
                rpt.status = "completed"
                rpt.report_json = json.dumps(report, ensure_ascii=False)
                rpt.completed_at = datetime.datetime.now()
                await rpt.aio_save()

            # 更新内存状态
            if report_id in _report_tasks:
                _report_tasks[report_id]["status"] = "completed"
                _report_tasks[report_id]["report"] = report

            logger.info(f"[Report {report_id}] 全部生成完成!")

        except Exception as e:
            logger.error(f"[Report {report_id}] 生成失败: {e}")
            logger.error(traceback.format_exc())

            rpt = await Report.aio_get_or_none(Report.id == report_id)
            if rpt:
                rpt.status = "failed"
                rpt.error_msg = str(e)
                await rpt.aio_save()

            if report_id in _report_tasks:
                _report_tasks[report_id]["status"] = "failed"
                _report_tasks[report_id]["error"] = str(e)


# ============================================================
# 3. 查询生成进度
# ============================================================
class ReportStatusHandler(LoggedRequestHandler):
    """
    GET /wanxiang/api/report/status?report_id=xxx
    返回: { "status": "generating|completed|failed", "sections": { "foundation": true, ... } }
    """
    async def get(self):
        report_id = self.get_argument("report_id", "")
        if not report_id:
            self.write_json({"success": False, "msg": "缺少 report_id"})
            return

        rid = int(report_id)

        # 先查内存（实时进度）
        if rid in _report_tasks:
            task = _report_tasks[rid]
            self.write_json({
                "success": True,
                "status": task["status"],
                "sections": task["sections"],
            })
            # 如果已完成或失败，清理内存
            if task["status"] in ("completed", "failed"):
                del _report_tasks[rid]
            return

        # 内存里没有，查数据库
        rpt = await Report.aio_get_or_none(Report.id == rid)
        if not rpt:
            self.write_json({"success": False, "msg": "报告不存在"})
            return

        self.write_json({
            "success": True,
            "status": rpt.status,
            "sections": {},
        })


# ============================================================
# 4. 用户历史报告列表
# ============================================================
class UserReportsHandler(LoggedRequestHandler):
    """
    GET /wanxiang/api/reports?openid=xxx&login_type=mobile
    返回用户所有已完成的报告列表
    """
    async def get(self):
        openid = self.get_argument("openid", "")
        login_type = self.get_argument("login_type", "mobile")

        if not openid:
            self.write_json({"success": False, "msg": "缺少 openid"})
            return

        if login_type == "mobile":
            user = await User.aio_get_or_none(User.mobile_openid == openid)
        else:
            user = await User.aio_get_or_none(User.web_openid == openid)

        if not user:
            self.write_json({"success": True, "reports": []})
            return

        reports = await (Report
            .select(Report.id, Report.order_no, Report.bazi_str,
                    Report.status, Report.created_at)
            .where(Report.user_id == user.id, Report.status == "completed")
            .order_by(Report.id.desc())
            .limit(20)
            .aio_execute())

        result = []
        for r in reports:
            result.append({
                "report_id": r.id,
                "order_no": r.order_no,
                "bazi": r.bazi_str,
                "created_at": r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else "",
            })

        self.write_json({"success": True, "reports": result})






# 应用路由
def make_app():
    return tornado.web.Application([
        (r"/api", APIHandler),
        (r"/user/([0-9]+)", UserHandler),  # 动态路由
        (r"/wanxiang/api/wechat/login", WechatLoginHandler),
        (r"/wanxiang/api/withdraw", WithdrawHandler),
        (r"/wanxiang/api/wechat/pay/create", CreateOrderHandler),
        (r"/wanxiang/api/wechat/pay/notify", PayNotifyHandler),
        (r"/wanxiang/api/wechat/pay/query", QueryOrderHandler),
        (r"/wanxiang/api/wechat/jsapi_signature", JsapiSignatureHandler),  # 新增
        (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": settings["static_path"]}),
        (r"/wanxiang/api/wechat/pay/create_native", CreateNativeOrderHandler),
        (r"/wanxiang/api/dashboard", DashboardHandler),
        (r"/wanxiang/api/products", ProductListHandler),
          (r"/wanxiang/api/user/set_price", SetUserPriceHandler),
          (r"/wanxiang/api/product/ref_price", GetRefPriceHandler),
            (r"/wanxiang/api/orders", OrderListHandler),           # 新增
        (r"/wanxiang/api/withdrawals", WithdrawalListHandler), # 新增
         (r"/wanxiang/api/report", GetReportHandler),
    (r"/wanxiang/api/report/generate", GenerateReportHandler),
    (r"/wanxiang/api/report/status", ReportStatusHandler),
    (r"/wanxiang/api/reports", UserReportsHandler),
        
    ], **settings)

# 启动应用
if __name__ == "__main__":
    app = make_app()
    app.listen(3032)  # 监听端口
    print("Server started at http://localhost:3032")
    tornado.ioloop.IOLoop.current().start()

    