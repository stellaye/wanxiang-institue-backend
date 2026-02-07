import logging
MCHID = '1230000109'

# 商户证书私钥，此文件不要放置在下面设置的CERT_DIR目录里。
with open('path_to_mch_private_key/apiclient_key.pem') as f:
    PRIVATE_KEY = f.read()

# 商户证书序列号
CERT_SERIAL_NO = '444F4864EA9B34415...'

# API v3密钥， https://pay.weixin.qq.com/wiki/doc/apiv3/wechatpay/wechatpay3_2.shtml
APIV3_KEY = 'MIIEvwIBADANBgkqhkiG9w0BAQE...'

# APPID，应用ID，服务商模式下为服务商应用ID，即官方文档中的sp_appid，也可以在调用接口的时候覆盖。
APPID = 'wxd678efh567hg6787'

# 回调地址，也可以在调用接口的时候覆盖。
NOTIFY_URL = 'https://www.xxxx.com/notify'

# 微信支付平台证书缓存目录，初始调试的时候可以设为None，首次使用确保此目录为空目录。
CERT_DIR = './cert'

# 日志记录器，记录web请求和回调细节，便于调试排错。
logging.basicConfig(filename=os.path.join(os.getcwd(), 'demo.log'), level=logging.DEBUG, filemode='a', format='%(asctime)s - %(process)s - %(levelname)s: %(message)s')
LOGGER = logging.getLogger("demo")

# 接入模式：False=直连商户模式，True=服务商模式。
PARTNER_MODE = False

# 代理设置，None或者{"https": "http://10.10.1.10:1080"}，详细格式参见[https://requests.readthedocs.io/en/latest/user/advanced/#proxies](https://requests.readthedocs.io/en/latest/user/advanced/#proxies)
PROXY = None

# 请求超时时间配置
TIMEOUT = (10, 30) # 建立连接最大超时时间是10s，读取响应的最大超时时间是30s

# 微信支付平台公钥
# 注：如果使用平台公钥模式初始化，需配置此参数。
with open('path_to_wechat_pay_public_key/pub_key.pem') as f:
    PUBLIC_KEY = f.read()

# 微信支付平台公钥ID
# 注：如果使用平台公钥模式初始化，需配置此参数。
PUBLIC_KEY_ID = 'PUB_KEY_ID_444F4864EA9B34415...'




