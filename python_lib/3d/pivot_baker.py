import numpy as np
import math

def mat4_identity():
    return np.eye(4, dtype=float)

def T(v):
    m = mat4_identity()
    m[:3, 3] = v
    return m

def Rx(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([
        [1, 0, 0, 0],
        [0, c, -s, 0],
        [0, s, c, 0],
        [0, 0, 0, 1]
    ], dtype=float)

def Ry(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([
        [c, 0, s, 0],
        [0, 1, 0, 0],
        [-s, 0, c, 0],
        [0, 0, 0, 1]
    ], dtype=float)

def Rz(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([
        [c, -s, 0, 0],
        [s, c, 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1]
    ], dtype=float)

def Rxyz(v):
    rx, ry, rz = v
    return Rx(rx) @ Ry(ry) @ Rz(rz)

def S(v):
    sx, sy, sz = v
    return np.diag([sx, sy, sz, 1.0])

def build_pivoted(tr, rot, sca, rp, rpt, sp, spt):
    M = np.eye(4)
    M = M @ T(tr)
    M = M @ T(rpt)
    M = M @ T(rp)
    M = M @ Rxyz(rot)
    M = M @ T(-np.array(rp))
    M = M @ T(spt)
    M = M @ T(sp)
    M = M @ S(sca)
    M = M @ T(-np.array(sp))
    return M

def decompose_trs_XYZ(M):
    t = M[:3, 3].copy()
    A = M.copy()
    A[:3, 3] = 0.0
    c0, c1, c2 = A[:3, 0], A[:3, 1], A[:3, 2]
    sx, sy, sz = np.linalg.norm(c0), np.linalg.norm(c1), np.linalg.norm(c2)
    r0, r1, r2 = c0 / sx, c1 / sy, c2 / sz
    R = np.column_stack((r0, r1, r2))
    if np.linalg.det(R) < 0:
        sz = -sz
        R[:, 2] *= -1

    ry = math.asin(max(-1.0, min(1.0, R[0, 2])))
    cy = math.cos(ry)
    if abs(cy) > 1e-6:
        rx = math.atan2(-R[1, 2], R[2, 2])
        rz = math.atan2(-R[0, 1], R[0, 0])
    else:
        rx = math.atan2(R[2, 1], R[1, 1])
        rz = 0.0
    return t.tolist(), [rx, ry, rz], [sx, sy, sz]

def bake_pivots_in_array(objects):
    for obj in objects:
        if obj.get("word") != "FRAM":
            continue
        data = obj.get("data", {})
        anim = data.get("anim")
        if not anim:
            continue

        rp = np.array(data.get("rotate_pivot", [0,0,0]), dtype=float)
        rpt = np.array(data.get("rotate_pivot_translate", [0,0,0]), dtype=float)
        sp = np.array(data.get("scale_pivot", [0,0,0]), dtype=float)
        spt = np.array(data.get("scale_pivot_translate", [0,0,0]), dtype=float)

        # Собираем все ключи времени
        keys = anim["rotation"]["x"]["keys"]

        new_trans = {"x": {"keys": [], "values": []},
                     "y": {"keys": [], "values": []},
                     "z": {"keys": [], "values": []}}
        new_rot = {"x": {"keys": [], "values": []},
                   "y": {"keys": [], "values": []},
                   "z": {"keys": [], "values": []}}
        new_sca = {"x": {"keys": [], "values": []},
                   "y": {"keys": [], "values": []},
                   "z": {"keys": [], "values": []}}

        for i, t_key in enumerate(keys):
            tr = np.array([
                anim["translation"]["x"]["values"][i],
                anim["translation"]["y"]["values"][i],
                anim["translation"]["z"]["values"][i],
            ], dtype=float)

            rot = np.array([
                anim["rotation"]["x"]["values"][i],
                anim["rotation"]["y"]["values"][i],
                anim["rotation"]["z"]["values"][i],
            ], dtype=float)

            sca = np.array([
                anim["scaling"]["x"]["values"][i],
                anim["scaling"]["y"]["values"][i],
                anim["scaling"]["z"]["values"][i],
            ], dtype=float)

            M = build_pivoted(tr, rot, sca, rp, rpt, sp, spt)
            tr_new, rot_new, sca_new = decompose_trs_XYZ(M)

            new_trans["x"]["keys"].append(t_key)
            new_trans["x"]["values"].append(tr_new[0])
            new_trans["y"]["keys"].append(t_key)
            new_trans["y"]["values"].append(tr_new[1])
            new_trans["z"]["keys"].append(t_key)
            new_trans["z"]["values"].append(tr_new[2])

            new_rot["x"]["keys"].append(t_key)
            new_rot["x"]["values"].append(rot_new[0])
            new_rot["y"]["keys"].append(t_key)
            new_rot["y"]["values"].append(rot_new[1])
            new_rot["z"]["keys"].append(t_key)
            new_rot["z"]["values"].append(rot_new[2])

            new_sca["x"]["keys"].append(t_key)
            new_sca["x"]["values"].append(sca_new[0])
            new_sca["y"]["keys"].append(t_key)
            new_sca["y"]["values"].append(sca_new[1])
            new_sca["z"]["keys"].append(t_key)
            new_sca["z"]["values"].append(sca_new[2])

        data["anim"]["translation"] = new_trans
        data["anim"]["rotation"] = new_rot
        data["anim"]["scaling"] = new_sca

        # Обнуляем пивоты
        data["rotate_pivot"] = [0,0,0]
        data["rotate_pivot_translate"] = [0,0,0]
        data["scale_pivot"] = [0,0,0]
        data["scale_pivot_translate"] = [0,0,0]

        data["translation"] = [0,0,0]
        data["rotation"] = [0,0,0]
        data["scaling"] = [1,1,1]
        data["matrix"] = np.eye(4).tolist()  # единичная
        print(data["matrix"])

        obj["data"] = data
    return objects
