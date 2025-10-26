import numpy as np
import copy
from typing import Any, Dict, List, Optional


class AnimationNormalizer:
    """
    Нормализует разрозненные ключи анимации на общую сетку времени (шаг 1/fps)
    ДЛЯ МАССИВА ОБЪЕКТОВ и возвращает исходные объекты с перезаписанным data/anim.

    Ожидаемые пути в каждом объекте:
      - data/anim                : словарь с кривыми (translation/rotation/scaling → x|y|z → {keys, values})
      - data/translation         : [tx, ty, tz]  (обязательно; если нет — объект не трогаем)
      - data/scaling             : [sx, sy, sz]  (необязательно; по умолчанию [1,1,1])
      - data/rotation            : [rx, ry, rz]  (необязательно; по умолчанию [0,0,0] — эйлеры)
    """

    def __init__(self, fps: float = 24.0):
        if fps <= 0:
            raise ValueError("fps must be > 0")
        self.fps = float(fps)

    # ---------- utils ----------
    @staticmethod
    def _get_path(obj: Dict[str, Any], path: str, default: Any = None) -> Any:
        cur = obj
        for p in path.split("/"):
            if not isinstance(cur, dict) or p not in cur:
                return default
            cur = cur[p]
        return cur

    @staticmethod
    def _ensure_path(obj: Dict[str, Any], path: str) -> Dict[str, Any]:
        """Гарантирует существование промежуточных словарей, возвращает последний словарь по пути."""
        cur = obj
        for p in path.split("/"):
            nxt = cur.get(p)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[p] = nxt
            cur = nxt
        return cur

    @staticmethod
    def _sorted_unique_pairs(keys, values):
        if not keys or not values:
            return np.array([], dtype=float), np.array([], dtype=float)
        k = np.asarray(keys, dtype=float)
        v = np.asarray(values, dtype=float)
        idx = np.argsort(k, kind="stable")
        k, v = k[idx], v[idx]
        uniq_k, inv = np.unique(k, return_inverse=True)
        out_v = np.zeros_like(uniq_k, dtype=float)
        for i in range(len(k)):  # последнее значение для дубликатов
            out_v[inv[i]] = v[i]
        return uniq_k, out_v

    def _collect_all_times(self, curves: Dict[str, Any]) -> np.ndarray:
        times = []
        for ttype in curves.values():
            if not isinstance(ttype, dict):
                continue
            for axis in ttype.values():
                if not isinstance(axis, dict):
                    continue
                k = axis.get("keys")
                if k:
                    times.extend(k)
        return np.unique(np.asarray(times, dtype=float)) if times else np.array([], dtype=float)

    def _make_time_grid(self, tmin: float, tmax: float) -> np.ndarray:
        step = 1.0 / self.fps
        if tmax < tmin:
            tmin, tmax = tmax, tmin
        if np.isclose(tmax, tmin):
            return np.array([tmin], dtype=float)
        n = int(np.ceil((tmax - tmin) / step)) + 1
        grid = tmin + np.arange(n, dtype=float) * step
        if grid[-1] + 1e-9 < tmax:
            grid = np.append(grid, grid[-1] + step)
        return grid

    @staticmethod
    def _flat_series(val: float, grid: np.ndarray):
        return {"keys": grid.tolist(), "values": np.full(grid.shape, float(val), dtype=float).tolist()}

    def _normalize_one(
        self,
        curves: Dict[str, Any],
        rest_translation: List[float],
        rest_scaling: Optional[List[float]],
        rest_rotation: Optional[List[float]],
    ) -> Dict[str, Any]:
        """Возвращает новые нормализованные кривые (dict), рассчитанные на общей сетке времени.
        Если для конкретного ttype (translation/scaling/rotation) x/y/z пустые — оставляем как есть.
        """
        # rest-значения
        rt = {"x": float(rest_translation[0]), "y": float(rest_translation[1]), "z": float(rest_translation[2])}
        rs = {"x": 1.0, "y": 1.0, "z": 1.0} if rest_scaling is None else {
            "x": float(rest_scaling[0]), "y": float(rest_scaling[1]), "z": float(rest_scaling[2])
        }
        rr = {"x": 0.0, "y": 0.0, "z": 0.0} if rest_rotation is None else {
            "x": float(rest_rotation[0]), "y": float(rest_rotation[1]), "z": float(rest_rotation[2])
        }

        def _has_any_keys(axes_dict: Dict[str, Any]) -> bool:
            if not isinstance(axes_dict, dict):
                return False
            for ax in ("x", "y", "z"):
                axis = axes_dict.get(ax, {})
                keys = axis.get("keys", [])
                if isinstance(keys, (list, tuple)) and len(keys) > 0:
                    return True
            return False

        curves = curves if isinstance(curves, dict) else {}
        all_times = self._collect_all_times(curves)

        # Если ключей вообще нигде нет — ничего не делаем
        if all_times.size == 0:
            return curves

        t_min, t_max = float(all_times.min()), float(all_times.max())
        grid = self._make_time_grid(t_min, t_max)

        normalized: Dict[str, Any] = {}
        for ttype in ("translation", "scaling", "rotation"):
            axes_in = curves.get(ttype, {}) if isinstance(curves, dict) else {}

            # >>> ВАЖНО: если у данного ttype нет ключей ни по одной оси — оставляем как есть
            # if not _has_any_keys(axes_in):
                # Ничего не трогаем — ни добавления осей, ни плоских серий
                # if axes_in:  # если раздел существовал — копируем как есть
                    # normalized[ttype] = axes_in
                # если раздела даже не было, тоже ничего не добавляем
                # continue

            # Иначе нормализуем этот ttype на общей сетке
            normalized[ttype] = {}
            for axis_name in ("x", "y", "z"):
                axis = axes_in.get(axis_name, {}) if isinstance(axes_in, dict) else {}
                keys, vals = self._sorted_unique_pairs(axis.get("keys", []), axis.get("values", []))

                if vals.size < 1:
                    base = rt if ttype == "translation" else (rs if ttype == "scaling" else rr)
                    normalized[ttype][axis_name] = self._flat_series(base[axis_name], grid)
                elif vals.size == 1:
                    normalized[ttype][axis_name] = self._flat_series(vals[0], grid)
                else:
                    interp = np.interp(grid, keys, vals, left=vals[0], right=vals[-1])
                    normalized[ttype][axis_name] = {
                        "keys": grid.tolist(),
                        "values": interp.astype(float).tolist()
                    }

            # Добавляем недостающие оси только для активного ttype (у которого были ключи)
            base = rt if ttype == "translation" else (rs if ttype == "scaling" else rr)
            # print(normalized)
            for ax in ("x", "y", "z"):
                if ax not in normalized[ttype]:
                    normalized[ttype][ax] = self._flat_series(base[ax], grid)

        return normalized


    # ---------- публичный батч ----------
    def normalize(self, objects: List[Dict[str, Any]], inplace: bool = False) -> List[Dict[str, Any]]:
        """
        Возвращает массив объектов той же длины:
          - если у объекта есть data/translation — пересчитывает data/anim и подменяет его
          - если нет — объект возвращается без изменений
        По умолчанию НЕ мутирует вход (делает глубокую копию). Укажи inplace=True, чтобы менять на месте.
        """
        if not isinstance(objects, list):
            return []

        out = objects if inplace else copy.deepcopy(objects)

        for i, obj in enumerate(out):
            rest_translation = self._get_path(obj, "data/translation", None)
            if rest_translation is None:
                # пропускаем: ничего не меняем
                continue

            rest_scaling = self._get_path(obj, "data/scaling", None)
            rest_rotation = self._get_path(obj, "data/rotation", None)
            curves = self._get_path(obj, "data/anim", {}) or {}

            normalized_curves = self._normalize_one(
                curves=curves,
                rest_translation=rest_translation,
                rest_scaling=rest_scaling,
                rest_rotation=rest_rotation,
            )

            # гарантируем наличие data и перезаписываем anim
            data_dict = self._ensure_path(obj, "data")
            data_dict["anim"] = normalized_curves

        return out
