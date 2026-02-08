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
    "databank",
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
