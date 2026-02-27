import json
import datetime
import logging
from base_handler import LoggedRequestHandler
from models import Feedback

logger = logging.getLogger(__name__)


class SubmitFeedbackHandler(LoggedRequestHandler):
    """POST /wanxiang/api/feedback"""

    async def post(self):
        try:
            body = json.loads(self.request.body)

            content = (body.get("content") or "").strip()
            if not content:
                self.write_json({"success": False, "msg": "反馈内容不能为空"})
                return

            if len(content) > 2000:
                self.write_json({"success": False, "msg": "反馈内容不能超过2000字"})
                return

            page = (body.get("page") or "").strip()
            if not page:
                self.write_json({"success": False, "msg": "缺少页面标识"})
                return

            feedback_type = body.get("feedback_type", "correction")
            if feedback_type not in ("correction", "suggestion"):
                feedback_type = "correction"

            fb = Feedback(
                page=page,
                category_id=(body.get("category_id") or ""),
                article_index=int(body.get("article_index", 0)),
                article_title=(body.get("article_title") or "")[:200],
                feedback_type=feedback_type,
                content=content,
                contact=(body.get("contact") or "")[:200],
                user_agent=self.request.headers.get("User-Agent", "")[:500],
                created_at=datetime.datetime.now(),
            )
            await fb.aio_save(force_insert=True)

            self.write_json({"success": True, "msg": "感谢您的反馈！"})

        except Exception as e:
            logger.error(f"提交反馈失败: {e}")
            self.write_json({"success": False, "msg": "提交失败，请稍后重试"})
