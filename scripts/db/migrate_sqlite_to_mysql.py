# SQLite → MySQL 数据迁移脚本（一次性工具）
#
# 用法（在项目根目录执行）：
#   py -3 scripts/db/migrate_sqlite_to_mysql.py
# 连接参数全部从 .env 读取，脚本内不再写死任何密码。
import os
import sys

from dotenv import load_dotenv

# 项目根目录：scripts/db/ 往上两级
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(PROJECT_ROOT, '.env'))

import sqlite3
import pymysql
import json
import re

# 源 SQLite 文件，默认项目根目录下的 equipment.db，可用 SQLITE_DB 覆盖
SQLITE_DB = os.environ.get('SQLITE_DB', os.path.join(PROJECT_ROOT, 'equipment.db'))

# MySQL 连接配置，与 database.py 用同一套环境变量
MYSQL_CONFIG = {
    'host': os.environ.get('MYSQL_HOST', 'localhost'),
    'port': int(os.environ.get('MYSQL_PORT', 3306)),
    'user': os.environ.get('MYSQL_USER', 'root'),
    'password': os.environ.get('MYSQL_PASSWORD', ''),
    'database': os.environ.get('MYSQL_DATABASE', 'dms_db'),
    'charset': 'utf8mb4',
}

# 需要迁移的表（按外键依赖顺序）
TABLES = [
    'users',
    'devices',
    'documents',
    'borrow_records',
    'audit_logs',
    'approval_requests',
    'approval_steps',
    'signatures',
    'system_settings',
    'password_reset_requests',
    'maintenance_plan',
    'maintenance_record',
    'device_status_requests',
]


def get_sqlite_columns(cur, table):
    """获取 SQLite 表的列信息"""
    cur.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall()]


def convert_value(value, column_name):
    """转换值以适配 MySQL"""
    if value is None:
        return None
    # 处理 JSON 字段
    if column_name == 'permissions' and isinstance(value, str):
        try:
            return json.dumps(json.loads(value))
        except:
            return value
    # 处理时间戳
    if 'time' in column_name.lower() or 'date' in column_name.lower():
        if isinstance(value, str) and 'T' in value:
            # ISO 格式时间
            value = value.replace('T', ' ').replace('Z', '')
            if '.' in value:
                value = value.split('.')[0]
    return value


def migrate_table(sqlite_cur, mysql_conn, table):
    """迁移单个表的数据"""
    # 获取 SQLite 列
    sqlite_columns = get_sqlite_columns(sqlite_cur, table)
    
    # 获取 MySQL 列（排除 AUTO_INCREMENT 的 id）
    mysql_cur = mysql_conn.cursor()
    mysql_cur.execute(f"SHOW COLUMNS FROM {table}")
    mysql_columns = [row[0] for row in mysql_cur.fetchall()]
    
    # 找出共同的列
    common_columns = [col for col in sqlite_columns if col in mysql_columns]
    if not common_columns:
        print(f"  ⚠ {table}: 无共同列，跳过")
        return 0
    
    # 查询 SQLite 数据
    sqlite_cur.execute(f"SELECT {', '.join(common_columns)} FROM {table}")
    rows = sqlite_cur.fetchall()
    
    if not rows:
        print(f"  📭 {table}: 无数据")
        return 0
    
    # 插入 MySQL
    placeholders = ', '.join(['%s'] * len(common_columns))
    columns_str = ', '.join(common_columns)
    
    # 排除已存在的记录（基于主键）
    inserted = 0
    for row in rows:
        try:
            # 转换值
            converted = tuple(convert_value(row[i], common_columns[i]) 
                            for i in range(len(common_columns)))
            
            # 构建 INSERT 语句，忽略已存在记录
            sql = f"INSERT IGNORE INTO {table} ({columns_str}) VALUES ({placeholders})"
            mysql_cur.execute(sql, converted)
            if mysql_cur.rowcount > 0:
                inserted += 1
        except Exception as e:
            print(f"    ⚠ 插入失败: {e}")
            continue
    
    mysql_conn.commit()
    return inserted


def main():
    print("=" * 50)
    print("SQLite → MySQL 数据迁移")
    print("=" * 50)
    
    # 连接 SQLite
    print("\n📂 连接 SQLite 数据库...")
    sqlite_conn = sqlite3.connect(SQLITE_DB)
    sqlite_cur = sqlite_conn.cursor()
    print(f"  ✅ 已连接: {SQLITE_DB}")
    
    # 连接 MySQL
    print("\n📂 连接 MySQL 数据库...")
    mysql_conn = pymysql.connect(**MYSQL_CONFIG)
    print(f"  ✅ 已连接: {MYSQL_CONFIG['database']}")
    
    # 迁移每个表
    total_inserted = 0
    print("\n📦 开始迁移数据...")
    for table in TABLES:
        count = migrate_table(sqlite_cur, mysql_conn, table)
        if count > 0:
            print(f"  ✅ {table}: 导入 {count} 条")
        total_inserted += count
    
    # 验证结果
    print("\n📊 迁移结果验证:")
    mysql_cur = mysql_conn.cursor()
    for table in TABLES:
        try:
            mysql_cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = mysql_cur.fetchone()[0]
            print(f"  {table}: {count} 条")
        except:
            pass
    
    # 关闭连接
    sqlite_conn.close()
    mysql_conn.close()
    
    print("\n" + "=" * 50)
    print(f"✅ 迁移完成！共导入 {total_inserted} 条记录")
    print("=" * 50)


if __name__ == '__main__':
    main()
