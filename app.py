import tornado.ioloop
import tornado.web

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

# 应用路由
def make_app():
    return tornado.web.Application([
        (r"/", MainHandler),
        (r"/api", APIHandler),
        (r"/user/([0-9]+)", UserHandler),  # 动态路由
        (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": settings["static_path"]}),
    ], **settings)

# 启动应用
if __name__ == "__main__":
    app = make_app()
    app.listen(8888)  # 监听端口
    print("Server started at http://localhost:8888")
    tornado.ioloop.IOLoop.current().start()

    