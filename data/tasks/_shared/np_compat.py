"""
Чисто-питоновский полифилл (fallback) для подмножества NumPy, используемого пакетом astrosim.
Позволяет запускать оригинальные модули astrosim (models, analysis, tasks) внутри контейнера
astroprak core (где в pyproject.toml по умолчанию не установлен пакет numpy) без пересборки Docker-образа.
Если в окружении установлен настоящий numpy, используется он.
"""
from __future__ import annotations

import math
import random as _py_random
import sys
from typing import Any, Iterable

pi = math.pi


class ndarray:
    """Компактная 1D/2D обёртка над списками Python с поддержкой векторных операций astrosim."""

    def __init__(self, data: Any, dtype: Any = float):
        if isinstance(data, ndarray):
            raw = data._data
        elif isinstance(data, (list, tuple)):
            raw = list(data)
        elif isinstance(data, Iterable) and not isinstance(data, (str, bytes)):
            raw = list(data)
        else:
            raw = [data]

        if raw and isinstance(raw[0], (list, tuple, ndarray)):
            self._ndim = 2
            self._data = [
                [dtype(x) if dtype else x for x in (row._data if isinstance(row, ndarray) else row)]
                for row in raw
            ]
        else:
            self._ndim = 1
            self._data = [dtype(x) if dtype else x for x in raw]

    @property
    def size(self) -> int:
        if self._ndim == 1:
            return len(self._data)
        return sum(len(r) for r in self._data)

    @property
    def shape(self) -> tuple[int, ...]:
        if self._ndim == 1:
            return (len(self._data),)
        return (len(self._data), len(self._data[0]) if self._data else 0)

    @property
    def T(self) -> ndarray:
        if self._ndim == 1:
            return ndarray(list(self._data))
        rows = len(self._data)
        cols = len(self._data[0]) if rows else 0
        return ndarray([[self._data[r][c] for r in range(rows)] for c in range(cols)])

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self):
        if self._ndim == 1:
            return iter(self._data)
        return (ndarray(row) for row in self._data)

    def __getitem__(self, idx: Any) -> Any:
        if self._ndim == 2 and isinstance(idx, tuple):
            r_idx, c_idx = idx
            rows = self._data[r_idx] if isinstance(r_idx, slice) else [self._data[r_idx]]
            if isinstance(c_idx, slice):
                sub = [r[c_idx] for r in rows]
                return ndarray(sub if isinstance(r_idx, slice) else sub[0])
            else:
                sub = [r[c_idx] for r in rows]
                return ndarray(sub) if isinstance(r_idx, slice) else sub[0]
        if isinstance(idx, ndarray):
            return ndarray([x for x, flag in zip(self._data, idx._data) if flag])
        res = self._data[idx]
        if isinstance(res, list):
            return ndarray(res)
        return res

    def __setitem__(self, idx: Any, value: Any) -> None:
        if isinstance(idx, ndarray):
            if isinstance(value, ndarray):
                vi = iter(value._data)
                for i, flag in enumerate(idx._data):
                    if flag:
                        self._data[i] = float(next(vi))
            else:
                for i, flag in enumerate(idx._data):
                    if flag:
                        self._data[i] = float(value)
            return
        self._data[idx] = value

    def max(self) -> float:
        if self._ndim == 1:
            return max(self._data)
        return max(max(r) for r in self._data)

    def min(self) -> float:
        if self._ndim == 1:
            return min(self._data)
        return min(min(r) for r in self._data)

    def _binop(self, other: Any, op) -> ndarray:
        if isinstance(other, ndarray):
            if self._ndim == 1 and other._ndim == 1:
                return ndarray([op(a, b) for a, b in zip(self._data, other._data)], dtype=None)
            if self._ndim == 2 and other._ndim == 2:
                return ndarray(
                    [[op(a, b) for a, b in zip(r1, r2)] for r1, r2 in zip(self._data, other._data)],
                    dtype=None,
                )
        if self._ndim == 1:
            return ndarray([op(a, other) for a in self._data], dtype=None)
        return ndarray([[op(a, other) for a in r] for r in self._data], dtype=None)

    def __add__(self, other: Any) -> ndarray:
        return self._binop(other, lambda a, b: a + b)

    def __radd__(self, other: Any) -> ndarray:
        return self._binop(other, lambda a, b: b + a)

    def __sub__(self, other: Any) -> ndarray:
        return self._binop(other, lambda a, b: a - b)

    def __rsub__(self, other: Any) -> ndarray:
        return self._binop(other, lambda a, b: b - a)

    def __mul__(self, other: Any) -> ndarray:
        return self._binop(other, lambda a, b: a * b)

    def __rmul__(self, other: Any) -> ndarray:
        return self._binop(other, lambda a, b: b * a)

    def __truediv__(self, other: Any) -> ndarray:
        return self._binop(other, lambda a, b: a / b)

    def __rtruediv__(self, other: Any) -> ndarray:
        return self._binop(other, lambda a, b: b / a)

    def __pow__(self, other: Any) -> ndarray:
        return self._binop(other, lambda a, b: a ** b)

    def __neg__(self) -> ndarray:
        if self._ndim == 1:
            return ndarray([-a for a in self._data])
        return ndarray([[-a for a in r] for r in self._data])

    def __abs__(self) -> ndarray:
        if self._ndim == 1:
            return ndarray([builtins_abs(a) for a in self._data])
        return ndarray([[builtins_abs(a) for a in r] for r in self._data])

    def __lt__(self, other: Any) -> ndarray:
        return self._binop(other, lambda a, b: a < b)

    def __le__(self, other: Any) -> ndarray:
        return self._binop(other, lambda a, b: a <= b)

    def __gt__(self, other: Any) -> ndarray:
        return self._binop(other, lambda a, b: a > b)

    def __ge__(self, other: Any) -> ndarray:
        return self._binop(other, lambda a, b: a >= b)

    def __and__(self, other: Any) -> ndarray:
        return self._binop(other, lambda a, b: bool(a) and bool(b))

    def __matmul__(self, other: Any) -> Any:
        other_arr = other if isinstance(other, ndarray) else ndarray(other)
        if self._ndim == 1 and other_arr._ndim == 1:
            return sum(a * b for a, b in zip(self._data, other_arr._data))
        if self._ndim == 2 and other_arr._ndim == 1:
            return ndarray([sum(a * b for a, b in zip(row, other_arr._data)) for row in self._data])
        if self._ndim == 1 and other_arr._ndim == 2:
            cols = len(other_arr._data[0])
            return ndarray([
                sum(self._data[r] * other_arr._data[r][c] for r in range(len(self._data)))
                for c in range(cols)
            ])
        rows = len(self._data)
        cols = len(other_arr._data[0])
        inner = len(other_arr._data)
        return ndarray([
            [sum(self._data[i][k] * other_arr._data[k][j] for k in range(inner)) for j in range(cols)]
            for i in range(rows)
        ])

    def __float__(self) -> float:
        if self._ndim == 1 and len(self._data) == 1:
            return float(self._data[0])
        raise TypeError("only length-1 arrays can be converted to Python scalars")

    def __repr__(self) -> str:
        return f"ndarray({self._data!r})"


builtins_abs = abs
builtins_round = round


def asarray(a: Any, dtype: Any = float) -> ndarray | float:
    if isinstance(a, ndarray):
        return a
    if isinstance(a, (int, float)):
        return float(a) if dtype is float else a
    return ndarray(a, dtype=dtype)


def array(a: Any, dtype: Any = float) -> ndarray:
    return ndarray(a, dtype=dtype)


def ones_like(a: ndarray) -> ndarray:
    return ndarray([1.0 for _ in range(len(a))])


def _ufunc1(fn):
    def wrapper(x: Any):
        if isinstance(x, ndarray):
            if x._ndim == 1:
                return ndarray([fn(float(v)) for v in x._data])
            return ndarray([[fn(float(v)) for v in r] for r in x._data])
        if isinstance(x, (list, tuple)):
            return ndarray([fn(float(v)) for v in x])
        return fn(float(x))
    return wrapper


sin = _ufunc1(math.sin)
cos = _ufunc1(math.cos)
exp = _ufunc1(math.exp)
log = _ufunc1(math.log)
sqrt = _ufunc1(math.sqrt)
abs = _ufunc1(builtins_abs)


def hypot(a: Any, b: Any) -> Any:
    if isinstance(a, ndarray) or isinstance(b, ndarray):
        aa = a if isinstance(a, ndarray) else ndarray([a] * len(b))
        bb = b if isinstance(b, ndarray) else ndarray([b] * len(a))
        return ndarray([math.hypot(float(x), float(y)) for x, y in zip(aa._data, bb._data)])
    return math.hypot(float(a), float(b))


def mod(a: Any, m: float) -> Any:
    if isinstance(a, ndarray):
        return ndarray([float(x) % m for x in a._data])
    return float(a) % m


def where(cond: ndarray, x: Any, y: Any) -> ndarray:
    n = len(cond)
    xs = x._data if isinstance(x, ndarray) else [x] * n
    ys = y._data if isinstance(y, ndarray) else [y] * n
    return ndarray([float(xv if flag else yv) for flag, xv, yv in zip(cond._data, xs, ys)])


def clip(x: Any, lo: float, hi: float) -> Any:
    if isinstance(x, ndarray):
        return ndarray([min(hi, max(lo, float(v))) for v in x._data])
    return min(hi, max(lo, float(x)))


def round(x: Any, decimals: int = 0) -> Any:
    if isinstance(x, ndarray):
        return ndarray([builtins_round(float(v), decimals) for v in x._data])
    return builtins_round(float(x), decimals)


def sort(x: Any) -> ndarray:
    arr = x._data if isinstance(x, ndarray) else list(x)
    return ndarray(sorted(arr))


def linspace(start: float, stop: float, num: int) -> ndarray:
    if num <= 1:
        return ndarray([float(start)])
    step = (stop - start) / (num - 1)
    return ndarray([start + i * step for i in range(num)])


def arange(start: float, stop: float, step: float = 1.0) -> ndarray:
    out = []
    cur = float(start)
    while cur < stop - 1e-12:
        out.append(cur)
        cur += step
    return ndarray(out)


def concatenate(arrays: Iterable[Any]) -> ndarray:
    out = []
    for a in arrays:
        out.extend(a._data if isinstance(a, ndarray) else list(a))
    return ndarray(out)


def column_stack(cols: Iterable[Any]) -> ndarray:
    col_lists = [c._data if isinstance(c, ndarray) else list(c) for c in cols]
    n_rows = len(col_lists[0]) if col_lists else 0
    return ndarray([[col[r] for col in col_lists] for r in range(n_rows)])


class _Linalg:
    @staticmethod
    def inv(mat: ndarray) -> ndarray:
        """Обращение квадратной матрицы методом Гаусса—Жордана."""
        n = len(mat._data)
        aug = [
            [float(mat._data[i][j]) for j in range(n)] + [1.0 if i == j else 0.0 for j in range(n)]
            for i in range(n)
        ]
        for col in range(n):
            pivot = max(range(col, n), key=lambda r: builtins_abs(aug[r][col]))
            aug[col], aug[pivot] = aug[pivot], aug[col]
            div = aug[col][col]
            if builtins_abs(div) < 1e-15:
                div = 1e-15
            for j in range(2 * n):
                aug[col][j] /= div
            for r in range(n):
                if r != col:
                    factor = aug[r][col]
                    for j in range(2 * n):
                        aug[r][j] -= factor * aug[col][j]
        return ndarray([row[n:] for row in aug])

    @staticmethod
    def lstsq(x: ndarray, y: ndarray, rcond: Any = None):
        """МНК-решение: beta = (X^T X)^(-1) X^T y."""
        xtx = x.T @ x
        xty = x.T @ y
        beta = _Linalg.inv(xtx) @ xty
        return beta, ndarray([]), x.shape[1], ndarray([])


linalg = _Linalg()


class Generator:
    """Генератор псевдослучайных чисел, совместимый по API с numpy.random.Generator."""

    def __init__(self, seed: int | None = None):
        self._rng = _py_random.Random(seed)

    def uniform(self, low: float = 0.0, high: float = 1.0, size: int | None = None) -> float | ndarray:
        if size is None:
            return self._rng.uniform(low, high)
        return ndarray([self._rng.uniform(low, high) for _ in range(size)])

    def normal(self, loc: float = 0.0, scale: float = 1.0, size: int | None = None) -> float | ndarray:
        if size is None:
            return self._rng.gauss(loc, scale)
        return ndarray([self._rng.gauss(loc, scale) for _ in range(size)])

    def integers(self, low: int, high: int | None = None, size: int | None = None) -> int | ndarray:
        if high is None:
            low, high = 0, low
        if size is None:
            return self._rng.randrange(int(low), int(high))
        return ndarray([self._rng.randrange(int(low), int(high)) for _ in range(size)])

    def choice(self, seq: Any, size: int | None = None) -> Any:
        items = seq._data if isinstance(seq, ndarray) else list(seq)
        if size is None:
            return self._rng.choice(items)
        return ndarray([self._rng.choice(items) for _ in range(size)])

    def shuffle(self, arr: Any) -> None:
        if isinstance(arr, ndarray):
            self._rng.shuffle(arr._data)
        else:
            self._rng.shuffle(arr)


class _RandomModule:
    Generator = Generator

    @staticmethod
    def default_rng(seed: int | None = None) -> Generator:
        return Generator(seed)


random = _RandomModule()


def ensure_numpy():
    """Подключает настоящий numpy, а при его отсутствии в контейнере регистрирует этот модуль как 'numpy'."""
    try:
        import numpy as real_np
        return real_np
    except ImportError:
        sys.modules["numpy"] = sys.modules[__name__]
        return sys.modules[__name__]
