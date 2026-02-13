import tornado.ioloop
import tornado.web
import json
from logger import logger
import tornado.httpclient  # 这是解决错误的关键
from models import User,Order
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



# 全局缓存 jsapi_ticket
jsapi_ticket_cache = {"ticket": "", "expires_at": 0}


# 定义处理器
class MainHandler(tornado.web.RequestHandler):
    def get(self):
        self.write("Hello, Tornado!")
    
    def post(self):
        data = self.get_argument("data", "No data provided")
        self.write(f"Received: {data}")

    def write_json(self, data):
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(data, ensure_ascii=False))

        
class JsapiSignatureHandler(MainHandler):
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
class APIHandler(tornado.web.RequestHandler):
    def get(self):
        self.write({
            "status": "success",
            "message": "Tornado API is running",
            "timestamp": tornado.ioloop.IOLoop.current().time()
        })

# 动态路由示例
class UserHandler(tornado.web.RequestHandler):
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


class WechatLoginHandler(MainHandler):
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
            target_user = await User.aio_get_or_none(User.mobile_openid == openid)
            if target_user:
                pass
            else:
                new_user = User(wechat_unionid = unionid,mobile_openid = openid)
                await new_user.aio_save()
        else:
            target_user = await User.aio_get_or_none(User.web_openid == openid)
            if target_user:
                pass
            else:
                new_user = User(wechat_unionid = unionid,web_openid = openid)
                await new_user.aio_save()     

        # 第二步：用 access_token 获取用户信息
        user_info = await self._get_user_info(access_token, openid)
        logger.info(f"user_info:{user_info}")
        if not user_info or "errcode" in user_info:
            logger.error(f"获取用户信息失败: {user_info}")
            self.write_error_json("获取用户信息失败")
            return

        # 第三步：处理用户数据（存库 / 更新 / 生成业务token等）
        user = await self._save_or_update_user(user_info, refresh_token)

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

    async def _save_or_update_user(self, user_info, refresh_token):
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

        # TODO: 替换为真实的数据库操作
        # 例如使用 MySQL / PostgreSQL / MongoDB:
        #
        # existing_user = await db.users.find_one({"openid": openid})
        # if existing_user:
        #     await db.users.update_one(
        #         {"openid": openid},
        #         {"$set": {
        #             "nickname": nickname,
        #             "headimgurl": headimgurl,
        #             "refresh_token": refresh_token,
        #             "updated_at": datetime.now()
        #         }}
        #     )
        # else:
        #     await db.users.insert_one({
        #         "openid": openid,
        #         "unionid": unionid,
        #         "nickname": nickname,
        #         "headimgurl": headimgurl,
        #         "refresh_token": refresh_token,
        #         "balance": 0,
        #         "created_at": datetime.now()
        #     })

        # logger.info(f"用户登录成功: {nickname} ({openid})")

        return {
            "openid": openid,
            "unionid": unionid,
            "nickname": nickname,
            "headimgurl": headimgurl,
            "sex": sex,
            "province": province,
            "city": city,
        }



class WithdrawHandler(MainHandler):

    async def post(self):
        try:
            body = json.loads(self.request.body)
            login_type = body.get("login_type")
            openid = body.get("openid")
            amount = body.get("amount")

            if not openid or not amount:
                self.write_json({"success": False, "msg": "缺少必要参数"})
                return

            if login_type == "mobile":
                client_id = "mobile_app"
                app_id = WX_MP_APP_ID
            else:
                client_id = "web_app"
                app_id = WX_OPEN_APP_ID

            raw_result = transfer_to_openid(openid=openid, amount=amount, client_id=client_id)
            logger.info(f"转账结果: {raw_result}")

            if isinstance(raw_result, tuple):
                success, result = raw_result
            else:
                success = False
                result = raw_result

            if not success or not result:
                self.write_json({"success": False, "msg": "转账失败"})
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
            logger.error(f"提现接口异常: {e}")
            self.write_json({"success": False, "msg": f"服务器异常: {str(e)}"})




logger = logging.getLogger(__name__)
current_dir = os.path.dirname(os.path.abspath(__file__))
key_path = os.path.join(os.path.join(current_dir,"wxpay"),"apiclient_key.pem")



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

# 商品价格（单位：分）
PRODUCT_PRICE_FEN = 990  # ¥9.9 = 990分


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

class CreateOrderHandler(tornado.web.RequestHandler):
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
            login_type = data.get("mobile","")
            amount = data.get("amount",0)
            
            # if not openid:
            #     self.set_status(400)
            #     self.write({"error": "缺少openid参数"})
            #     return

            out_trade_no = generate_out_trade_no()

            # 1. 调用微信 JSAPI下单接口
            prepay_id = await self._create_prepay_order(out_trade_no, openid,order_name,amount)

            # if not prepay_id:
            #     self.set_status(500)
            #     self.write({"error": "微信下单失败"})
            #     return

            # if login_type == "mobile":
            #     target_user = await User.aio_get(User.mobile_openid == openid)
            #     user_id = target_user.id
            # else:
            #     target_user = await User.aio_get(User.web_openid == openid)
            #     user_id = target_user.id

            # 2. 存储订单
            newOrder = Order(
                out_trade_no = out_trade_no,
                order_name = order_name,
                user_id = 0,
                ref_code = ref_code,
                amount = amount,
                prepay_id = prepay_id,
                status = "NOTPAY"
            )
            await newOrder.aio_save()

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


class PayNotifyHandler(tornado.web.RequestHandler):
    """
    微信支付结果回调通知
    POST /api/wechat/pay/notify
    微信服务器会推送支付结果到这个地址
    """

    async def post(self):
        try:
            notify_data = json.loads(self.request.body)
            logger.info(f"收到微信支付回调: {notify_data}")

            # 解密通知内容
            resource = notify_data.get("resource", {})
            plaintext = decrypt_aes_gcm(
                nonce=resource["nonce"],
                ciphertext=resource["ciphertext"],
                associated_data=resource.get("associated_data", ""),
            )

            payment_info = json.loads(plaintext)
            out_trade_no = payment_info["out_trade_no"]
            trade_state = payment_info["trade_state"]

            logger.info(f"支付结果: order={out_trade_no}, state={trade_state}")

            target_order = await Order.aio_get_or_none(Order.out_trade_no == out_trade_no)
            if target_order:
                target_order.status = trade_state
                if trade_state == "SUCCESS":
                    target_order.transaction_id = payment_info.get("transaction_id", "")
                    target_order.pay_time = payment_info.get("success_time", "")
                    
                    # TODO: 这里可以触发生成报告、发送通知等业务逻辑
                    logger.info(f"订单支付成功: {out_trade_no}")

            # 返回成功应答（必须返回，否则微信会重复通知）
            self.set_status(200)
            self.write({"code": "SUCCESS", "message": "成功"})

        except Exception as e:
            logger.exception("处理支付回调失败")
            self.set_status(500)
            self.write({"code": "FAIL", "message": str(e)})


class QueryOrderHandler(tornado.web.RequestHandler):
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




# 应用路由
def make_app():
    return tornado.web.Application([
        (r"/", MainHandler),
        (r"/api", APIHandler),
        (r"/user/([0-9]+)", UserHandler),  # 动态路由
        (r"/wanxiang/api/wechat/login", WechatLoginHandler),
        (r"/wanxiang/api/withdraw", WithdrawHandler),
        (r"/wanxiang/api/wechat/pay/create", CreateOrderHandler),
        (r"/wanxiang/api/wechat/pay/notify", PayNotifyHandler),
        (r"/wanxiang/api/wechat/pay/query", QueryOrderHandler),
        (r"/wanxiang/api/wechat/jsapi_signature", JsapiSignatureHandler),  # 新增
        (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": settings["static_path"]}),
    ], **settings)

# 启动应用
if __name__ == "__main__":
    app = make_app()
    app.listen(3032)  # 监听端口
    print("Server started at http://localhost:3032")
    tornado.ioloop.IOLoop.current().start()

    