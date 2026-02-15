import sys
import subprocess
import platform

system_name = platform.system()
# 判断是否为 macOS
from statistics import mean, median, stdev
from concurrent.futures import ThreadPoolExecutor
if system_name == "Darwin":
    sys.path.append("/Users/stellaye/wanxiang-institue-backend")
else:
    sys.path.append("/root/wanxiang-institue-backend")
from peewee import *
import peewee_async
from datetime import date
from playhouse.shortcuts import ReconnectMixin
import time
import random
import json
from playhouse.shortcuts import model_to_dict
import aiomysql
import datetime
import asyncio
from peewee_async import AioModel
from peewee_async import PooledMySQLDatabase
import uuid

remote_server = "myecs"
# remote_server = "47.116.182.73"

host = "localhost" if "darwin" not in sys.platform else remote_server

# ssh -Nf -L 3307:localhost:3306 -o "ProxyCommand=nc %h %p" root@testecs
def setup_ssh_tunnel():
    # zhixih
    # SSH隧道命令
    ssh_command = ["ssh", "-Nf", "-L", "3307:localhost:3306", f"root@m{remote_server}"]

    try:
        # 检查是否已经存在SSH隧道
        check_tunnel = subprocess.run(["ps", "aux"], capture_output=True, text=True)
        if "3307:localhost:3306" not in check_tunnel.stdout:
            # 建立SSH隧道
            subprocess.Popen(
                ssh_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            # 等待隧道建立
            time.sleep(2)
        return True
    except Exception as e:
        print(f"建立SSH隧道失败: {e}")
        return False


port = 3306 if "darwin" not in sys.platform else 3307
if port == 3307:
    setup_ssh_tunnel()


# 创建数据库实例
database = PooledMySQLDatabase(
    "wanxiang",
    max_connections=1100,
    user="root",
    password="yrjdata@454784911",
    host="127.0.0.1",
    port=port,
    charset='utf8mb4', 
)


# objects = Manager(database)
# objects.database.allow_sync = False
class UnknownField(object):
    def __init__(self, *_, **__):
        pass


try:
    print("123")
except AttributeError:
    raise


class BaseModel(AioModel):
    class Meta:
        database = database

    def save(self, *args, **kwargs):
        self.modified_time = datetime.datetime.now()
        return super().save(*args, **kwargs)





class Order(BaseModel):

    id = IntegerField(null=False)
    # 订单号 - 主键
    out_trade_no = CharField(max_length=64, primary_key=True, index=True)
    # 订单名
    order_name = CharField(max_length=64)
    # 用户信息
    user_id = IntegerField(null=False)
    # 推荐码
    ref_code = CharField(max_length=64, null=True, index=True)
    # 金额（分）
    amount = IntegerField(null=False, help_text="金额，单位：分")
    # 预支付ID
    prepay_id = CharField(max_length=128, null=True) 
    # 订单状态
    status = CharField(
        max_length=20, 
        choices=[
            ('NOTPAY', '未支付'),
            ('SUCCESS', '支付成功'),
            ('CLOSED', '已关闭')
        ],
        default='NOTPAY',
        index=True
    )
    
    # 创建时间（时间戳）
    create_time =  DateTimeField(default=datetime.datetime.now, verbose_name='创建时间')
    
    # 添加一些额外的常用字段
    update_time =  DateTimeField(default=datetime.datetime.now, verbose_name='更新时间')
    pay_time =  DateTimeField(default=datetime.datetime.now, verbose_name='付款时间')
    transaction_id = CharField(max_length=64, null=True)  # 微信支付交易号
    
    class Meta:
        table_name = 'orders'
        indexes = (
            # 复合索引
            (('status', 'create_time'), False),
        )
    
    @classmethod
    def create_order(cls, out_trade_no, openid, birth_info, ref_code, amount, prepay_id=None):
        """创建订单的辅助方法"""
        return cls.create(
            out_trade_no=out_trade_no,
            openid=openid,
            birth_info=birth_info,  # 如果birth_info是dict，需要用json.dumps
            ref_code=ref_code,
            amount=amount,
            prepay_id=prepay_id,
            status='NOTPAY',
            create_time=int(time.time())
        )
    
    def to_dict(self):
        """转换为字典"""
        import json
        return {
            'out_trade_no': self.out_trade_no,
            'openid': self.openid,
            'birth_info': json.loads(self.birth_info) if self.birth_info else None,
            'ref_code': self.ref_code,
            'amount': self.amount,
            'prepay_id': self.prepay_id,
            'status': self.status,
            'create_time': self.create_time,
            'pay_time': self.pay_time,
            'transaction_id': self.transaction_id
        }


class User(BaseModel):
    """
    用户表模型
    """
    # 主键ID
    id = BigAutoField(primary_key=True, constraints=[SQL('AUTO_INCREMENT')])
    
    # 微信相关字段
    wechat_unionid = CharField(max_length=128, null=True, unique=True, verbose_name='微信开放平台unionid')
    web_openid = CharField(max_length=128, null=True, index=True, verbose_name='网站应用openid')
    mobile_openid = CharField(max_length=128, null=True, index=True, verbose_name='移动应用openid')
    
    # 基本信息
    nickname = CharField(max_length=100, null=True, verbose_name='用户昵称')
    
    # 财务相关
    balance = DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name='用户余额')
    
    # 时间字段
    created_time = DateTimeField(default=datetime.datetime.now, verbose_name='创建时间')
    updated_time = DateTimeField(default=datetime.datetime.now, verbose_name='更新时间')
    ref_code = CharField(max_length=100, null=True, verbose_name='邀请码')
    total_earned = DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name='累计收益(分)')

    class Meta:
        table_name = 'user'
        indexes = (
            # 复合索引示例（如果需要）
            # (('wechat_unionid', 'web_openid'), False),
        )
    
    def save(self, *args, **kwargs):
        # 自动更新updated_time
        self.updated_time = datetime.datetime.now()
        return super(User, self).save(*args, **kwargs)




class Product(BaseModel):
    """产品表"""
    id = AutoField(primary_key=True)
    name = CharField(max_length=100, verbose_name='产品名称')
    desc = CharField(max_length=200, null=True, verbose_name='产品描述')
    icon = CharField(max_length=20, default='🔒', verbose_name='图标emoji')
    url_path = CharField(max_length=200, verbose_name='产品URL路径')
    base_price = IntegerField(verbose_name='保底价(分)')       # 用户定价不能低于此
    recommended_price = IntegerField(verbose_name='推荐价(分)')  # 默认推荐价
    max_price = IntegerField(verbose_name='最高价(分)')         # 用户定价不能高于此
    commission_rate = IntegerField(default=45, verbose_name='佣金比例%')
    is_active = BooleanField(default=True, verbose_name='是否上架')
    created_time = DateTimeField(default=datetime.datetime.now)

    class Meta:
        table_name = 'product'


class UserProductPrice(BaseModel):
    """用户自定义产品价格表"""
    id = AutoField(primary_key=True)
    user_id = IntegerField(verbose_name='用户ID')
    product_id = IntegerField(verbose_name='产品ID')
    custom_price = IntegerField(verbose_name='自定义价格(分)')
    updated_time = DateTimeField(default=datetime.datetime.now)

    class Meta:
        table_name = 'user_product_price'
        indexes = (
            (('user_id', 'product_id'), True),  # 联合唯一索引
        )


class Report(BaseModel):
    """年运报告存储表"""
    id = AutoField()
    order_no = CharField(max_length=64, unique=True, index=True)  # 关联订单号
    user_id = IntegerField(index=True)                            # 用户ID
    
    # 八字信息
    bazi_str = CharField(max_length=64, default="")               # "癸酉 己未 辛丑 戊子"
    birth_info_json = CharField(null=True)                     # 原始出生信息JSON
    
    # 报告内容
    report_json = CharField(null=True)                          # 完整报告JSON（可能很大）
    
    # 状态
    status = CharField(max_length=20, default="pending")           # pending/generating/completed/failed
    error_msg = TextField(default="")                              # 失败原因
    
    # 时间
    created_at = DateTimeField(default=datetime.datetime.now)
    completed_at = DateTimeField(null=True)

    class Meta:
        table_name = 'reports'