"""缓存服务模块。

提供内存缓存能力，支持 TTL 和最大条目限制。
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

from src.core.config import CacheConfig, get_config


class MemoryCache:
    """基于 OrderedDict 的 LRU 缓存，线程安全。"""

    def __init__(self, config: CacheConfig | None = None) -> None:
        self._config = config or get_config().cache
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        """获取缓存值，不存在或过期返回 None。"""
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            ts, value = item
            if time.time() - ts > self._config.ttl_seconds:
                self._store.pop(key, None)
                return None
            # 移到末尾（LRU）
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: Any) -> None:
        """设置缓存值。"""
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (time.time(), value)
            self._evict()

    def delete(self, key: str) -> None:
        """删除缓存条目。"""
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        """清空缓存。"""
        with self._lock:
            self._store.clear()

    @property
    def size(self) -> int:
        """当前缓存条目数。"""
        with self._lock:
            return len(self._store)

    def _evict(self) -> None:
        """淘汰过期和超限条目（需在锁内调用）。"""
        now = time.time()
        # 淘汰过期条目
        expired = [k for k, (ts, _) in self._store.items() if now - ts > self._config.ttl_seconds]
        for k in expired:
            self._store.pop(k, None)
        # 淘汰超限条目（LRU）
        while len(self._store) > self._config.max_entries:
            self._store.popitem(last=False)


# 全局缓存实例
_cache: MemoryCache | None = None


def get_cache() -> MemoryCache:
    """获取全局缓存实例。"""
    global _cache
    if _cache is None:
        _cache = MemoryCache()
    return _cache
