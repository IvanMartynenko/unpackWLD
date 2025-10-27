# This cell creates a self-contained Python module that:
# - Takes an array of node dicts (your schema)
# - Reconstructs per-key local matrices using translation/rotation/scaling + pivots + shear
# - Decomposes them back to TRS with NO pivots and NO shear
# - Writes the new TRS animation channels and zeroes out pivot/shear fields
# - Returns the transformed array
#
# Assumptions:
# - Rotation order is XYZ (rotate X, then Y, then Z), radians
# - Shear is given as (shXY, shXZ, shYZ) (like Maya)
# - Composition used to build the original local matrix:
#   M = T * RpT * Rp * R(XYZ) * Rp^-1 * SpT * Sp * Sh * S * Sp^-1
#   (Rp = rotate_pivot, Sp = scale_pivot, RpT = rotate_pivot_translate, SpT = scale_pivot_translate)
# - All animation channels share identical key times (as the user stated)
# - If a channel has no animation (constant), its keys still exist and contain the same constant
#
# If your engine uses a different composition order, adjust `compose_local_matrix_with_pivots`.
#
# Save this as a reusable script and a small example runner function.
from typing import List, Dict, Any, Tuple
import math
import copy
import json
import numpy as np

# ------------- Linear algebra helpers -------------

def Tmat(t: np.ndarray) -> np.ndarray:
    M = np.eye(4, dtype=np.float64)
    M[:3, 3] = t[:3]
    return M

def Smat(s: np.ndarray) -> np.ndarray:
    M = np.eye(4, dtype=np.float64)
    M[0,0], M[1,1], M[2,2] = s[0], s[1], s[2]
    return M

def Shmat(sh: np.ndarray) -> np.ndarray:
    """Shear with components (shXY, shXZ, shYZ). Convention:
       x' = x + shXY*y + shXZ*z
       y' = y + shYZ*z
       z' = z
       Matrix (column-vector convention):
       [1   shXY shXZ 0
        0   1    shYZ 0
        0   0    1    0
        0   0    0    1]
    """
    shXY, shXZ, shYZ = sh[0], sh[1], sh[2]
    M = np.eye(4, dtype=np.float64)
    M[0,1] = shXY
    M[0,2] = shXZ
    M[1,2] = shYZ
    return M

def Rx(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    M = np.eye(4, dtype=np.float64)
    M[1,1] = c; M[1,2] = -s
    M[2,1] = s; M[2,2] = c
    return M

def Ry(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    M = np.eye(4, dtype=np.float64)
    M[0,0] = c;  M[0,2] = s
    M[2,0] = -s; M[2,2] = c
    return M

def Rz(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    M = np.eye(4, dtype=np.float64)
    M[0,0] = c; M[0,1] = -s
    M[1,0] = s; M[1,1] = c
    return M

def Rxyz(euler: np.ndarray) -> np.ndarray:
    """Rotation order XYZ: rotate around X, then Y, then Z.
       Column-vector convention => M = Rz * Ry * Rx
    """
    rx, ry, rz = euler[0], euler[1], euler[2]
    return (Rz(rz) @ Ry(ry) @ Rx(rx))

def extract_trs_no_shear(M: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Decompose 4x4 affine matrix into T, EulerXYZ (radians), Scale, removing shear.
       Uses Gram–Schmidt on the 3x3 part, then converts to XYZ Euler.
    """
    # Translation
    T = M[:3, 3].copy()

    # 3x3
    A = M[:3, :3].astype(np.float64).copy()

    # Columns (column-vector convention)
    aX = A[:, 0]
    aY = A[:, 1]
    aZ = A[:, 2]

    def length(v):
        return np.linalg.norm(v)

    def normalize(v):
        n = length(v)
        if n < 1e-12:
            return v * 0.0
        return v / n

    sx = length(aX)
    nx = normalize(aX)

    shXY = float(np.dot(nx, aY))
    y_   = aY - shXY * nx
    sy   = length(y_)
    ny   = normalize(y_) if sy > 1e-12 else np.array([0.0,1.0,0.0], dtype=np.float64)

    shXZ = float(np.dot(nx, aZ))
    z_   = aZ - shXZ * nx
    shYZ = float(np.dot(ny, z_))
    z__  = z_ - shYZ * ny
    sz   = length(z__)
    nz   = normalize(z__) if sz > 1e-12 else normalize(np.cross(nx, ny))

    R = np.column_stack([nx, ny, nz])

    # Fix determinant to be positive; fold reflection into scale.x
    if np.linalg.det(R) < 0.0:
        sx *= -1.0
        nx *= -1.0
        R = np.column_stack([nx, ny, nz])

    # Convert R to Euler XYZ (column-vector, M = Rz*Ry*Rx)
    # Derivation for XYZ:
    # From R = Rz*Ry*Rx, we have:
    # r02 = R[0,2] = sY
    # r12 = R[1,2] = -cY*sX
    # r22 = R[2,2] = cY*cX
    # r01 = R[0,1] = -cZ*sY + sZ*cY*sX
    # r00 = R[0,0] =  cZ*cY + sZ*sY*sX
    sy_sin = np.clip(R[0,2], -1.0, 1.0)
    ry = math.asin(sy_sin)
    cy = math.cos(ry)

    if abs(cy) > 1e-6:
        rx = math.atan2(-R[1,2], R[2,2])
        rz = math.atan2(-R[0,1], R[0,0])
    else:
        # Gimbal lock: cy ~ 0 => ry ~ ±pi/2
        # Set rz = 0 and compute rx from other terms
        rz = 0.0
        rx = math.atan2(R[2,1], R[1,1])

    S = np.array([sx, sy, sz], dtype=np.float64)
    euler_xyz = np.array([rx, ry, rz], dtype=np.float64)
    return T, euler_xyz, S

def unwrap_angle(prev: float, cur: float) -> float:
    """Choose cur + k*2π closest to prev to avoid jumps."""
    two_pi = 2.0 * math.pi
    k = round((prev - cur) / two_pi)
    return cur + k * two_pi

def compose_local_matrix_with_pivots(Tv: np.ndarray,
                                     Rxyz_v: np.ndarray,
                                     Sv: np.ndarray,
                                     rp: np.ndarray,
                                     rpt: np.ndarray,
                                     sp: np.ndarray,
                                     spt: np.ndarray,
                                     shear: np.ndarray) -> np.ndarray:
    """Compose local matrix using assumed order:
       M = T * RpT * Rp * R(XYZ) * Rp^-1 * SpT * Sp * Sh * S * Sp^-1
       All vectors are 3D arrays; angles in radians.
    """
    M_T   = Tmat(Tv)
    M_RpT = Tmat(rpt)
    M_Rp  = Tmat(rp)
    M_R   = Rxyz(Rxyz_v)
    M_SpT = Tmat(spt)
    M_Sp  = Tmat(sp)
    M_Sh  = Shmat(shear)
    M_S   = Smat(Sv)
    M_Rp_inv = Tmat(-rp)
    M_Sp_inv = Tmat(-sp)

    # Note: matrix multiply order with column vectors: rightmost applies first
    M = (M_T @ M_RpT @ M_Rp @ M_R @ M_Rp_inv @ M_SpT @ M_Sp @ M_Sh @ M_S @ M_Sp_inv)
    return M

# ------------- Animation sampling helpers -------------

def get_key_times(anim: Dict[str, Any]) -> List[float]:
    # Prefer translation.x if exists, else rotation.x, else scaling.x
    for channel in ["translation", "rotation", "scaling"]:
        if channel in anim and "x" in anim[channel] and "keys" in anim[channel]["x"]:
            return list(anim[channel]["x"]["keys"])
    return []

def sample_channel(anim_axis: Dict[str, Any], default_val: float) -> List[float]:
    if not anim_axis or "values" not in anim_axis:
        return [default_val]
    return list(anim_axis["values"])

def as_vec(vals: List[float]) -> np.ndarray:
    return np.array([vals[0], vals[1], vals[2]], dtype=np.float64)

# ------------- Core bake function -------------

def bake_pivots_in_array(nodes: List[Dict[str, Any]], degrees: bool=False) -> List[Dict[str, Any]]:
    """Bake all nodes so that rotate/scale pivots and shear become zero, folding them into TRS animation.
       - nodes: array of node dicts with fields like in the user's schema.
       - degrees: if True, interpret rotation channels as degrees; output also in degrees.
    """
    result = copy.deepcopy(nodes)

    for node in result:
        if node.get("word") != "FRAM":
            continue
        data = node.get("data", {})
        anim = data.get("anim", {})
        if not anim:
            # No animation: still zero pivots/shear and decompose current matrix once if present.
            data["rotate_pivot"] = [0.0, 0.0, 0.0]
            data["scale_pivot"] = [0.0, 0.0, 0.0]
            data["rotate_pivot_translate"] = [0.0, 0.0, 0.0]
            data["scale_pivot_translate"] = [0.0, 0.0, 0.0]
            data["shear"] = [0.0, 0.0, 0.0]
            continue

        # Base static values (used when channel is constant)
        base_T = as_vec(data.get("translation", [0.0, 0.0, 0.0]))
        base_R = as_vec(data.get("rotation",    [0.0, 0.0, 0.0]))
        base_S = as_vec(data.get("scaling",     [1.0, 1.0, 1.0]))

        if degrees:
            base_R = np.deg2rad(base_R)

        rp  = as_vec(data.get("rotate_pivot",            [0.0, 0.0, 0.0]))
        rpt = as_vec(data.get("rotate_pivot_translate",  [0.0, 0.0, 0.0]))
        sp  = as_vec(data.get("scale_pivot",             [0.0, 0.0, 0.0]))
        spt = as_vec(data.get("scale_pivot_translate",   [0.0, 0.0, 0.0]))
        sh  = as_vec(data.get("shear",                   [0.0, 0.0, 0.0]))

        # Key times
        times = get_key_times(anim)
        if not times:
            # Fallback: single sample at t=0
            times = [0.0]

        # Prepare axis arrays (use existing if present, otherwise constants)
        Txs = sample_channel(anim.get("translation", {}).get("x", {}), float(base_T[0]))
        Tys = sample_channel(anim.get("translation", {}).get("y", {}), float(base_T[1]))
        Tzs = sample_channel(anim.get("translation", {}).get("z", {}), float(base_T[2]))

        Rxs = sample_channel(anim.get("rotation", {}).get("x", {}), float(base_R[0]))
        Rys = sample_channel(anim.get("rotation", {}).get("y", {}), float(base_R[1]))
        Rzs = sample_channel(anim.get("rotation", {}).get("z", {}), float(base_R[2]))

        Sxs = sample_channel(anim.get("scaling", {}).get("x", {}), float(base_S[0]))
        Sys = sample_channel(anim.get("scaling", {}).get("y", {}), float(base_S[1]))
        Szs = sample_channel(anim.get("scaling", {}).get("z", {}), float(base_S[2]))

        nkeys = len(times)
        # Defensive: ensure all lists have same length
        def ensure_len(lst, n, fill_last=True):
            if len(lst) == n:
                return lst
            if not lst:
                return [0.0]*n
            if fill_last:
                return lst + [lst[-1]]*(n - len(lst))
            else:
                return (lst + [0.0]*(n - len(lst)))[:n]

        Txs = ensure_len(Txs, nkeys); Tys = ensure_len(Tys, nkeys); Tzs = ensure_len(Tzs, nkeys)
        Rxs = ensure_len(Rxs, nkeys); Rys = ensure_len(Rys, nkeys); Rzs = ensure_len(Rzs, nkeys)
        Sxs = ensure_len(Sxs, nkeys); Sys = ensure_len(Sys, nkeys); Szs = ensure_len(Szs, nkeys)

        if degrees:
            Rxs = [math.radians(v) for v in Rxs]
            Rys = [math.radians(v) for v in Rys]
            Rzs = [math.radians(v) for v in Rzs]

        # Output arrays
        out_Tx, out_Ty, out_Tz = [], [], []
        out_Rx, out_Ry, out_Rz = [], [], []
        out_Sx, out_Sy, out_Sz = [], [], []

        prev_rx = None; prev_ry = None; prev_rz = None

        for i in range(nkeys):
            Tv = np.array([Txs[i], Tys[i], Tzs[i]], dtype=np.float64)
            Rv = np.array([Rxs[i], Rys[i], Rzs[i]], dtype=np.float64)
            Sv = np.array([Sxs[i], Sys[i], Szs[i]], dtype=np.float64)

            # Build original local matrix including pivots and shear
            M_old = compose_local_matrix_with_pivots(Tv, Rv, Sv, rp, rpt, sp, spt, sh)

            # Decompose to TRS without pivots/shear
            T_new, R_new, S_new = extract_trs_no_shear(M_old)

            # Unwrap angles to avoid jumps
            if prev_rx is not None:
                R_new[0] = unwrap_angle(prev_rx, R_new[0])
                R_new[1] = unwrap_angle(prev_ry, R_new[1])
                R_new[2] = unwrap_angle(prev_rz, R_new[2])

            prev_rx, prev_ry, prev_rz = R_new[0], R_new[1], R_new[2]

            out_Tx.append(float(T_new[0]))
            out_Ty.append(float(T_new[1]))
            out_Tz.append(float(T_new[2]))

            out_Rx.append(float(R_new[0]))
            out_Ry.append(float(R_new[1]))
            out_Rz.append(float(R_new[2]))

            out_Sx.append(float(S_new[0]))
            out_Sy.append(float(S_new[1]))
            out_Sz.append(float(S_new[2]))

        # Convert back to degrees if requested
        if degrees:
            out_Rx = [math.degrees(v) for v in out_Rx]
            out_Ry = [math.degrees(v) for v in out_Ry]
            out_Rz = [math.degrees(v) for v in out_Rz]

        # Write results back
        # Preserve the same key times
        anim_out = anim
        if "translation" not in anim_out: anim_out["translation"] = {"x":{}, "y":{}, "z":{}}
        if "rotation" not in anim_out:    anim_out["rotation"]    = {"x":{}, "y":{}, "z":{}}
        if "scaling" not in anim_out:     anim_out["scaling"]     = {"x":{}, "y":{}, "z":{}}

        anim_out["translation"]["x"]["keys"] = times; anim_out["translation"]["x"]["values"] = out_Tx
        anim_out["translation"]["y"]["keys"] = times; anim_out["translation"]["y"]["values"] = out_Ty
        anim_out["translation"]["z"]["keys"] = times; anim_out["translation"]["z"]["values"] = out_Tz

        anim_out["rotation"]["x"]["keys"] = times; anim_out["rotation"]["x"]["values"] = out_Rx
        anim_out["rotation"]["y"]["keys"] = times; anim_out["rotation"]["y"]["values"] = out_Ry
        anim_out["rotation"]["z"]["keys"] = times; anim_out["rotation"]["z"]["values"] = out_Rz

        anim_out["scaling"]["x"]["keys"] = times; anim_out["scaling"]["x"]["values"] = out_Sx
        anim_out["scaling"]["y"]["keys"] = times; anim_out["scaling"]["y"]["values"] = out_Sy
        anim_out["scaling"]["z"]["keys"] = times; anim_out["scaling"]["z"]["values"] = out_Sz

        data["anim"] = anim_out

        # Zero-out pivots and shear
        data["rotate_pivot"] = [0.0, 0.0, 0.0]
        data["scale_pivot"] = [0.0, 0.0, 0.0]
        data["rotate_pivot_translate"] = [0.0, 0.0, 0.0]
        data["scale_pivot_translate"] = [0.0, 0.0, 0.0]
        data["shear"] = [0.0, 0.0, 0.0]

        # Optional: also update static TRS to match the first key
        data["translation"] = [out_Tx[0], out_Ty[0], out_Tz[0]]
        data["rotation"]    = [out_Rx[0], out_Ry[0], out_Rz[0]]
        data["scaling"]     = [out_Sx[0], out_Sy[0], out_Sz[0]]

        node["data"] = data

    return result