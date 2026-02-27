"""一次性脚本：创建 feedback 表"""
from models import database, Feedback

database.create_tables([Feedback])
print("feedback 表创建成功")
