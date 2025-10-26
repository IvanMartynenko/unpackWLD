# io_export_nmf.py
# Blender add-on: Export NMF (binary) — FRAM/JOIN/MESH + ANIM

bl_info = {
    "name": "Export: NMF (Neo Model Format)",
    "author": "You + ChatGPT",
    "version": (0, 2, 0),
    "blender": (3, 0, 0),
    "location": "File > Export > NMF (.nmf)",
    "description": "Export .nmf models (hierarchy, meshes, UVs). Adds ANIM and JOIN (armature bones).",
    "category": "Import-Export",
}

import bpy
import bmesh
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty, BoolProperty
from mathutils import Matrix, Vector
import struct, math, os
from typing import Dict, List, Tuple, Optional, Iterable

# ---------- consts ----------
FPS = 24.0  # должен совпадать с твоим импортёром
RAD2DEG = 180.0 / math.pi

# ---------- binary helpers ----------
def compute_vertex_normals_manual(me: bpy.types.Mesh):
    """Независимо от версии Blender: суммируем нормали треугольников в вершины и нормализуем."""
    vnorms = [Vector((0.0, 0.0, 0.0)) for _ in me.vertices]

    # Если есть loop_triangles — используем их (точнее и быстрее)
    if getattr(me, "loop_triangles", None) and len(me.loop_triangles) > 0:
        for lt in me.loop_triangles:
            vi0 = me.loops[lt.loops[0]].vertex_index
            vi1 = me.loops[lt.loops[1]].vertex_index
            vi2 = me.loops[lt.loops[2]].vertex_index
            p0, p1, p2 = me.vertices[vi0].co, me.vertices[vi1].co, me.vertices[vi2].co
            n = (p1 - p0).cross(p2 - p0)
            vnorms[vi0] += n
            vnorms[vi1] += n
            vnorms[vi2] += n
    else:
        # Фолбэк: полигоны (после триангуляции должны быть треугольники)
        for poly in me.polygons:
            if len(poly.vertices) < 3:
                continue
            vi0, vi1, vi2 = poly.vertices[:3]
            p0, p1, p2 = me.vertices[vi0].co, me.vertices[vi1].co, me.vertices[vi2].co
            n = (p1 - p0).cross(p2 - p0)
            vnorms[vi0] += n
            vnorms[vi1] += n
            vnorms[vi2] += n

    out = []
    for n in vnorms:
        if n.length > 1e-12:
            n.normalize()
            out.append((float(n.x), float(n.y), float(n.z)))
        else:
            out.append((0.0, 0.0, 1.0))  # дефолт на всякий случай
    return out

def write_aligned_string(f, s: str):
    data = s.encode("windows-1252", errors="ignore") + b"\x00"
    f.write(data)
    pad = (4 - (len(data) % 4)) % 4
    if pad:
        f.write(b"\x00" * pad)

def write_token_header(f, token: str, parent_id: int, name: str, size_be: int = 0, skip_le: int = 0):
    f.write(token.encode("ascii"))
    f.write(struct.pack(">I", size_be))
    f.write(struct.pack("<i", skip_le))
    f.write(struct.pack("<i", parent_id))
    write_aligned_string(f, name)

def mat4_row_major(m: Matrix) -> List[float]:
    # Blender хранит column-major, парсер ждёт row-major
    rm = m.transposed()
    return [rm[i][j] for i in range(4) for j in range(4)]

def mat3_to_mat4_rowmajor(m3: Matrix) -> List[float]:
    # из 3x3 (ориентация) делаем 4x4 (с единичной четвёртой строкой/столбцом)
    m4 = Matrix.Identity(4)
    m4[0][0], m4[0][1], m4[0][2] = m3[0][0], m3[0][1], m3[0][2]
    m4[1][0], m4[1][1], m4[1][2] = m3[1][0], m3[1][1], m3[1][2]
    m4[2][0], m4[2][1], m4[2][2] = m3[2][0], m3[2][1], m3[2][2]
    return mat4_row_major(m4)

# ---------- mesh sampling ----------

def triangulate_object_get_eval_mesh(obj: bpy.types.Object) -> bpy.types.Mesh:
    deps = bpy.context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(deps)
    me = bpy.data.meshes.new_from_object(
        obj_eval, preserve_all_data_layers=True, depsgraph=deps
    )

    # Триангуляция во временный bmesh (если нужно)
    bm = bmesh.new()
    bm.from_mesh(me)
    if any(len(p.verts) != 3 for p in bm.faces):
        bmesh.ops.triangulate(
            bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY'
        )
        bm.to_mesh(me)
    bm.free()

    # Нормали посчитаем вручную позже; здесь лишь убедимся, что есть триугольники
    if hasattr(me, "calc_loop_triangles"):
        me.calc_loop_triangles()
    return me


def collect_uv_per_vertex(me: bpy.types.Mesh) -> List[Tuple[float,float]]:
    uv_layer = me.uv_layers.active
    vcount = len(me.vertices)
    if not uv_layer:
        return [(0.0, 0.0)] * vcount
    acc = [(0.0, 0.0, 0) for _ in range(vcount)]
    uvdata = uv_layer.data
    for poly in me.polygons:
        for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
            v_idx = me.loops[li].vertex_index
            u, v = uvdata[li].uv[:]
            su, sv, c = acc[v_idx]
            acc[v_idx] = (su + float(u), sv + float(v), c + 1)
    out = []
    for su, sv, c in acc:
        out.append((0.0, 0.0) if c == 0 else (su / c, sv / c))
    return out

def mesh_indices_from_loops(me: bpy.types.Mesh) -> List[int]:
    idx = []
    for lt in me.loop_triangles:
        idx.extend([me.loops[i].vertex_index for i in lt.loops])
    return idx

# ---------- animation collection ----------

def _axis_counts(track_dict: Dict[str, List[float]]) -> Tuple[int,int,int]:
    return (
        len(track_dict.get("x", [])) // 2,  # //2 потому что мы возвращаем "t,v" попарно? Нет — ниже возвращаем раздельно
        len(track_dict.get("y", [])) // 2,
        len(track_dict.get("z", [])) // 2
    )

def fcurves_for_path_id(action: Optional[bpy.types.Action], datapath: str) -> Dict[int, bpy.types.FCurve]:
    """Вернёт fcurves по индексам осей для datapath."""
    out: Dict[int, bpy.types.FCurve] = {}
    if not action:
        return out
    for fc in action.fcurves:
        if fc.data_path == datapath and fc.array_index in (0,1,2):
            out[fc.array_index] = fc
    return out

def extract_axis_keys(fc: Optional[bpy.types.FCurve]) -> Tuple[List[float], List[float]]:
    """Достаём отсортированные по времени ключи: время(сек), значение. Без интерполяции (как в файле)."""
    if not fc or not fc.keyframe_points:
        return [], []
    pts = sorted(fc.keyframe_points, key=lambda k: k.co[0])
    t = [float(p.co[0]) / FPS for p in pts]  # секунды
    v = [float(p.co[1]) for p in pts]
    return t, v

def collect_anim_for_object(obj: bpy.types.ID) -> Dict[str, Dict[str, Tuple[List[float], List[float]]]]:
    """Собирает анимацию для Object: location/rotation_euler/scale (XYZ). Возвращает по треку и оси пары (t[], v[])."""
    action = getattr(obj.animation_data, "action", None) if getattr(obj, "animation_data", None) else None
    result: Dict[str, Dict[str, Tuple[List[float], List[float]]]] = {"translation": {}, "rotation": {}, "scaling": {}}

    # location
    for i, ax in enumerate("xyz"):
        t, v = extract_axis_keys(fcurves_for_path_id(action, "location").get(i))
        if t:
            result["translation"][ax] = (t, v)
    # rotation_euler (в радианах — это и нужно)
    # Если rotation_mode != 'XYZ', лучше предварительно bake'нуть, но тут берём F-кривые как есть.
    for i, ax in enumerate("xyz"):
        t, v = extract_axis_keys(fcurves_for_path_id(action, "rotation_euler").get(i))
        if t:
            result["rotation"][ax] = (t, v)
    # scale
    for i, ax in enumerate("xyz"):
        t, v = extract_axis_keys(fcurves_for_path_id(action, "scale").get(i))
        if t:
            result["scaling"][ax] = (t, v)
    return result

def collect_anim_for_bone(arm_obj: bpy.types.Object, bone_name: str) -> Dict[str, Dict[str, Tuple[List[float], List[float]]]]:
    """Собирает анимацию для pose.bone. Ищем F-кривые на Armature action по путям pose.bones["Name"].*"""
    ad = getattr(arm_obj, "animation_data", None)
    action = ad.action if ad else None
    result: Dict[str, Dict[str, Tuple[List[float], List[float]]]] = {"translation": {}, "rotation": {}, "scaling": {}}
    if not action:
        return result
    # helper
    def curves(dp): return fcurves_for_path_id(action, dp)
    base = f'pose.bones["{bone_name}"]'
    # location
    for i, ax in enumerate("xyz"):
        t, v = extract_axis_keys(curves(base + ".location").get(i))
        if t:
            result["translation"][ax] = (t, v)
    # rotation_euler (в радианах)
    for i, ax in enumerate("xyz"):
        t, v = extract_axis_keys(curves(base + ".rotation_euler").get(i))
        if t:
            result["rotation"][ax] = (t, v)
    # scale
    for i, ax in enumerate("xyz"):
        t, v = extract_axis_keys(curves(base + ".scale").get(i))
        if t:
            result["scaling"][ax] = (t, v)
    return result

def has_any_keys(anim: Dict[str, Dict[str, Tuple[List[float], List[float]]]]) -> bool:
    for trk in ("translation","rotation","scaling"):
        for ax in ("x","y","z"):
            tv = anim.get(trk, {}).get(ax)
            if tv and tv[0]:
                return True
    return False

def write_anim(f, anim: Dict[str, Dict[str, Tuple[List[float], List[float]]]]):
    """Блок ANIM под твой парсер:
       int32 unknown=0
       sizes: для translation, rotation, scaling по 3 int (x,y,z)
       затем для каждого трека по оси: n*float (keys), n*float (values)
       rotation значения — в радианах (импортёр сам умножает на RAD2DEG)."""
    f.write(b"ANIM")
    f.write(struct.pack("<i", 0))  # unknown

    # sizes
    for track in ("translation","rotation","scaling"):
        sizes = []
        for ax in ("x","y","z"):
            tv = anim.get(track, {}).get(ax, ([], []))
            sizes.append(len(tv[0]))
        f.write(struct.pack("<3i", *sizes))

    # data per track/axis
    for track in ("translation","rotation","scaling"):
        for ax in ("x","y","z"):
            t, v = anim.get(track, {}).get(ax, ([], []))
            if t:
                f.write(struct.pack("<%df" % len(t), *t))
                f.write(struct.pack("<%df" % len(v), *v))
            # если нулевые — ничего не пишем (парсер читает ровно по sizes)

# ---------- FRAM/JOIN writers ----------

def write_root(f, name="Scene"):
    write_token_header(f, "ROOT", 0, name)
    m = Matrix.Identity(4)
    f.write(struct.pack("<16f", *mat4_row_major(m)))
    zero3 = (0.0, 0.0, 0.0)
    f.write(struct.pack("<3f", 0.0, 0.0, 0.0))  # T
    f.write(struct.pack("<3f", 1.0, 1.0, 1.0))  # S
    f.write(struct.pack("<3f", 0.0, 0.0, 0.0))  # R(rad)
    f.write(struct.pack("<3f", *zero3))  # RpT
    f.write(struct.pack("<3f", *zero3))  # Rp
    f.write(struct.pack("<3f", *zero3))  # SpT
    f.write(struct.pack("<3f", *zero3))  # Sp
    f.write(struct.pack("<3f", *zero3))  # Shear
    # без ANIM у ROOT

def write_fram(f, obj: bpy.types.Object, parent_id: int):
    write_token_header(f, "FRAM", parent_id, obj.name)
    m = obj.matrix_local
    f.write(struct.pack("<16f", *mat4_row_major(m)))
    t = obj.location
    s = obj.scale
    r = obj.rotation_euler  # radians
    f.write(struct.pack("<3f", float(t.x), float(t.y), float(t.z)))
    f.write(struct.pack("<3f", float(s.x), float(s.y), float(s.z)))
    f.write(struct.pack("<3f", float(r.x), float(r.y), float(r.z)))
    zero3 = (0.0, 0.0, 0.0)
    f.write(struct.pack("<3f", *zero3))  # RpT
    f.write(struct.pack("<3f", *zero3))  # Rp
    f.write(struct.pack("<3f", *zero3))  # SpT
    f.write(struct.pack("<3f", *zero3))  # Sp
    f.write(struct.pack("<3f", *zero3))  # Shear

def write_fram_with_anim(f, obj: bpy.types.Object, parent_id: int):
    write_fram(f, obj, parent_id)
    anim = collect_anim_for_object(obj)
    if has_any_keys(anim):
        write_anim(f, anim)

def bone_local_rest_matrix(b: bpy.types.Bone) -> Matrix:
    """Локальная матрица кости относительно родителя в REST (armature space -> parent local)."""
    if b.parent:
        return b.parent.matrix_local.inverted() @ b.matrix_local
    return b.matrix_local.copy()

def write_join(f, arm_obj: bpy.types.Object, bone: bpy.types.Bone, parent_id: int):
    """JOIN: matrix(4x4), translation/scaling/rotation(rad), rotation_matrix(4x4 from rest orient),
       min/max rot limits (рад), опц. ANIM."""
    name = bone.name
    write_token_header(f, "JOIN", parent_id, name)

    # Локальная rest-матрица кости
    m_local = bone_local_rest_matrix(bone)

    # 1) matrix (4x4) — пишем тот же локальный rest
    f.write(struct.pack("<16f", *mat4_row_major(m_local)))

    # 2) translation / scaling / rotation (рад) из декомпозиции локальной матрицы
    loc = m_local.to_translation()
    rot = m_local.to_euler('XYZ')   # rest-поворот
    sca = m_local.to_scale()
    f.write(struct.pack("<3f", float(loc.x), float(loc.y), float(loc.z)))
    f.write(struct.pack("<3f", float(sca.x), float(sca.y), float(sca.z)))
    # Базовую rotation можно оставить нулём, а orient вынести в rotation_matrix (как joint orient),
    # но парсер допускает и такой вариант: rotation = rest-euler, orient = тоже rest (не конфликтует)
    f.write(struct.pack("<3f", float(rot.x), float(rot.y), float(rot.z)))

    # 3) rotation_matrix (4x4) — ориент кости (берём чистую 3x3 из rest, без масштабов/сдвига)
    rot3 = m_local.to_3x3()
    f.write(struct.pack("<16f", *mat3_to_mat4_rowmajor(rot3)))

    # 4) limits — можно поставить ±180° (в радианах)
    lim = math.pi
    f.write(struct.pack("<3f", -lim, -lim, -lim))  # min
    f.write(struct.pack("<3f",  lim,  lim,  lim))  # max

    # 5) optional ANIM — с F-кривых pose.bones["name"].*
    anim = collect_anim_for_bone(arm_obj, name)
    if has_any_keys(anim):
        write_anim(f, anim)

def write_mesh(f, obj: bpy.types.Object, parent_id: int):
    name = obj.name
    write_token_header(f, "MESH", parent_id, name)
    me = triangulate_object_get_eval_mesh(obj)

    f.write(struct.pack("<i", 0))  # tnum
    vnum = len(me.vertices)
    f.write(struct.pack("<i", vnum))

    # === здесь вместо me.calc_normals() берём наши нормали ===
    vnorms = compute_vertex_normals_manual(me)

    vbuf = []
    for i, v in enumerate(me.vertices):
        px, py, pz = v.co[:]
        nx, ny, nz = vnorms[i]
        vbuf.extend([float(px), float(py), float(pz),
                     float(nx), float(ny), float(nz),
                     0.0, 0.0, 0.0, 0.0])
    f.write(struct.pack("<%df" % (vnum * 10), *vbuf))

    # UV, индексы и хвост — без изменений
    uvpt = collect_uv_per_vertex(me)
    flat_uv = []
    for (u, v) in uvpt:
        flat_uv.extend([float(u), float(v)])
    f.write(struct.pack("<%df" % (vnum * 2), *flat_uv))

    # индексы
    idx = mesh_indices_from_loops(me)
    inum = len(idx)
    f.write(struct.pack("<i", inum))
    if vnum > 32767:
        raise RuntimeError(f"Mesh '{name}' has too many vertices for int16 indices ({vnum})")
    f.write(struct.pack("<%dh" % inum, *[int(i) for i in idx]))
    if inum % 2 == 1:
        f.write(struct.pack("<h", 0))

    f.write(struct.pack("<5i", 0, 0, 0, 0, 0))
    f.write(struct.pack("<i", 0))
    f.write(struct.pack("<i", 0))
    f.write(struct.pack("<i", 0))

    bpy.data.meshes.remove(me, do_unlink=True)

# ---------- export selection, ordering, parenting ----------

def gather_export_objects(context) -> List[bpy.types.Object]:
    sel = list(context.selected_objects)
    if sel:
        return sel
    return [o for o in context.view_layer.objects if o.visible_get()]

def topo_order(objs: Iterable[bpy.types.Object]) -> List[bpy.types.Object]:
    export_set = set(objs)
    ordered: List[bpy.types.Object] = []
    placed = set()
    while len(placed) < len(export_set):
        progress = False
        for o in list(export_set):
            if o in placed:
                continue
            p = o.parent
            if (p is None) or (p in placed) or (p not in export_set):
                ordered.append(o)
                placed.add(o)
                progress = True
        if not progress:
            for o in list(export_set):
                if o not in placed:
                    ordered.append(o); placed.add(o)
    return ordered

def write_end(f):
    f.write(b"END ")
    f.write(struct.pack(">I", 0))
    f.write(struct.pack("<i", 0))

# ---------- operator ----------

class EXPORT_OT_nmf(Operator, ExportHelper):
    bl_idname = "export_scene.nmf"
    bl_label = "Export NMF"
    bl_options = {'PRESET'}

    filename_ext: StringProperty(default=".nmf")
    filter_glob: StringProperty(default="*.nmf", options={'HIDDEN'})

    export_meshes:   BoolProperty(name="Export Meshes", default=True)
    export_frams:    BoolProperty(name="Export Non-mesh as FRAM", default=True)
    export_armature: BoolProperty(name="Export Armature as JOIN", default=True)
    bake_object_anim: BoolProperty(
        name="Export Object Animation",
        description="Write ANIM blocks for Objects that have F-curves",
        default=True
    )
    bake_bone_anim: BoolProperty(
        name="Export Bone Animation",
        description="Write ANIM blocks for Bones (from Armature action pose.bones[\"...\"])",
        default=True
    )

    def execute(self, context):
        path = self.filepath
        try:
            objs = gather_export_objects(context)
            if not objs:
                self.report({'ERROR'}, "Nothing to export")
                return {'CANCELLED'}

            ordered = topo_order(objs)
            with open(path, "wb") as f:
                # header + ROOT
                f.write(b"NMF ")
                f.write(struct.pack("<i", 0))
                write_root(f, name="Scene")

                # индексная карта: объект/кость -> индекс
                node_index: Dict[str, int] = {}  # ключ — уникальное имя узла (obj.name или "arm:bone")
                cur_index = 2  # 1 — ROOT

                # --- 1) FRAM для не-мешей (включая сами Armature объекты) ---
                if self.export_frams:
                    for o in ordered:
                        if o.type not in {'MESH'}:  # Armature, Empty, Camera, Light и т.п.
                            parent_id = 1
                            if o.parent and (o.parent.name in node_index):
                                parent_id = node_index[o.parent.name]
                            write_fram_with_anim(f, o, parent_id) if self.bake_object_anim else write_fram(f, o, parent_id)
                            node_index[o.name] = cur_index
                            cur_index += 1

                # --- 2) JOIN для костей Armature ---
                if self.export_armature:
                    for arm in [o for o in ordered if o.type == 'ARMATURE']:
                        arm_parent_id = node_index.get(arm.name, 1)
                        # Пишем кости в порядке, где родитель уже существует
                        bones = list(arm.data.bones)
                        # простая топосорт по родителю
                        placed = set()
                        while len(placed) < len(bones):
                            progress = False
                            for b in bones:
                                if b.name in placed:
                                    continue
                                if (b.parent is None) or (b.parent.name in placed):
                                    # определить parent_id: родительская кость или арм-объект
                                    if b.parent is None:
                                        parent_id = arm_parent_id
                                    else:
                                        parent_id = node_index.get(f"{arm.name}:{b.parent.name}", arm_parent_id)
                                    write_join(f, arm, b, parent_id)
                                    node_index[f"{arm.name}:{b.name}"] = cur_index
                                    cur_index += 1
                                    placed.add(b.name)
                                    progress = True
                            if not progress:
                                # На случай странных циклов
                                for b in bones:
                                    if b.name not in placed:
                                        write_join(f, arm, b, arm_parent_id)
                                        node_index[f"{arm.name}:{b.name}"] = cur_index
                                        cur_index += 1
                                        placed.add(b.name)

                # --- 3) MESH ---
                if self.export_meshes:
                    for o in ordered:
                        if o.type == 'MESH':
                            parent_id = 1
                            # если у меша есть родитель — привяжем к нему (FRAM/Armature FRAM/к JOIN не привязываем здесь)
                            if o.parent and (o.parent.name in node_index):
                                parent_id = node_index[o.parent.name]
                            write_mesh(f, o, parent_id)
                            node_index[o.name] = cur_index
                            cur_index += 1

                write_end(f)

        except Exception as e:
            self.report({'ERROR'}, f"NMF export failed: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, "NMF export finished")
        return {'FINISHED'}

# ---------- menu & register ----------

def menu_func_export(self, context):
    self.layout.operator(EXPORT_OT_nmf.bl_idname, text="NMF (.nmf)")

classes = (EXPORT_OT_nmf,)

def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)

def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

if __name__ == "__main__":
    register()
