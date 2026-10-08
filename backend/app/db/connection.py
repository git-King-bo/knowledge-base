"""启动时选择数据库；失败日志不包含连接串、用户信息或密码。"""
import logging

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError

logger = logging.getLogger(__name__)


def build_engine(url, timeout=5):
    url = make_url(url)
    if url.get_backend_name() == 'sqlite':
        engine = create_engine(url, connect_args={'check_same_thread': False})

        @event.listens_for(engine, 'connect')
        def sqlite_options(connection, record):
            cursor = connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.execute('PRAGMA busy_timeout=10000')
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.close()
        return engine
    if url.get_backend_name() != 'mysql':
        raise ValueError('Only MySQL and SQLite are supported')
    return create_engine(url.set(drivername='mysql+pymysql'), pool_pre_ping=True,
                         pool_recycle=1800, hide_parameters=True,
                         connect_args={'connect_timeout': timeout, 'read_timeout': 30,
                                       'write_timeout': 30, 'charset': 'utf8mb4'})


def select_engine(settings):
    """auto 只对连接/认证失败回退，迁移和业务 SQL 错误必须显式修复。"""
    base_url = make_url(settings.database_url)
    sqlite_url = base_url if base_url.get_backend_name() == 'sqlite' else make_url(settings.sqlite_fallback_url)
    if sqlite_url.get_backend_name() != 'sqlite':
        raise ValueError('APP_SQLITE_FALLBACK_URL must use SQLite')
    if settings.database_mode == 'sqlite':
        return build_engine(sqlite_url)

    mysql_url = None
    if settings.mysql_host:
        if not settings.mysql_database or not settings.mysql_user:
            raise ValueError('MySQL host requires XINIU_MYSQL_DATABASE and XINIU_MYSQL_USER')
        # URL.create 会正确处理密码里的 @、:、/ 等特殊字符。
        mysql_url = URL.create('mysql+pymysql', username=settings.mysql_user,
                               password=settings.mysql_password.get_secret_value(),
                               host=settings.mysql_host, port=settings.mysql_port,
                               database=settings.mysql_database)
    elif base_url.get_backend_name() == 'mysql':
        mysql_url = base_url
    elif base_url.get_backend_name() != 'sqlite':
        raise ValueError('Only MySQL and SQLite are supported')
    if mysql_url is None:
        if settings.database_mode == 'mysql':
            raise ValueError('MySQL configuration is required in mysql mode')
        return build_engine(sqlite_url)

    candidate = build_engine(mysql_url, settings.mysql_connect_timeout)
    try:
        # 只探测连接，不自动创建数据库或修改远端表。
        with candidate.connect() as connection:
            connection.execute(text('SELECT 1'))
    except DBAPIError as error:
        candidate.dispose()
        if settings.database_mode == 'mysql':
            raise RuntimeError('MySQL connection failed; fallback disabled') from None
        code = getattr(error.orig, 'args', (None,))[0]
        safe_code = code if isinstance(code, int) else 'unknown'
        logger.warning('MySQL connection failed (code=%s); using SQLite for this process. '
                       'Data is not synchronized between databases.', safe_code)
        return build_engine(sqlite_url)
    logger.info('Database selected: MySQL')
    return candidate
