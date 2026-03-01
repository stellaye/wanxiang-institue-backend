import json
import datetime
import logging
from peewee import fn
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


class AdminFeedbackListHandler(LoggedRequestHandler):
    """GET /wanxiang/api/admin/feedback?page=1&page_size=20&feedback_type=correction"""

    async def get(self):
        try:
            page = max(int(self.get_argument("page", "1")), 1)
            page_size = min(max(int(self.get_argument("page_size", "20")), 1), 200)
        except Exception:
            self.write_json({"success": False, "msg": "分页参数格式错误"})
            return

        feedback_type = (self.get_argument("feedback_type", "") or "").strip()
        page_key = (self.get_argument("page_key", "") or "").strip()
        category_id = (self.get_argument("category_id", "") or "").strip()

        where = []
        if feedback_type in ("correction", "suggestion"):
            where.append(Feedback.feedback_type == feedback_type)
        if page_key:
            where.append(Feedback.page == page_key)
        if category_id:
            where.append(Feedback.category_id == category_id)

        try:
            total = await (
                Feedback
                .select(fn.COUNT(Feedback.id))
                .where(*where)
                .aio_scalar()
            ) or 0

            offset = (page - 1) * page_size
            rows = await (
                Feedback
                .select()
                .where(*where)
                .order_by(Feedback.created_at.desc(), Feedback.id.desc())
                .offset(offset)
                .limit(page_size)
                .aio_execute()
            )

            feedbacks = []
            for row in rows:
                created_at = ""
                if row.created_at and isinstance(row.created_at, datetime.datetime):
                    created_at = row.created_at.strftime("%Y-%m-%d %H:%M:%S")
                elif row.created_at:
                    created_at = str(row.created_at)

                feedbacks.append({
                    "id": int(row.id),
                    "page": row.page or "",
                    "category_id": row.category_id or "",
                    "article_index": int(row.article_index or 0),
                    "article_title": row.article_title or "",
                    "feedback_type": row.feedback_type or "correction",
                    "content": row.content or "",
                    "contact": row.contact or "",
                    "user_agent": row.user_agent or "",
                    "created_at": created_at,
                })

            self.write_json({
                "success": True,
                "feedbacks": feedbacks,
                "total": int(total),
                "page": page,
                "page_size": page_size,
                "has_more": (offset + page_size) < int(total),
            })
        except Exception as e:
            logger.error(f"获取反馈列表失败: {e}")
            self.write_json({"success": False, "msg": "获取反馈列表失败，请稍后重试"})
