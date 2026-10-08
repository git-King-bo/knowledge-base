"""显式启用：MYSQL_TEST_ENABLED=1 APP_DATABASE_MODE=mysql python -m unittest discover -s tests -p test_mysql_integration.py -v

只插入随机测试记录，并始终回滚事务；不启动应用、不调用模型、不修改已有业务数据。
"""
import os
import unittest
from uuid import uuid4
from sqlalchemy.orm import Session


@unittest.skipUnless(os.getenv('MYSQL_TEST_ENABLED') == '1', 'explicit MySQL test opt-in required')
class MySQLIntegrationTests(unittest.TestCase):
    def test_long_text_budget_and_timezone_statistics(self):
        from app.db.session import engine
        from app.db.models import KnowledgeSourceModel, TalentModel, AIActivityLogModel, TokenUsageModel, RequestBudgetModel
        from app.core.security import now
        from app.core.limits import ensure_budget
        from app.api.routes.usage import overview, UsageFilter
        from app.api.routes.workspace import talent_order
        from sqlalchemy import select
        self.assertEqual(engine.dialect.name, 'mysql')
        marker = str(uuid4())
        with Session(engine) as db:
            try:
                db.add(KnowledgeSourceModel(id=marker, filename='mysql-test.txt', storage_path='unused',
                       content_text='测试🙂' * 30000, created_at=now(), updated_at=now()))
                db.flush()
                db.add(TalentModel(id=marker, source_id=marker, sheet_name='测试', source_row=1,
                       raw_data_json='{}', formulas_json='{}', created_at=now(), name='测试姓名🙂'))
                db.add(AIActivityLogModel(id=marker, action='ask', provider_id=marker, model='test',
                       success=True, request_text='问' * 30000, response_text='答', created_at=now()))
                db.flush()
                db.add(TokenUsageModel(log_id=marker, input_tokens=10, output_tokens=2, total_tokens=12))
                ensure_budget(db, marker, now().date().isoformat())
                budget = db.get(RequestBudgetModel, (marker, now().date().isoformat()))
                budget.tokens, budget.requests = 12, 1
                db.flush()
                ensure_budget(db, marker, now().date().isoformat())
                db.expire_all()
                self.assertEqual(budget.tokens, 12)
                self.assertEqual(len(db.get(KnowledgeSourceModel, marker).content_text), 90000)
                self.assertEqual(db.scalar(select(TalentModel.id).where(TalentModel.id == marker)
                                           .order_by(*talent_order('openalex_h_index', 'desc'))), marker)
                result = overview(filters=UsageFilter(days=7, provider_id=marker, timezone_offset=480), page=1, page_size=20, db=db)
                self.assertEqual(result['summary']['total_tokens'], 12)
                self.assertEqual(sum(day['total_tokens'] for day in result['daily']), 12)
            finally:
                db.rollback()
