"""
数据库初始化模块
"""
from dotenv import dotenv_values

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.database.connection import engine, Base
from app.database.models import Settings
from app.log.logger import get_database_logger

logger = get_database_logger()


def _migrate_request_log_columns():
    """Add request_content_length, response_content_length, total_token_count to t_request_log if missing."""
    try:
        inspector = inspect(engine)
        if "t_request_log" not in inspector.get_table_names():
            return
        columns = {c["name"] for c in inspector.get_columns("t_request_log")}
        with engine.connect() as conn:
            if "request_content_length" not in columns:
                conn.execute(text("ALTER TABLE t_request_log ADD COLUMN request_content_length INTEGER"))
                conn.commit()
                logger.info("Added request_content_length to t_request_log")
            if "total_token_count" not in columns:
                conn.execute(text("ALTER TABLE t_request_log ADD COLUMN total_token_count INTEGER"))
                conn.commit()
                logger.info("Added total_token_count to t_request_log")
            if "response_content_length" not in columns:
                conn.execute(text("ALTER TABLE t_request_log ADD COLUMN response_content_length INTEGER"))
                conn.commit()
                logger.info("Added response_content_length to t_request_log")
            if "request_body" not in columns:
                conn.execute(text("ALTER TABLE t_request_log ADD COLUMN request_body TEXT"))
                conn.commit()
                logger.info("Added request_body to t_request_log")
            if "response_body" not in columns:
                conn.execute(text("ALTER TABLE t_request_log ADD COLUMN response_body TEXT"))
                conn.commit()
                logger.info("Added response_body to t_request_log")
    except Exception as e:
        logger.warning(f"Request log migration skipped or failed: {e}")


def create_tables():
    """
    创建数据库表
    """
    try:
        # 创建所有表
        Base.metadata.create_all(engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Failed to create database tables: {str(e)}")
        raise


def import_env_to_settings():
    """
    将.env文件中的配置项导入到t_settings表中
    """
    try:
        # 获取.env文件中的所有配置项
        env_values = dotenv_values(".env")
        
        # 获取检查器
        inspector = inspect(engine)
        
         # 检查t_settings表是否存在
        if "t_settings" in inspector.get_table_names():
            # 使用Session进行数据库操作
            with Session(engine) as session:
                # 获取所有现有的配置项
                current_settings = {setting.key: setting for setting in session.query(Settings).all()}
                
                # 遍历所有配置项
                for key, value in env_values.items():
                    # 检查配置项是否已存在
                    if key not in current_settings:
                        # 插入配置项
                        new_setting = Settings(key=key, value=value)
                        session.add(new_setting)
                        logger.info(f"Inserted setting: {key}")
                
                # 提交事务
                session.commit()
                
        logger.info("Environment variables imported to settings table successfully")
    except Exception as e:
        logger.error(f"Failed to import environment variables to settings table: {str(e)}")
        raise


def initialize_database():
    """
    初始化数据库
    """
    try:
        # 创建表
        create_tables()

        # 迁移: 为 t_request_log 添加新列
        _migrate_request_log_columns()

        # 导入环境变量
        import_env_to_settings()
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
        raise
