from datetime import datetime
import unittest
from sqlalchemy import create_engine, select
from app.db.session import Base
from app.db import models
from scripts.migrate_sqlite_to_mysql import merge


class MergeTests(unittest.TestCase):
    def test_maps_account_preserves_target_and_merges_usage(self):
        source = create_engine('sqlite://')
        target = create_engine('sqlite://')
        Base.metadata.create_all(source)
        Base.metadata.create_all(target)
        users = Base.metadata.tables['users']
        budgets = Base.metadata.tables['request_budgets']
        conversations = Base.metadata.tables['saved_conversations']
        with source.begin() as s, target.begin() as t:
            for connection, uid, password in [(s,'old','old-password'), (t,'new','new-password')]:
                connection.execute(users.insert().values(id=uid, username='admin', password_hash=password,
                    role='admin', enabled=True, created_at=datetime.now()))
                connection.execute(budgets.insert().values(user_id=uid,day='2026-10-08',requests=1,tokens=50,reserved=0))
            s.execute(conversations.insert().values(id='conversation', user_id='old',title='历史',
                messages_json='[]', favorite=False, feedback='', updated_at=datetime.now()))
            preview=merge(s,t)
            self.assertEqual(preview['saved_conversations']['inserted'],1)
            self.assertEqual(t.scalar(select(budgets.c.tokens)),50)
            merge(s,t,apply=True)
            self.assertEqual(t.scalar(select(users.c.password_hash)),'new-password')
            self.assertEqual(t.scalar(select(conversations.c.user_id)),'new')
            self.assertEqual(t.scalar(select(budgets.c.tokens)),100)
        source.dispose();target.dispose()

    def test_business_collision_aborts_preflight(self):
        source = create_engine('sqlite://')
        target = create_engine('sqlite://')
        Base.metadata.create_all(source);Base.metadata.create_all(target)
        table=Base.metadata.tables['categories']
        with source.begin() as s, target.begin() as t:
            s.execute(table.insert().values(id='same', name='source'))
            t.execute(table.insert().values(id='same', name='target'))
            with self.assertRaisesRegex(RuntimeError,'Conflicting'):
                merge(s,t)
            self.assertEqual(t.scalar(select(table.c.name)),'target')
        source.dispose();target.dispose()
