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
import json

logger = logging.getLogger(__name__)

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


    def set_default_headers(self):
        origin = self.request.headers.get("Origin")
        if origin:
            self.set_header("Access-Control-Allow-Origin", origin)
        self.set_header("Access-Control-Allow-Credentials", "true")
        self.set_header(
            "Access-Control-Allow-Headers", "x-requested-with, Content-Type, x-session-id"
        )
        self.set_header(
            "Access-Control-Allow-Methods", "POST, GET, OPTIONS, PATCH, PUT, DELETE"
            )
    # def set_default_headers(self):
    #    self.set_header("Content-Type", "application/json")

    def success_response(self, data=None):
        """成功返回"""
        self.write({"result": data})

    def error_response(self, status_code, error_code, msg=""):
        """错误返回
        :param status_code: HTTP状态码
        :param error_code: 业务错误码，使用 ErrorCode 中定义的值
        """
        self.set_status(status_code)
        self.write({"error_code": error_code, "msg": msg})

    def options(self):
        # 预检请求应该返回相同的头部
        self.set_default_headers()
        self.set_status(204)
        self.finish()
