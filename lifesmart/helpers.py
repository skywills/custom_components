from typing import Any
# ====================================================================
# 通用辅助函数
# ====================================================================
def safe_get(data: dict | list, *path, default: Any = None) -> Any:
    """
    安全地根据路径从嵌套的字典或列表中取值。

    如果路径中的任何一个键或索引不存在，则返回默认值，避免了 KeyError 或 IndexError。

    Args:
        data: 要查询的源数据（字典或列表）。
        *path: 一个或多个键或索引，代表访问路径。
        default: 如果路径无效，返回的默认值。

    Returns:
        获取到的值，或默认值。
    """
    cur = data
    for key in path:
        if isinstance(cur, dict):
            cur = cur.get(key, default)
        elif isinstance(cur, list) and isinstance(key, int):
            try:
                cur = cur[key]
            except IndexError:
                return default
        else:
            return default
    return cur