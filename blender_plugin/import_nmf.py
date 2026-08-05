# -*- coding: utf-8 -*-

"""
Import NMF

Description:
    Core logic for importing NMF data into the Blender scene.
    - Creates Materials with Principled BSDF nodes.
    - Imports Textures and configures UV mapping.
    - Builds the Scene Graph (Objects, Meshes, Empties).
    - Applies Animation tracks.

License: MIT License
"""

import bpy
import math
from mathutils import Matrix
#from .nmf_parser import Nmf
#from .nmf_convertor import convert_and_filter_nodes


# ------------------------------------------------------------------------
# Materials
# ------------------------------------------------------------------------


def _create_material_from_nmf(mat_info):
    """
    mat_info:
        {
            "mat_name": str,
            "r": float, "g": float, "b": float, "a": float,
            "repeatU": float, "repeatV": float,
            "mirrorU": int, "mirrorV": int,
            "rotateUV": float,
            "tex_path": str | None,
            "has_tex": bool,
        }
    """
    name = mat_info.get("mat_name", "NMF_Material")

    # mat = bpy.data.materials.get(name)
    # if mat is None:
    mat = bpy.data.materials.new(name)

    # Enable nodes in new Blender versions, ignore in old ones
    if hasattr(mat, "use_nodes"):
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        # Look for existing Principled BSDF
        bsdf = None
        for n in nodes:
            if n.type == "BSDF_PRINCIPLED":
                bsdf = n
                break

        # If missing — create simple tree: BSDF -> Output
        if bsdf is None:
            nodes.clear()
            out = nodes.new("ShaderNodeOutputMaterial")
            out.location = (400, 0)

            bsdf = nodes.new("ShaderNodeBsdfPrincipled")
            bsdf.location = (0, 0)

            links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    else:
        # Old Blender Internal — no nodes, exit immediately
        return mat

    # -------- Color / Alpha --------
    r = mat_info["r"]
    g = float(mat_info.get("g", 1.0))
    b = float(mat_info.get("b", 1.0))
    a_src = float(mat_info.get("a", 1.0))

    # If alpha = transparency instead of opacity, you can invert:
    # a = 1.0 - a_src
    a = a_src

    mat.diffuse_color = (r, g, b, a)

    bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
    bsdf.inputs["Alpha"].default_value = a

    # Transparency - only if Blender supports it
    mode = mat_info.get("blend_mode", 0)
    if mode == 0:  # decal
        if hasattr(mat, "blend_method"):
            mat.blend_method = "OPAQUE"
        if hasattr(mat, "shadow_method"):
            mat.shadow_method = "OPAQUE"

    elif mode == 1:  # alpha
        if hasattr(mat, "blend_method"):
            mat.blend_method = "BLEND"
        if hasattr(mat, "shadow_method"):
            mat.shadow_method = "HASHED"

    elif mode == 2:  # additive
        if hasattr(mat, "blend_method"):
            mat.blend_method = "BLEND"
        if hasattr(mat, "shadow_method"):
            mat.shadow_method = "NONE"
        # Additive effect needs node setup: MixRGB(Add)

    elif mode == 3:  # multiply
        if hasattr(mat, "blend_method"):
            mat.blend_method = "BLEND"
        if hasattr(mat, "shadow_method"):
            mat.shadow_method = "HASHED"
        # Multiply is done in nodes (MixRGB(Multiply))

    # -------- Texture / UV --------
    tex_path = mat_info.get("tex_path")
    has_tex = bool(mat_info.get("has_tex") and tex_path)

    if has_tex:
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        # UV Map
        uv_node = None
        for n in nodes:
            if n.type == "UVMAP":
                uv_node = n
                break
        if uv_node is None:
            uv_node = nodes.new("ShaderNodeUVMap")
            uv_node.location = (-800, 0)
            uv_node.uv_map = "UVMap"

        # Mapping
        mapping_node = None
        for n in nodes:
            if n.type == "MAPPING":
                mapping_node = n
                break
        if mapping_node is None:
            mapping_node = nodes.new("ShaderNodeMapping")
            mapping_node.location = (-600, 0)

        # Image Texture
        tex_node = None
        for n in nodes:
            if n.type == "TEX_IMAGE":
                tex_node = n
                break
        if tex_node is None:
            tex_node = nodes.new("ShaderNodeTexImage")
            tex_node.location = (-400, 0)

        # Try to load image
        image = None
        try:
            image = bpy.data.images.load(tex_path)
        except Exception:
            image = None

        if image is not None:
            tex_node.image = image

        # Repeats / mirrors / rotation
        repeatU = float(mat_info.get("repeatU", 1.0))
        repeatV = float(mat_info.get("repeatV", 1.0))
        mirrorU = int(mat_info.get("mirrorU", 0))
        mirrorV = int(mat_info.get("mirrorV", 0))
        rotateUV = float(mat_info.get("rotateUV", 0.0))

        # if rotateUV is in degrees:
        # rotate = math.radians(rotateUV)
        rotate = rotateUV

        scale_x = repeatU * (-1.0 if mirrorU else 1.0)
        scale_y = repeatV * (-1.0 if mirrorV else 1.0)

        mapping_node.inputs["Scale"].default_value[0] = scale_x
        mapping_node.inputs["Scale"].default_value[1] = scale_y
        mapping_node.inputs["Scale"].default_value[2] = 1.0

        mapping_node.inputs["Rotation"].default_value[0] = 0.0
        mapping_node.inputs["Rotation"].default_value[1] = 0.0
        mapping_node.inputs["Rotation"].default_value[2] = rotate

        # Helper function for linking without duplicates
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

        # Texture transparency - only if attributes exist
        # if hasattr(mat, "blend_method"):
        #     mat.blend_method = "BLEND"
        # if hasattr(mat, "shadow_method"):
        #     mat.shadow_method = "HASHED"

    return mat


def _apply_anim_to_object(obj, anim_tracks):
    """
    Writes keys directly to the object:
      translation -> location
      rotation    -> rotation_euler (XYZ, rad)
      scale       -> scale
    """
    if not anim_tracks:
        return

    obj.rotation_mode = "XYZ"
    fps = bpy.context.scene.render.fps  # e.g., 24

    spec = {
        "translation": ("location", (0, 1, 2), 1.0),
        "rotation": ("rotation_euler", (0, 1, 2), 1.0),  # already in radians
        "scale": ("scale", (0, 1, 2), 1.0),
    }

    for track, (prop, idxs, scale) in spec.items():
        track_data = anim_tracks.get(track)
        if not track_data:
            continue

        values = track_data.get("values", {})
        keys = track_data.get("times", {})

        for ax_name, ax_i in zip(("x", "y", "z"), idxs):
            vals = values.get(ax_name)
            frames = keys.get(ax_name)
            if not vals or not frames:
                continue

            for t, v in zip(frames, vals):
                frame = int(round(t * fps))  # <--- KEY CHANGE
                arr = getattr(obj, prop)
                arr[ax_i] = float(v) * scale
                obj.keyframe_insert(
                    data_path=prop,
                    index=ax_i,
                    frame=frame,
                )


def _parent_objects_by_ids(nodes, id_to_obj):
    for node in nodes:
        nid = node["id"]
        pid = node["parent_id"]

        obj = id_to_obj.get(nid)
        if obj is None:
            continue

        # Parent is a standard object
        parent_obj = id_to_obj.get(pid)
        if parent_obj is not None:
            obj.parent = parent_obj


def _build_objects_from_nodes(nodes, collection):
    """
    Creates Blender objects for types:
      - transform  -> Empty
      - empty      -> Empty
      - mesh       -> Mesh Object
    Bones are created in a separate function.
    Returns:
      id_to_obj: { node_id: bpy.types.Object }
      imported_objects: list[bpy.types.Object]
      bone_nodes: list[dict] (nodes of type "bone")
    """
    id_to_obj = {}
    imported_objects = []
    bone_nodes = []

    # First pass: create all objects except bones
    for node in nodes:
        ntype = node["type"]
        nid = node["id"]
        name = node["name"]

        if ntype == "transform":
            obj = bpy.data.objects.new(name, None)
            obj.matrix_world = Matrix(node.get("matrix"))
            if node.get("animation"):
                _apply_anim_to_object(obj, node.get("animation"))

            collection.objects.link(obj)
            id_to_obj[nid] = obj
            imported_objects.append(obj)

        elif ntype == "empty":
            obj = bpy.data.objects.new(name, None)
            # For LOCA in convert_and_filter_nodes there is no matrix - leave at (0,0,0)
            collection.objects.link(obj)
            id_to_obj[nid] = obj
            imported_objects.append(obj)

        elif ntype == "mesh":
            mesh = bpy.data.meshes.new(name)

            verts = [tuple(v) for v in node["vrts"]]
            faces = [tuple(tri) for tri in node["ibuf"]]

            mesh.from_pydata(verts, [], faces)

            # --- UV ---
            uvpt = node.get("uvpt") or []
            uv_index_of_vertex = node.get("uv_index_of_vertex") or list(
                range(len(verts))
            )
            if uvpt:
                uv_layer = mesh.uv_layers.new(name="UVMap")
                for poly in mesh.polygons:
                    for li in poly.loop_indices:
                        vidx = mesh.loops[li].vertex_index
                        uvidx = uv_index_of_vertex[vidx]
                        if 0 <= uvidx < len(uvpt):
                            u, v = uvpt[uvidx]
                            # if you want to invert V:
                            # uv_layer.data[li].uv = (u, 1.0 - v)
                            uv_layer.data[li].uv = (u, v)

            # --- Materials on mesh ---
            materials_list = node.get("materials") or []
            existing_names = [slot.name for slot in mesh.materials]

            for mat_info in materials_list:
                mat = _create_material_from_nmf(mat_info)
                if mat is None:
                    continue

                if mat.name not in existing_names:
                    mesh.materials.append(mat)
                    existing_names.append(mat.name)

                # Узнаем индекс этого материала в меше
                mat_idx = existing_names.index(mat.name)

                # Читаем unknown_ints, чтобы понять, к каким полигонам его привязать
                uints = mat_info.get("unknown_ints")
                if uints and len(uints) >= 4:
                    start_index = uints[2]   # индекс начала в буфере
                    num_indices = uints[3]   # сколько всего индексов
                    
                    # Делим на 3, так как треугольник состоит из 3 индексов
                    start_face = start_index // 3
                    num_faces = num_indices // 3

                    # Назначаем этот материал нужным полигонам
                    for f_idx in range(start_face, start_face + num_faces):
                        if f_idx < len(mesh.polygons):
                            mesh.polygons[f_idx].material_index = mat_idx

            obj = bpy.data.objects.new(name, mesh)
            collection.objects.link(obj)
            id_to_obj[nid] = obj
            imported_objects.append(obj)

        else:
            # Just in case - ignore other types
            pass

    return id_to_obj, imported_objects, bone_nodes


# ------------------------------------------------------------------------
# Main Import Function
# ------------------------------------------------------------------------


def load(operator, context, filepath):
    # Parse NMF and convert to normalized node list
    try:
        parser = Nmf()
        nodes_raw = parser.unpack(filepath)
        nodes = convert_and_filter_nodes(nodes_raw, filepath)
    except Exception as e:
        operator.report({"ERROR"}, f"NMF parse error: {e}")
        return {"CANCELLED"}

    collection = context.collection
    imported_objects = []

    # 1) Create objects (transform/empty/mesh)
    id_to_obj, objs_created, bone_nodes = _build_objects_from_nodes(nodes, collection)
    imported_objects.extend(objs_created)

    # 3) Build hierarchy
    _parent_objects_by_ids(nodes, id_to_obj)

    operator.report({"INFO"}, f"Imported NMF: {filepath}")
    return {"FINISHED"}
