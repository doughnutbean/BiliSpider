import sqlite3
import sys
from pathlib import Path

db = Path(__file__).resolve().parents[1] / "data" / "comments.db"
conn = sqlite3.connect(db)

# 表结构
for table in ('comments', 'crawl_progress'):
    cols = conn.execute(f'PRAGMA table_info({table})').fetchall()
    pk_info = conn.execute(f'PRAGMA index_list({table})').fetchall()
    print(f'=== {table} ===')
    for c in cols:
        pk = ' [PK]' if c[5] else ''
        print(f'  {c[1]:20s} {c[2]:10s}{pk}')

# 统计
cnt = conn.execute('SELECT COUNT(*) FROM comments').fetchone()[0]
root = conn.execute("SELECT COUNT(*) FROM comments WHERE parent=0").fetchone()[0]
sub = conn.execute("SELECT COUNT(*) FROM comments WHERE parent>0").fetchone()[0]
print(f'\n总评论: {cnt}, 一级: {root}, 子评论: {sub}')

# 测试 INSERT OR IGNORE 去重
print('\n=== 去重测试 ===')
# 找一条已有评论
existing = conn.execute('SELECT rpid,oid,type FROM comments LIMIT 1').fetchone()
if existing:
    rpid, oid, ctype = existing
    conn.execute("""INSERT OR IGNORE INTO comments
        (rpid,oid,type,mid,parent,root,ctime,message,like_count,sub_count,crawl_time)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (rpid, oid, ctype, 0, 0, 0, 0, 'test_dup', 0, 0, 0))
    conn.commit()
    cnt2 = conn.execute('SELECT COUNT(*) FROM comments').fetchone()[0]
    print(f'重复插入 rpid={rpid}: INSERT OR IGNORE 后总条数 {cnt} -> {cnt2} (相同=去重生效)')
    # 验证message没有被覆盖
    msg = conn.execute('SELECT message FROM comments WHERE rpid=?', (rpid,)).fetchone()[0]
    print(f'message仍然是: {msg[:40]} (未被覆盖=正确)')

# 数据库文件位置
size = db.stat().st_size
print(f'\n数据库位置: {db}')
print(f'文件大小: {size:,} bytes')

conn.close()
