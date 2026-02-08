import tornado.ioloop
import tornado.web
import json
from logger import logger
import tornado.httpclient  # 这是解决错误的关键
from models import User
# 定义处理器
class MainHandler(tornado.web.RequestHandler):
    def get(self):
        self.write("Hello, Tornado!")
    
    def post(self):
        data = self.get_argument("data", "No data provided")
        self.write(f"Received: {data}")

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
WX_MP_APP_ID = "wx_your_mp_appid"        # 服务号 appId
WX_MP_APP_SECRET = "your_mp_secret"       # 服务号 appSecret

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



# 应用路由
def make_app():
    return tornado.web.Application([
        (r"/", MainHandler),
        (r"/api", APIHandler),
        (r"/user/([0-9]+)", UserHandler),  # 动态路由
        (r"/wanxiang/api/wechat/login", WechatLoginHandler),
        (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": settings["static_path"]}),
    ], **settings)

# 启动应用
if __name__ == "__main__":
    app = make_app()
    app.listen(3032)  # 监听端口
    print("Server started at http://localhost:3032")
    tornado.ioloop.IOLoop.current().start()

    