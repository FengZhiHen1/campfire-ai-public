"""py-db Repository 层 — 数据库操作封装。

所有数据库操作必须通过 Repository 类执行，
禁止在 Service 层直接调用 session.execute() 或拼接 SQL。
"""
