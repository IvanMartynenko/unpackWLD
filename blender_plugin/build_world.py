import bpy
import json
import os
from mathutils import Matrix, Euler

# --- НАСТРОЙКИ ПУТЕЙ ---
UNPACK_DIR = r"REPLACE_TO_PATH_TO_MODELS"

def debug_log(message):
    print(f"[NMF_BUILDER] {message}")


# --- ГЛОБАЛЬНЫЕ КЭШИ ---
MATERIAL_CACHE = {}
IMAGE_CACHE = {}

# ------------------------------------------------------------------------
# Импорт Материалов
# ------------------------------------------------------------------------


def _create_material_from_nmf(mat_info):
    name = mat_info.get("mat_name", "NMF_Material")

    # Берем из кэша, если уже создавали для другой модели
    if name in MATERIAL_CACHE:
        return MATERIAL_CACHE[name]

    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)

    if hasattr(mat, "use_nodes"):
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        bsdf = None
        for n in nodes:
            if n.type == "BSDF_PRINCIPLED":
                bsdf = n
                break

        if bsdf is None:
            nodes.clear()
            out = nodes.new("ShaderNodeOutputMaterial")
            out.location = (400, 0)
            bsdf = nodes.new("ShaderNodeBsdfPrincipled")
            bsdf.location = (0, 0)
            links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    else:
        MATERIAL_CACHE[name] = mat
        return mat

    r = mat_info["r"]
    g = float(mat_info.get("g", 1.0))
    b = float(mat_info.get("b", 1.0))
    a = float(mat_info.get("a", 1.0))

    bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
    bsdf.inputs["Alpha"].default_value = a

    mode = mat_info.get("blend_mode", 0)
    if mode in (0, 1, 2, 3):
        mat.blend_method = "OPAQUE" if mode == 0 else "BLEND"
        mat.shadow_method = (
            "OPAQUE" if mode == 0 else ("NONE" if mode == 2 else "HASHED")
        )

    tex_path = mat_info.get("tex_path")
    has_tex = bool(mat_info.get("has_tex") and tex_path)

    if has_tex:
        uv_node = nodes.new("ShaderNodeUVMap")
        uv_node.location = (-800, 0)
        uv_node.uv_map = "UVMap"

        mapping_node = nodes.new("ShaderNodeMapping")
        mapping_node.location = (-600, 0)

        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.location = (-400, 0)

        # Текстуры грузим 1 раз
        try:
            if tex_path in IMAGE_CACHE:
                tex_node.image = IMAGE_CACHE[tex_path]
            else:
                image = bpy.data.images.load(tex_path)
                tex_node.image = image
                IMAGE_CACHE[tex_path] = image
        except Exception:
            pass

        repeatU = float(mat_info.get("repeatU", 1.0))
        repeatV = float(mat_info.get("repeatV", 1.0))
        mirrorU = int(mat_info.get("mirrorU", 0))
        mirrorV = int(mat_info.get("mirrorV", 0))
        rotateUV = float(mat_info.get("rotateUV", 0.0))

        scale_x = repeatU * (-1.0 if mirrorU else 1.0)
        scale_y = repeatV * (-1.0 if mirrorV else 1.0)

        mapping_node.inputs["Scale"].default_value[0] = scale_x
        mapping_node.inputs["Scale"].default_value[1] = scale_y
        mapping_node.inputs["Rotation"].default_value[2] = rotateUV

        def safe_link(src, dst):
            if src is None or dst is None:
                return
            for link in dst.links:
                if link.from_socket == src:
                    return
            links.new(src, dst)

        safe_link(uv_node.outputs.get("UV"), mapping_node.inputs.get("Vector"))
        safe_link(mapping_node.outputs.get("Vector"), tex_node.inputs.get("Vector"))
        safe_link(tex_node.outputs.get("Color"), bsdf.inputs.get("Base Color"))
        safe_link(tex_node.outputs.get("Alpha"), bsdf.inputs.get("Alpha"))

    MATERIAL_CACHE[name] = mat
    return mat


def _apply_anim_to_object(obj, anim_tracks):
    if not anim_tracks:
        return
    obj.rotation_mode = "XYZ"
    fps = bpy.context.scene.render.fps
    spec = {
        "translation": ("location", (0, 1, 2), 1.0),
        "rotation": ("rotation_euler", (0, 1, 2), 1.0),
        "scaling": ("scale", (0, 1, 2), 1.0),
    }
    for track, (prop, idxs, scale) in spec.items():
        track_data = anim_tracks.get(track)
        if not track_data:
            continue
        values = track_data.get("values", {})
        keys = track_data.get("keys", {})
        for ax_name, ax_i in zip(("x", "y", "z"), idxs):
            vals = values.get(ax_name)
            frames = keys.get(ax_name)
            if not vals or not frames:
                continue
            for t, v in zip(frames, vals):
                frame = int(round(t * fps))
                arr = getattr(obj, prop)
                arr[ax_i] = float(v) * scale
                obj.keyframe_insert(data_path=prop, index=ax_i, frame=frame)


# ------------------------------------------------------------------------
# Импорт 3D-Модели в скрытую коллекцию
# ------------------------------------------------------------------------


def import_nmf_as_collection(nmf_rel_path, model_id, source_models_coll):
    """
    Парсит NMF один раз и собирает его в эталонную (мастер) коллекцию.
    """
    abs_path = os.path.join(UNPACK_DIR, nmf_rel_path)
    if not os.path.exists(abs_path):
        return None

    coll_name = f"NMF_Asset_{model_id}"

    # Если коллекция уже была создана ранее — просто возвращаем её!
    if coll_name in bpy.data.collections:
        return bpy.data.collections[coll_name]

    new_coll = bpy.data.collections.new(coll_name)
    source_models_coll.children.link(new_coll)

    parser = Nmf()
    try:
        nodes_raw = parser.unpack(abs_path)
        nodes = convert_and_filter_nodes(nodes_raw, abs_path)
    except Exception as e:
        debug_log(f"Ошибка парсинга {nmf_rel_path}: {e}")
        return None

    id_to_obj = {}

    # ЭТАП 1: Создаем объекты и применяем их абсолютные (глобальные) координаты NMF
    for node in nodes:
        ntype = node["type"]
        nid = node["id"]
        name = node["name"]

        if ntype in ("transform", "empty"):
            obj = bpy.data.objects.new(name, None)
            obj.empty_display_size = 0.5
            if node.get("matrix"):
                obj.matrix_world = Matrix(node.get("matrix"))
            if node.get("animation"):
                _apply_anim_to_object(obj, node.get("animation"))
            new_coll.objects.link(obj)
            id_to_obj[nid] = obj

        elif ntype == "mesh":
            mesh = bpy.data.meshes.new(name)
            verts = [tuple(v) for v in node["vrts"]]
            faces = [tuple(tri) for tri in node["ibuf"]]
            mesh.from_pydata(verts, [], faces)

            uvpt = node.get("uvpt") or []
            uv_index = node.get("uv_index_of_vertex") or list(range(len(verts)))
            if uvpt:
                uv_layer = mesh.uv_layers.new(name="UVMap")
                for poly in mesh.polygons:
                    for li in poly.loop_indices:
                        vidx = mesh.loops[li].vertex_index
                        uvidx = uv_index[vidx]
                        if 0 <= uvidx < len(uvpt):
                            uv_layer.data[li].uv = uvpt[uvidx]

            mats = node.get("materials") or []
            existing_names = []
            for mat_info in mats:
                mat = _create_material_from_nmf(mat_info)
                if mat and mat.name not in existing_names:
                    mesh.materials.append(mat)
                    existing_names.append(mat.name)

            obj = bpy.data.objects.new(name, mesh)
            if node.get("matrix"):
                obj.matrix_world = Matrix(node.get("matrix"))
            new_coll.objects.link(obj)
            id_to_obj[nid] = obj

    # ЭТАП 2: Иерархия. Blender сам высчитает правильные смещения (matrix_parent_inverse)
    for node in nodes:
        nid = node["id"]
        pid = node["parent_id"]
        if nid in id_to_obj and pid in id_to_obj:
            id_to_obj[nid].parent = id_to_obj[pid]

    return new_coll


# ------------------------------------------------------------------------
# Сборка мира (Instance Builder)
# ------------------------------------------------------------------------


def load_json(filename):
    path = os.path.join(UNPACK_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_world():
    debug_log("Начало сборки карты через Collection Instances...")

    world_tree = load_json("world_tree.json")
    models_info = load_json("models_info.json")

    if not world_tree or not models_info:
        return

    model_map = {m["index"]: m["system_filepath"] for m in models_info}
    nodes_map = {n["index"]: n for n in world_tree}

    # Основная папка карты
    main_world_coll = bpy.data.collections.get("TheSting_WorldMap")
    if not main_world_coll:
        main_world_coll = bpy.data.collections.new("TheSting_WorldMap")
        bpy.context.scene.collection.children.link(main_world_coll)

    # Скрытая папка для хранения оригиналов моделей (Мастер-ассеты)
    source_coll_name = "NMF_Source_Models"
    source_models_coll = bpy.data.collections.get(source_coll_name)
    if not source_models_coll:
        source_models_coll = bpy.data.collections.new(source_coll_name)
        bpy.context.scene.collection.children.link(source_models_coll)
        # Исключаем из рендера и вьюпорта
        bpy.context.view_layer.layer_collection.children[source_coll_name].exclude = (
            True
        )

    id_to_coll = {}
    markers_by_id = {}

    # 1. Создаем коллекции-папки из world_tree
    for item in world_tree:
        if item.get("type") == 0:
            name = item.get("folder_name") or f"Folder_{item['index']}"
            new_coll = bpy.data.collections.new(name)
            id_to_coll[item["index"]] = new_coll

    for index, coll in id_to_coll.items():
        parent_id = nodes_map[index].get("parent_id")
        if parent_id in id_to_coll:
            id_to_coll[parent_id].children.link(coll)
        else:
            if coll.name not in main_world_coll.children:
                main_world_coll.children.link(coll)

    count = 0
    cached_folders = {}

    # 2. Создаем Инстансы на карте
    for item in world_tree:
        if item.get("type") == 1:
            model_id = item.get("model_id")
            if model_id is None or model_id not in model_map:
                continue

            nmf_path = model_map[model_id]

            # Находим нужную папку для инстанса
            parent_id = item.get("parent_id")
            if parent_id not in cached_folders:
                target_coll = id_to_coll.get(parent_id, main_world_coll)
                temp_p = parent_id
                while temp_p in nodes_map and temp_p not in id_to_coll:
                    temp_p = nodes_map[temp_p].get("parent_id")
                    if temp_p in id_to_coll:
                        target_coll = id_to_coll[temp_p]
                        break
                cached_folders[parent_id] = target_coll
            target_coll = cached_folders[parent_id]

            # Создаем/получаем мастер-коллекцию модели
            asset_coll = import_nmf_as_collection(
                nmf_path, model_id, source_models_coll
            )

            if asset_coll:
                # Создаем маркер-пустышку, который будет рендерить коллекцию
                obj_name = item.get("name") or f"Instance_{item['index']}"
                map_marker = bpy.data.objects.new(obj_name, None)
                map_marker.instance_type = "COLLECTION"
                map_marker.instance_collection = asset_coll

                target_coll.objects.link(map_marker)
                markers_by_id[item["index"]] = map_marker

                # Позиционируем инстанс на карте (с учетом инверсии вращения!)
                map_marker.location = (item["x"], item["z"], item["y"])
                map_marker.rotation_euler = Euler(
                    (0, 0, -item.get("rotation", 0.0)), "XYZ"
                )
                s = item.get("scaling", 1.0)
                map_marker.scale = (s, s, s)

                count += 1

    # 3. Привязка маркеров-инстансов друг к другу
    for item in world_tree:
        if item.get("type") == 1 and item["index"] in markers_by_id:
            parent_id = item.get("parent_id")
            if parent_id in markers_by_id:
                child_marker = markers_by_id[item["index"]]
                parent_marker = markers_by_id[parent_id]
                child_marker.parent = parent_marker
                child_marker.matrix_parent_inverse.identity()

    debug_log(
        f"Сборка завершена (Collection Instances)! Импортировано {count} инстансов на карту."
    )


if __name__ == "__main__":
    build_world()
