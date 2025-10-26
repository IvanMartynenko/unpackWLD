# pivot_bake_anim.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# -----------------------------
# Вспомогательные матрицы
# -----------------------------

def mat_std_from_nmf(N_like) -> np.ndarray:
    """NMF → стандартная 4×4 (T в последнем столбце)."""
    N = np.asarray(N_like, dtype=np.float64).reshape(4,4)
    M = np.eye(4, dtype=np.float64)
    M[:3, :3] = N[:3, :3]       # та же 3x3
    M[:3, 3]  = N[3, :3]        # T берём из последней строки
    return M

def mat_nmf_from_std(M_like) -> np.ndarray:
    """Стандартная 4×4 → NMF (T в последней строке)."""
    M = np.asarray(M_like, dtype=np.float64).reshape(4,4)
    N = np.zeros((4,4), dtype=np.float64)
    N[:3, :3] = M[:3, :3]       # та же 3x3
    N[3, :3]  = M[:3, 3]        # T кладём в последнюю строку
    N[3, 3]   = 1.0
    return N

def T_mat(v: np.ndarray) -> np.ndarray:
    M = np.eye(4, dtype=np.float64)
    M[:3, 3] = v[:3]
    return M

def R_from_euler(euler_xyz_deg: np.ndarray, order: str = "XYZ") -> np.ndarray:
    ax, ay, az = np.deg2rad(euler_xyz_deg[0]), np.deg2rad(euler_xyz_deg[1]), np.deg2rad(euler_xyz_deg[2])

    def Rx(a):
        ca, sa = np.cos(a), np.sin(a)
        return np.array([[1,0,0],[0,ca,-sa],[0,sa,ca]], dtype=np.float64)
    def Ry(a):
        ca, sa = np.cos(a), np.sin(a)
        return np.array([[ca,0,sa],[0,1,0],[-sa,0,ca]], dtype=np.float64)
    def Rz(a):
        ca, sa = np.cos(a), np.sin(a)
        return np.array([[ca,-sa,0],[sa,ca,0],[0,0,1]], dtype=np.float64)

    mapping = {'X': Rx(ax), 'Y': Ry(ay), 'Z': Rz(az)}
    R = np.eye(3, dtype=np.float64)
    for axis in order:
        R = R @ mapping[axis]
    return R

def shear_matrix(sh: np.ndarray) -> np.ndarray:
    shxy, shxz, shyz = sh[:3]
    return np.array([[1.0, shxy, shxz],
                     [0.0, 1.0,  shyz],
                     [0.0, 0.0,  1.0]], dtype=np.float64)

def mat4_from_TRS_pivots(
    T: np.ndarray, R_euler_deg: np.ndarray, S: np.ndarray,
    shear: np.ndarray,
    rotate_pivot: np.ndarray, rotate_pivot_translate: np.ndarray,
    scale_pivot: np.ndarray, scale_pivot_translate: np.ndarray,
    rot_order: str = "XYZ",
) -> np.ndarray:
    M  = T_mat(T)
    if rotate_pivot_translate is not None:
        M = M @ T_mat(rotate_pivot_translate)
    if rotate_pivot is not None:
        M = M @ T_mat(rotate_pivot)

    R3 = R_from_euler(R_euler_deg, order=rot_order)
    Sh3 = shear_matrix(shear)
    RS3 = R3 @ Sh3
    RS4 = np.eye(4, dtype=np.float64)
    RS4[:3,:3] = RS3
    M = M @ RS4

    if rotate_pivot is not None:
        M = M @ T_mat(-rotate_pivot)

    if scale_pivot_translate is not None:
        M = M @ T_mat(scale_pivot_translate)
    if scale_pivot is not None:
        M = M @ T_mat(scale_pivot)

    S4 = np.diag([S[0], S[1], S[2], 1.0])
    M = M @ S4

    if scale_pivot is not None:
        M = M @ T_mat(-scale_pivot)

    return M

# -----------------------------
# Декомпозиция 4x4 → TRS(+shear)
# -----------------------------
def euler_from_R(R: np.ndarray, order: str = "XYZ") -> np.ndarray:
    def clamp(x, lo=-1.0, hi=1.0):
        return max(lo, min(hi, x))

    if order == "XYZ":
        sy = clamp(-R[2,0])
        cy = np.sqrt(max(0.0, 1.0 - sy*sy))
        if cy > 1e-8:
            x = np.arctan2(R[2,1], R[2,2])
            y = np.arcsin(sy)
            z = np.arctan2(R[1,0], R[0,0])
        else:
            x = np.arctan2(-R[1,2], R[1,1]); y = np.arcsin(sy); z = 0.0
    elif order == "XZY":
        sz = clamp(R[1,0]); cz = np.sqrt(max(0.0, 1.0 - sz*sz))
        if cz > 1e-8:
            x = np.arctan2(-R[1,2], R[1,1]); z = np.arcsin(sz); y = np.arctan2(-R[2,0], R[0,0])
        else:
            x = np.arctan2(R[2,1], R[2,2]); z = np.arcsin(sz); y = 0.0
    elif order == "YXZ":
        sx = clamp(R[2,1]); cx = np.sqrt(max(0.0, 1.0 - sx*sx))
        if cx > 1e-8:
            y = np.arctan2(-R[2,0], R[2,2]); x = np.arcsin(sx); z = np.arctan2(-R[0,1], R[1,1])
        else:
            y = np.arctan2(R[0,2], R[0,0]); x = np.arcsin(sx); z = 0.0
    elif order == "YZX":
        sz = clamp(-R[0,1]); cz = np.sqrt(max(0.0, 1.0 - sz*sz))
        if cz > 1e-8:
            y = np.arctan2(R[0,2], R[0,0]); z = np.arcsin(sz); x = np.arctan2(R[2,1], R[1,1])
        else:
            y = np.arctan2(-R[2,0], R[2,2]); z = np.arcsin(sz); x = 0.0
    elif order == "ZXY":
        sx = clamp(-R[1,2]); cx = np.sqrt(max(0.0, 1.0 - sx*sx))
        if cx > 1e-8:
            z = np.arctan2(R[1,0], R[1,1]); x = np.arcsin(sx); y = np.arctan2(R[0,2], R[2,2])
        else:
            z = np.arctan2(-R[0,1], R[0,0]); x = np.arcsin(sx); y = 0.0
    elif order == "ZYX":
        sy = clamp(R[0,2]); cy = np.sqrt(max(0.0, 1.0 - sy*sy))
        if cy > 1e-8:
            z = np.arctan2(-R[0,1], R[0,0]); y = np.arcsin(sy); x = np.arctan2(-R[1,2], R[2,2])
        else:
            z = np.arctan2(R[1,0], R[1,1]); y = np.arcsin(sy); x = 0.0
    else:
        raise ValueError(f"Unsupported rotation order: {order}")

    return np.rad2deg(np.array([x, y, z], dtype=np.float64))

def decompose_TRS_shear(M: np.ndarray, rot_order: str = "XYZ") -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    T = M[:3, 3].copy()
    A = M[:3, :3].copy()

    U, Sdiag, Vt = np.linalg.svd(A, full_matrices=True)
    R = U @ Vt
    if np.linalg.det(R) < 0:
        U[:, -1] *= -1
        Sdiag[-1] *= -1
        R = U @ Vt

    Sym = Vt.T @ np.diag(Sdiag) @ Vt
    sx, sy, sz = Sym[0,0], Sym[1,1], Sym[2,2]
    scale = np.array([sx, sy, sz], dtype=np.float64)
    shear = np.array([Sym[0,1], Sym[0,2], Sym[1,2]], dtype=np.float64)
    euler_deg = euler_from_R(R, rot_order)
    return T, euler_deg, scale, shear

# -----------------------------
# Кривые (linear)
# -----------------------------
def sample_linear(keys: np.ndarray, values: np.ndarray, t: float) -> float:
    if len(keys) == 0:
        return 0.0
    if t <= keys[0]:
        return float(values[0])
    if t >= keys[-1]:
        return float(values[-1])
    i = np.searchsorted(keys, t)
    t0, t1 = keys[i-1], keys[i]
    v0, v1 = values[i-1], values[i]
    w = (t - t0) / (t1 - t0 + 1e-12)
    return float(v0 * (1.0 - w) + v1 * w)

def union_times(arrs: List[np.ndarray]) -> np.ndarray:
    """
    Объединяет и сортирует все тайм-ключи.
    Возвращает как минимум [0.0], если ключей нет вовсе.
    """
    if not arrs:
        return np.array([0.0], dtype=np.float64)

    pools = []
    for a in arrs:
        if a is None:
            continue
        # поддержка list/np.ndarray; пропускаем пустые
        aa = np.asarray(a, dtype=np.float64)
        if aa.size > 0:
            pools.append(aa)

    if not pools:
        return np.array([0.0], dtype=np.float64)

    return np.unique(np.concatenate(pools, axis=0))

# -----------------------------
# Структура входа для одного узла
# -----------------------------
@dataclass
class NodeInput:
    matrix: Optional[List[float]] = None
    translation: Optional[List[float]] = None
    scaling: Optional[List[float]] = None
    rotation: Optional[List[float]] = None
    rotate_pivot_translate: Optional[List[float]] = None
    rotate_pivot: Optional[List[float]] = None
    scale_pivot_translate: Optional[List[float]] = None
    scale_pivot: Optional[List[float]] = None
    shear: Optional[List[float]] = None

    translation_curve_keys_x: Optional[List[float]] = None
    translation_curve_keys_y: Optional[List[float]] = None
    translation_curve_keys_z: Optional[List[float]] = None
    translation_curve_values_x: Optional[List[float]] = None
    translation_curve_values_y: Optional[List[float]] = None
    translation_curve_values_z: Optional[List[float]] = None

    rotation_curve_keys_x: Optional[List[float]] = None
    rotation_curve_keys_y: Optional[List[float]] = None
    rotation_curve_keys_z: Optional[List[float]] = None
    rotation_curve_values_x: Optional[List[float]] = None
    rotation_curve_values_y: Optional[List[float]] = None
    rotation_curve_values_z: Optional[List[float]] = None

    scaling_curve_keys_x: Optional[List[float]] = None
    scaling_curve_keys_y: Optional[List[float]] = None
    scaling_curve_keys_z: Optional[List[float]] = None
    scaling_curve_values_x: Optional[List[float]] = None
    scaling_curve_values_y: Optional[List[float]] = None
    scaling_curve_values_z: Optional[List[float]] = None

    rotation_order: str = "XYZ"

def _to_arr3(x: Optional[List[float]], default=(0.0,0.0,0.0)) -> np.ndarray:
    return np.array(x if x is not None else default, dtype=np.float64)

def _to_arrM(x: Optional[List[float]]) -> Optional[np.ndarray]:
    if x is None:
        return None
    arr = np.array(x, dtype=np.float64)
    if arr.size == 16:
        N = arr.reshape((4,4))
    elif arr.shape == (4,4):
        N = arr
    else:
        raise ValueError("matrix must be 4x4 or flat 16 elements")
    return mat_std_from_nmf(N)   # ← теперь внутри у нас «стандарт»

def bake_pivots_and_retime(node: NodeInput) -> Dict[str, np.ndarray]:
    T0  = _to_arr3(node.translation, (0,0,0))
    R0  = _to_arr3(node.rotation, (0,0,0))
    S0  = _to_arr3(node.scaling, (1,1,1))
    Rp  = _to_arr3(node.rotate_pivot, (0,0,0))
    RpT = _to_arr3(node.rotate_pivot_translate, (0,0,0))
    Sp  = _to_arr3(node.scale_pivot, (0,0,0))
    SpT = _to_arr3(node.scale_pivot_translate, (0,0,0))
    Sh  = _to_arr3(node.shear, (0,0,0))
    base_matrix = _to_arrM(node.matrix)

    tkeys = [
        np.array(node.translation_curve_keys_x or [], dtype=np.float64),
        np.array(node.translation_curve_keys_y or [], dtype=np.float64),
        np.array(node.translation_curve_keys_z or [], dtype=np.float64),
        np.array(node.rotation_curve_keys_x or [], dtype=np.float64),
        np.array(node.rotation_curve_keys_y or [], dtype=np.float64),
        np.array(node.rotation_curve_keys_z or [], dtype=np.float64),
        np.array(node.scaling_curve_keys_x or [], dtype=np.float64),
        np.array(node.scaling_curve_keys_y or [], dtype=np.float64),
        np.array(node.scaling_curve_keys_z or [], dtype=np.float64),
    ]
    times = union_times(tkeys)

    def sx(keys, vals, t, fallback):
        if keys is None or vals is None or len(keys) == 0:
            return fallback
        return sample_linear(np.array(keys, dtype=np.float64), np.array(vals, dtype=np.float64), t)

    out = {
        "translation_curve_keys_x": times.copy(), "translation_curve_values_x": [],
        "translation_curve_keys_y": times.copy(), "translation_curve_values_y": [],
        "translation_curve_keys_z": times.copy(), "translation_curve_values_z": [],
        "rotation_curve_keys_x": times.copy(),    "rotation_curve_values_x":   [],
        "rotation_curve_keys_y": times.copy(),    "rotation_curve_values_y":   [],
        "rotation_curve_keys_z": times.copy(),    "rotation_curve_values_z":   [],
        "scaling_curve_keys_x": times.copy(),     "scaling_curve_values_x":    [],
        "scaling_curve_keys_y": times.copy(),     "scaling_curve_values_y":    [],
        "scaling_curve_keys_z": times.copy(),     "scaling_curve_values_z":    [],
    }

    no_anim = all(len(a or []) == 0 for a in [
        node.translation_curve_keys_x, node.translation_curve_keys_y, node.translation_curve_keys_z,
        node.rotation_curve_keys_x, node.rotation_curve_keys_y, node.rotation_curve_keys_z,
        node.scaling_curve_keys_x, node.scaling_curve_keys_y, node.scaling_curve_keys_z
    ])

    for t in times:
        Tt = np.array([
            sx(node.translation_curve_keys_x, node.translation_curve_values_x, t, T0[0]),
            sx(node.translation_curve_keys_y, node.translation_curve_values_y, t, T0[1]),
            sx(node.translation_curve_keys_z, node.translation_curve_values_z, t, T0[2]),
        ], dtype=np.float64)

        Rt = np.array([
            sx(node.rotation_curve_keys_x, node.rotation_curve_values_x, t, R0[0]),
            sx(node.rotation_curve_keys_y, node.rotation_curve_values_y, t, R0[1]),
            sx(node.rotation_curve_keys_z, node.rotation_curve_values_z, t, R0[2]),
        ], dtype=np.float64)

        St = np.array([
            sx(node.scaling_curve_keys_x, node.scaling_curve_values_x, t, S0[0]),
            sx(node.scaling_curve_keys_y, node.scaling_curve_values_y, t, S0[1]),
            sx(node.scaling_curve_keys_z, node.scaling_curve_values_z, t, S0[2]),
        ], dtype=np.float64)

        M_local = mat4_from_TRS_pivots(
            T=Tt, R_euler_deg=Rt, S=St, shear=Sh,
            rotate_pivot=Rp, rotate_pivot_translate=RpT,
            scale_pivot=Sp, scale_pivot_translate=SpT,
            rot_order=node.rotation_order,
        )

        if base_matrix is not None and no_anim:
            M_baked = base_matrix @ M_local
        else:
            M_baked = M_local

        T_new, Rdeg_new, S_new, _ = decompose_TRS_shear(M_baked, rot_order=node.rotation_order)

        out["translation_curve_values_x"].append(T_new[0])
        out["translation_curve_values_y"].append(T_new[1])
        out["translation_curve_values_z"].append(T_new[2])

        out["rotation_curve_values_x"].append(Rdeg_new[0])
        out["rotation_curve_values_y"].append(Rdeg_new[1])
        out["rotation_curve_values_z"].append(Rdeg_new[2])

        out["scaling_curve_values_x"].append(S_new[0])
        out["scaling_curve_values_y"].append(S_new[1])
        out["scaling_curve_values_z"].append(S_new[2])

        out["matrix"] = M_baked

    for k in list(out.keys()):
        if k.endswith("_values_x") or k.endswith("_values_y") or k.endswith("_values_z"):
            out[k] = np.array(out[k], dtype=np.float64)

    return out

# -----------------------------
# КЛАСС-ОБЁРТКА ДЛЯ МОДЕЛИ NMF
# -----------------------------
class PivotBaker:
    """
    Использование:
        model = Nmf().unpack(path)
        baked_model = PivotBaker(model, rotation_order="XYZ").bake(inplace=False)
    """
    def __init__(self, model: List[Dict[str, Any]], rotation_order: str = "XYZ"):
        self.model = model
        self.rotation_order = rotation_order

    # 1) помним, какие каналы были ИЗНАЧАЛЬНО
    def _anim_presence(self, node_anim: dict) -> dict:
        prs = {"t": {"x": False, "y": False, "z": False},
               "r": {"x": False, "y": False, "z": False},
               "s": {"x": False, "y": False, "z": False}}
        if not node_anim:
            return prs
        for kind_key, short in (("translation","t"), ("rotation","r"), ("scaling","s")):
            ch = node_anim.get(kind_key, {})
            for axis in ("x","y","z"):
                prs[short][axis] = bool(ch.get(axis, {}).get("keys"))
        return prs

    @staticmethod
    def _get_anim_dict(node_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return node_data.get("anim")

    @staticmethod
    def _axis_keys(anim_chan: Dict[str, Any], axis: str) -> List[float]:
        d = anim_chan.get(axis, {})
        return d.get("keys", []) or []

        

    @staticmethod
    def _axis_vals(anim_chan: Dict[str, Any], axis: str) -> List[float]:
        d = anim_chan.get(axis, {})
        return d.get("values", []) or []

    def _node_to_NodeInput(self, node_data: Dict[str, Any]) -> NodeInput:
        anim = self._get_anim_dict(node_data) or {"translation": {}, "rotation": {}, "scaling": {}}
        tr, ro, sc = anim.get("translation", {}), anim.get("rotation", {}), anim.get("scaling", {})

        return NodeInput(
            matrix=self._flatten_matrix(node_data.get("matrix")),
            translation=node_data.get("translation"),
            scaling=node_data.get("scaling"),
            rotation=node_data.get("rotation"),

            rotate_pivot_translate=node_data.get("rotate_pivot_translate"),
            rotate_pivot=node_data.get("rotate_pivot"),
            scale_pivot_translate=node_data.get("scale_pivot_translate"),
            scale_pivot=node_data.get("scale_pivot"),
            shear=node_data.get("shear"),

            translation_curve_keys_x=self._axis_keys(tr, "x"),
            translation_curve_keys_y=self._axis_keys(tr, "y"),
            translation_curve_keys_z=self._axis_keys(tr, "z"),
            translation_curve_values_x=self._axis_vals(tr, "x"),
            translation_curve_values_y=self._axis_vals(tr, "y"),
            translation_curve_values_z=self._axis_vals(tr, "z"),

            rotation_curve_keys_x=self._axis_keys(ro, "x"),
            rotation_curve_keys_y=self._axis_keys(ro, "y"),
            rotation_curve_keys_z=self._axis_keys(ro, "z"),
            rotation_curve_values_x=self._axis_vals(ro, "x"),
            rotation_curve_values_y=self._axis_vals(ro, "y"),
            rotation_curve_values_z=self._axis_vals(ro, "z"),

            scaling_curve_keys_x=self._axis_keys(sc, "x"),
            scaling_curve_keys_y=self._axis_keys(sc, "y"),
            scaling_curve_keys_z=self._axis_keys(sc, "z"),
            scaling_curve_values_x=self._axis_vals(sc, "x"),
            scaling_curve_values_y=self._axis_vals(sc, "y"),
            scaling_curve_values_z=self._axis_vals(sc, "z"),

            rotation_order=self.rotation_order,
        )

    @staticmethod
    def _flatten_matrix(M: Optional[List[List[float]]]) -> Optional[List[float]]:
        if M is None:
            return None
        # В твоём парсере matrix хранится как 4x4 список списков.
        flat = []
        for row in M:
            flat.extend(row)
        return flat

    @staticmethod
    def _to_nested_axis(keys: np.ndarray, vals: np.ndarray) -> Dict[str, Any]:
        return {"keys": keys.astype(np.float64).tolist(), "values": vals.astype(np.float64).tolist()}

    # 2) при записи назад — создаём кривые ТОЛЬКО по изначально присутствующим осям
    def _write_baked_back(self, node_data: Dict[str, Any], baked: Dict[str, np.ndarray], presence: dict) -> None:
        def axis_dict(kind_short, axis):
            k = f"{ {'t':'translation', 'r':'rotation', 's':'scaling'}[kind_short] }_curve_keys_{axis}"
            v = f"{ {'t':'translation', 'r':'rotation', 's':'scaling'}[kind_short] }_curve_values_{axis}"
            return baked[k], baked[v]

        new_anim = {"translation": {}, "rotation": {}, "scaling": {}}
        for kind_short, kind_full in (("t","translation"), ("r","rotation"), ("s","scaling")):
            for axis in ("x","y","z"):
                if presence[kind_short][axis]:
                    k_arr, v_arr = axis_dict(kind_short, axis)
                    new_anim[kind_full][axis] = {
                        "keys": k_arr.astype(float).tolist(),
                        "values": v_arr.astype(float).tolist(),
                    }
        node_data["anim"] = new_anim

        # 3) обновляем СТАТИКУ на t=0 из baked (rest-поза уже без pivots)
        T0 = np.array([
            baked["translation_curve_values_x"][0],
            baked["translation_curve_values_y"][0],
            baked["translation_curve_values_z"][0],
        ], dtype=np.float64)
        R0 = np.array([
            baked["rotation_curve_values_x"][0],
            baked["rotation_curve_values_y"][0],
            baked["rotation_curve_values_z"][0],
        ], dtype=np.float64)
        S0 = np.array([
            baked["scaling_curve_values_x"][0],
            baked["scaling_curve_values_y"][0],
            baked["scaling_curve_values_z"][0],
        ], dtype=np.float64)

        # важный момент: рест-вращение/масштаб оставляем в СТАТИКЕ, а не в кривых (если их не было)
        if not any(presence["r"].values()):
            node_data["rotation"] = R0.tolist()
        if not any(presence["s"].values()):
            node_data["scaling"] = S0.tolist()
        if not any(presence["t"].values()):
            node_data["translation"] = T0.tolist()

        # 4) пересобираем базовую матрицу из статической TRS (без pivot'ов)
        M_std = np.eye(4, dtype=np.float64)
        # M = T * R * S (наша внутренняя «стандартная» конвенция)
        M_std = T_mat(np.array(node_data["translation"], dtype=np.float64)) @ M_std
        R3   = R_from_euler(np.array(node_data["rotation"], dtype=np.float64), order=self.rotation_order)
        M_std[:3, :3] = R3 @ np.diag(np.array(node_data["scaling"], dtype=np.float64))
        node_data["matrix"] = mat_nmf_from_std(M_std).tolist()

        # 5) обнуляем pivots
        for k in ("rotate_pivot_translate", "rotate_pivot", "scale_pivot_translate", "scale_pivot"):
            if k in node_data:
                node_data[k] = [0.0, 0.0, 0.0]


    def bake(self, inplace: bool = False) -> List[Dict[str, Any]]:
        """
        Проходит по всем узлам модели.
        Для узлов с word in {"ROOT","FRAM"} и наличием полей pivot — запекает pivot'ы в анимацию TRS.
        JOIN и MESH не трогаем (анимацию костей/меша оставляем как есть).

        Возвращает модифицированный список узлов (в месте) либо его копию.
        """
        model = self.model if inplace else deepcopy(self.model)

        for node in model:
            word = node.get("word")
            data = node.get("data", {})

            if word in {"ROOT", "FRAM"} and any(k in data for k in ("rotate_pivot", "scale_pivot")):
                if "anim" in data:
                    presence = self._anim_presence(data.get("anim", {}))
                    node_input = self._node_to_NodeInput(data)
                    baked = bake_pivots_and_retime(node_input)
                    self._write_baked_back(data, baked, presence)
                else:
                    # без анимации: только обнулить pivots
                    for k in ("rotate_pivot_translate", "rotate_pivot", "scale_pivot_translate", "scale_pivot"):
                        if k in data:
                            data[k] = [0.0, 0.0, 0.0]

            # JOIN / MESH — пропускаем без изменений
        return model

# -----------------------------
# Пример
# -----------------------------
# if __name__ == "__main__":
    # Пример интеграции с твоим парсером:
    # from nmf_parser_file import Nmf
    # model = Nmf().unpack("path/to/model.nmf")
    # baked_model = PivotBaker(model, rotation_order="XYZ").bake(inplace=False)
    # pass
