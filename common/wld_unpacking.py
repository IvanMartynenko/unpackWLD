#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Der Clou! 2 (The Sting! / Ва-Банк!) World Unpacker

Description:
    This tool extracts assets from the proprietary .wld (World) format used
    by "The Sting!". It splits the monolithic binary file into editable
    components, facilitating modding and analysis.

Features:
    - Parses the binary WLD structure (TREE, LIST, OBJS, etc.).
    - Extracts textures to valid .DDS files with generated headers (TEXP).
    - Extracts 3D models to raw .NMF files and organizes them by folder structure.
    - Exports object metadata, task lists, and world hierarchy to JSON.
    - Extracts binary shadow maps to a separate file.

License: MIT License
"""
# NewVaBankFiles/common/wld_unpacking.py

import os, struct
from .binary_reader import BinaryReader


def unpack_raw_nmf(reader):
    start_pos = reader.offset
    token = reader.read_word()
    reader.read_int()  # 0

    if token != "NMF ":
        raise ValueError(f"Expected NMF token, got {token}")

    while True:
        chunk_token = reader.read_word()
        chunk_size = reader.read_big_endian_int()  # Big-endian size
        if chunk_token == "END ":
            break

        reader.skip(chunk_size)

    end_pos = reader.offset
    return reader.data[start_pos:end_pos]


def unpack_task_params(reader, task_id, param_index, param_type):
    if param_type == 2:
        return reader.read_floats(3)
    elif param_type == 3:
        return reader.read_float()
    elif param_type in [4, 5, 8, 9, 10]:
        return reader.read_int()
    elif param_type in [6, 12, 16]:
        return reader.read_string()
    elif param_type == 7:
        # Acod structure: 4 ints
        reader.read_word()  # ACOD marker
        reader.read_big_endian_int()  # size
        return reader.read_ints(4)
    elif param_type == 15:
        return reader.read_hex(9 * 4)
    else:
        raise ValueError(f"Unknown task param type: {param_type}")


def unpack_texture_pages(reader):
    """
    Parses Texture Pages chunks.
    Returns:
        pages_info (list): Metadata for JSON.
        raw_textures (list): List of dicts with {'page_id', 'width', 'height', 'is_alpha', 'raw_bytes'}.
                             Header generation is left to the caller.
    """
    token = reader.read_word()  # TEXP
    if token != "TEXP":
        raise ValueError("Expected TEXP")
    reader.read_int()  # 0

    pages_info = []
    raw_textures = []

    while True:
        sub_token = reader.read_word()
        if sub_token == "END ":
            reader.read_int()  # 0 after END
            break
        if sub_token != "PAGE":
            raise ValueError("Expected PAGE")

        _size = reader.read_big_endian_int()

        page_data = {}
        reader.read_int()  # 2
        page_data["width"] = reader.read_int()
        page_data["height"] = reader.read_int()
        page_data["id"] = reader.read_int()

        tex_count = reader.read_int()
        textures = []
        for _ in range(tex_count):
            tex = {
                "filepath": reader.read_string(),
                "box": {
                    "x0": reader.read_int(),
                    "y0": reader.read_int(),
                    "x2": reader.read_int(),
                    "y2": reader.read_int(),
                },
                "source_box": {
                    "x0": reader.read_int(),
                    "y0": reader.read_int(),
                    "x2": reader.read_int(),
                    "y2": reader.read_int(),
                },
            }
            textures.append(tex)
        page_data["textures"] = textures

        txpg = reader.read_word()  # TXPG
        if txpg != "TXPG":
            raise ValueError("Expected TXPG")
        page_data["is_alpha"] = reader.read_bool()

        # Reading DDS data
        # Size = W * H * 2 (since it is usually 16 bits per pixel for these textures)
        dds_size = page_data["width"] * page_data["height"] * 2
        dds_bytes = reader.read_bytes(dds_size)

        pages_info.append(page_data)

        raw_textures.append(
            {
                "page_id": page_data["id"],
                "width": page_data["width"],
                "height": page_data["height"],
                "is_alpha": page_data["is_alpha"],
                "raw_bytes": dds_bytes,
            }
        )

    return pages_info, raw_textures


def unpack_folders(reader, marker):
    token = reader.read_word()
    if token != marker:
        raise ValueError(f"Expected {marker}")
    reader.read_int()  # 0

    folders = []
    index = 2
    while True:
        sub_token = reader.read_word()
        if sub_token == "END ":
            reader.read_int()  # 0 after END
            break
        if sub_token != "ENTR":
            raise ValueError("Expected ENTR")
        reader.read_big_endian_int()  # size (BigEndian)
        reader.read_int()  # 0

        folder = {
            "index": index,
            "name": reader.read_string(),
            "parent_folder_id": reader.read_int(),
        }
        folders.append(folder)
        index += 1
    return folders


def unpack_models(reader):
    """
    Parses Models chunks.
    Returns:
        models_info (list): Metadata for JSON.
        raw_models (list): List of dicts {'index', 'raw_bytes'}.
                           Path construction is left to the caller.
    """
    token = reader.read_word()  # LIST
    if token != "LIST":
        raise ValueError(f"Expected LIST")
    reader.read_int()  # 0

    models_info = []
    raw_models = []
    index = 2

    while True:
        sub_token = reader.read_word()
        if sub_token == "END ":
            reader.read_int()  # 0 after END
            break
        if sub_token != "MODL":
            raise ValueError(f"Expected MODL")
        reader.read_big_endian_int()  # size
        reader.read_int()  # 9
        reader.read_int()  # 1

        model = {
            "index": index,
            "name": reader.read_string(),
            "influences_camera": reader.read_bool(),
            "no_camera_check": reader.read_bool(),
            "anti_ground": reader.read_bool(),
            "default_skeleton": reader.read_int(),
            "use_skeleton": reader.read_int(),
        }

        # Camera
        cam_token = reader.read_word()
        if cam_token == "RMAC":
            model["camera"] = {
                "camera": {
                    "x": reader.read_float(),
                    "y": reader.read_float(),
                    "z": reader.read_float(),
                    "pitch": reader.read_float(),
                    "yaw": reader.read_float(),
                },
                "item": {
                    "x": reader.read_float(),
                    "y": reader.read_float(),
                    "z": reader.read_float(),
                    "pitch": reader.read_float(),
                    "yaw": reader.read_float(),
                },
            }

        model["parent_folder_id"] = reader.read_int()

        # Attack points
        ap_count = reader.read_int()
        attack_points = []
        for _ in range(ap_count):
            attack_points.append(
                {
                    "x": reader.read_float(),
                    "y": reader.read_float(),
                    "z": reader.read_float(),
                    "radius": reader.read_float(),
                }
            )
        if attack_points:
            model["attack_points"] = attack_points

        # NMF RAW
        # Here we read NMF as raw data and save it to a separate .nmf file
        nmf_hex = unpack_raw_nmf(reader)

        models_info.append(model)
        raw_models.append({"index": index, "raw_bytes": nmf_hex})
        index += 1

    return models_info, raw_models


def unpack_info_block(reader):
    token = reader.read_word()  # INFO
    if token != "INFO":
        raise ValueError("Expected INFO")
    reader.read_big_endian_int()  # size

    info = {
        "unknown1": reader.read_int(),
        "unknown2": reader.read_int(),
        "unknown3": reader.read_int(),
    }

    # OPTS
    opts_token = reader.read_word()
    if opts_token != "OPTS":
        raise ValueError("Expected OPTS")
    reader.read_big_endian_int()  # size

    opts = {
        "unknown1": reader.read_int(),
        "id": reader.read_string(),
        "type": reader.read_int(),
        "story": reader.read_int(),
        "clickable": reader.read_bool(),
        "process_when_visible": reader.read_bool(),
        "process_always": reader.read_bool(),
    }

    # Opts Item specific
    t = opts["type"]
    if t == 0:
        opts["info"] = {"weight": reader.read_float()}
    elif t == 1:
        # Loot
        opts["info"] = {"weight": reader.read_float(), "value": reader.read_float()}
    elif t == 2:
        # Tool
        opts["info"] = {
            "weight": reader.read_float(),
            "value": reader.read_float(),
            "strength": reader.read_float(),
            "pick_locks": reader.read_float(),
            "pick_safes": reader.read_float(),
            "alarm_systems": reader.read_float(),
            "volume": reader.read_float(),
            "damaging": reader.read_bool(),
            "applicability": {
                "glass": reader.read_float(),
                "wood": reader.read_float(),
                "steel": reader.read_float(),
                "high_tech": reader.read_float(),
            },
            "noise": {
                "glass": reader.read_float(),
                "wood": reader.read_float(),
                "steel": reader.read_float(),
                "high_tech": reader.read_float(),
            },
        }
    elif t in [3, 7, 8]:
        # Type 3: Real estate
        # Type 7: Passage — Door
        # Type 8: Passage — Window
        opts["info"] = {
            "working_time": reader.read_float(),
            "material": reader.read_int(),
            "crack_type": reader.read_int(),
        }
    elif t == 4:
        # character_a
        opts["info"] = {
            "speed": reader.read_float(),
            "occupation": reader.read_string(),
        }
    elif t in [5, 6]:
        # Character B / C
        opts["info"] = {"speed": reader.read_float()}
    elif t == 9:
        # Car
        opts["info"] = {
            "transp_space": reader.read_float(),
            "max_speed": reader.read_float(),
            "acceleration": reader.read_float(),
            "value": reader.read_float(),
            "driving": reader.read_float(),
        }
    info["opts"] = opts

    # DIALOG (COND)
    cond_token = reader.read_word()
    if cond_token != "COND":
        raise ValueError("Expected COND")
    cond_size = reader.read_big_endian_int()  # size
    reader.read_int()  # 6

    dialogs = []
    info["with_dialogs"] = False
    if cond_size > 8:
        info["with_dialogs"] = True
        # If size > 8, then there is a count of dialogs and the list
        count = reader.read_int()
        info["dialogs_count"] = count
        for _ in range(count):
            d = {
                "active": reader.read_int(),
                "Q": reader.read_string(),
                "A": reader.read_string(),
                "Dlg-": reader.read_string(),
                "Dlg+": reader.read_string(),
                "Always-": reader.read_string(),
                "Always+": reader.read_string(),
                "Always": reader.read_int(),
                "Story": reader.read_int(),
                "Coohess": reader.read_int(),
                "DialogEvent": reader.read_int(),
            }
            dialogs.append(d)
    elif cond_size == 8:
        # If size is 8, there is an extra int (unknown_value)
        info["unknow_cond_int"] = reader.read_int()
    info["dialogs"] = dialogs

    # Custom Opts Tail
    if t in [7, 8]:
        # Passage (Door/Window)
        info["custom"] = {"open": reader.read_int(), "locked": reader.read_int()}
    elif t == 3:
        # Passage / Real estate
        info["custom"] = {
            "open": reader.read_int(),
            "locked": reader.read_int(),
            "active": reader.read_int(),
        }
    elif t == 4:
        # Character A
        info["custom"] = {
            "open": reader.read_int(),
            "locked": reader.read_int(),
            "values": reader.read_floats(8),
        }

    # TALI (Tasks) with Recursion
    info["task_list"] = unpack_task_list(reader)
    if reader.read_word() == "END ":
        reader.read_int()  # 0
        return info
    else:
        raise ValueError("Expected END")


def unpack_task(reader):
    token = reader.read_word()
    if token != "TASK":
        raise ValueError("Expected TASK")
    reader.read_big_endian_int()  # size
    task = {
        "type": "TASK",
        "unknown1": reader.read_int(),
        "unknown2": reader.read_int(),
        "task_id": reader.read_int(),
        "default": reader.read_bool(),
        "critical": reader.read_bool(),
    }
    p_count = reader.read_int()
    params = []
    for idx in range(p_count):
        ptype = reader.read_int()
        pval = unpack_task_params(reader, task["task_id"], idx, ptype)
        params.append({"type": ptype, "values": pval})
    task["params"] = params
    return task


def unpack_dpnd(reader):
    token = reader.read_word()
    if token != "DPND":
        raise ValueError("Expected DPND")
    reader.read_big_endian_int()  # size
    dpnd = {"type": "DPND", "unknown1": reader.read_int()}
    # ACOD nested
    reader.read_word()  # ACOD
    reader.read_big_endian_int()  # size
    dpnd["acod"] = reader.read_ints(4)
    dpnd["unknown2"] = reader.read_ints(4)
    # Nested TALI -> Recursion
    dpnd["sub_tasks"] = unpack_task_list(reader)
    dpnd["unknown3"] = reader.read_ints(9)
    dtype = reader.read_int()
    dpnd["dtype"] = dtype
    if dtype == 1:
        dpnd["unknown4"] = reader.read_ints(2)
    elif dtype == 2:
        dpnd["unknown4"] = reader.read_ints(4)
    return dpnd


def unpack_task_list(reader):
    token = reader.read_word()
    if token != "TALI":
        raise ValueError(f"Expected TALI, got {token}")
    reader.read_big_endian_int()  # size
    reader.read_int()  # 0
    tasks = []
    while True:
        token = reader.peek_word()
        if token == "END ":
            reader.read_word()
            reader.read_int()  # 0 after END
            break
        if token == "TASK":
            tasks.append(unpack_task(reader))
        elif token == "DPND":
            tasks.append(unpack_dpnd(reader))
        else:
            raise ValueError(f"Unknown token in TaskList: {token}")
    return tasks


def unpack_objects(reader):
    token = reader.read_word()  # OBJS
    if token != "OBJS":
        raise ValueError(f"Expected OBJS, got {token}")
    reader.read_int()  # 0
    objects = []
    index = 1
    while True:
        sub_token = reader.read_word()
        if sub_token == "END ":
            reader.read_int()  # 0 after END
            break
        if sub_token != "OBJ ":
            raise ValueError(f"Expected OBJ, got {token}")
        reader.read_big_endian_int()  # size
        obj = {
            "index": index,
            "type": reader.read_int(),
            "name": reader.read_string(),
            "parent_folder": reader.read_int(),
        }

        # 3d files
        model_count = reader.read_int()
        models = []
        for _ in range(model_count):
            model = {
                "name": reader.read_string(),
                "model_3d_id": reader.read_int(),
                "unknown2": reader.read_float(),
                "unknown3": reader.read_float(),
                "unknown4": reader.read_int(),
                "alway_negative100": reader.read_float(),
                "loop_animation": reader.read_bool(),
                "default_action": reader.read_bool(),
            }
            uk7_count = reader.read_int()
            uk7 = []
            for _ in range(uk7_count):
                uk7.append(
                    {"name": reader.read_string(), "unknown1": reader.read_float()}
                )
            model["animations"] = uk7
            models.append(model)
        obj["models"] = models

        # Info Block
        obj["info"] = unpack_info_block(reader)
        objects.append(obj)
        index += 1
    return objects


def unpack_makl(reader):
    token = reader.read_word()
    if token != "MAKL":
        raise ValueError("Expected MAKL")
    reader.read_int()
    while True:
        sub = reader.read_word()
        if sub == "END ":
            reader.read_int()
            break


def unpack_world(reader):
    token = reader.read_word()  # TREE
    if token != "TREE":
        raise ValueError("Expected TREE")
    reader.read_int()
    world_items = []
    shadows = []
    index = 2
    while True:
        sub_token = reader.read_word()
        if sub_token == "END ":
            reader.read_int()
            break
        if sub_token != "NODE":
            raise ValueError("Expected NODE")
        reader.read_big_endian_int()  # size of block
        reader.read_int()  # 15
        item = {
            "index": index,
            "parent_id": reader.read_int(),
            "folder_name": reader.read_string(),
            "x": reader.read_float(),
            "y": reader.read_float(),
            "z": reader.read_float(),
            "rotation": reader.read_float(),
            "unknown_n": reader.read_float(),
            "scaling": reader.read_float(),
            "unknown1": reader.read_int(),
            "type": reader.read_int(),
        }
        t = item["type"]
        if t == 0:
            # Folder
            item["folder_unknow_values"] = reader.read_ints(4)
        elif t == 1:
            # 3d Model
            item["model_id"] = reader.read_int()
            con_count = reader.read_int()
            if con_count > 0:
                item["connections"] = [reader.read_ints(2) for _ in range(con_count)]
            reader.read_int()  # 0

            shad_token = reader.read_word()
            if shad_token == "SHAD":
                s1 = reader.read_int()
                s2 = reader.read_int()
                extra = 1 if (s1 % 2 != 0 and s2 % 2 != 0) else 0
                size = (s1 * s2 // 2) + extra
                shad_data = reader.read_uints16(size * 2)

                # Saving shadow separately
                item["shadow"] = {"size1": s1, "size2": s2, "data": shad_data}
                item["has_shadow"] = True
        elif t == 2:
            item["object_id"] = reader.read_int()
            reader.read_int()  # 0
            # Info might exist, might not
            check = reader.peek_word()
            if check == "INFO":
                item["info"] = unpack_info_block(reader)
            else:
                reader.read_int()  # 0
            reader.read_int()
        elif t == 3:
            item["light"] = {
                "unknown1": reader.read_int(),
                "floats1": reader.read_floats(11),
                "unknown2": reader.read_int(),
                "floats2": reader.read_floats(13),
                "ints": reader.read_ints(4),
            }
        world_items.append(item)
        index += 1
    return world_items


def unpack_wld_to_data(wld_path):
    if not os.path.exists(wld_path):
        raise FileNotFoundError(f"File not found: {wld_path}")

    with open(wld_path, "rb") as f:
        data = f.read()

    reader = BinaryReader(data)
    header = reader.read_word()
    if header != "WRLD":
        raise ValueError("Not a WLD file.")
    reader.read_int()

    # Result structure
    result = {
        "texture_pages_info": [],
        "raw_textures": [], 
        "model_folders": [],
        "object_folders": [],
        "models_info": [],
        "raw_models": [], 
        "objects": [],
        "world_tree": [],
        # shadows_data removed, shadows are inside world_tree items
    }

    while not reader.eof():
        token = reader.peek_word()
        if token == "EOF ":
            break

        if token == "TEXP":
            pages, raw_textures = unpack_texture_pages(reader)
            result["texture_pages_info"] = pages
            result["raw_textures"] = raw_textures

        elif token == "GROU":
            result["model_folders"] = unpack_folders(reader, "GROU")

        elif token == "OBGR":
            result["object_folders"] = unpack_folders(reader, "OBGR")

        elif token == "LIST":
            models, raw_models = unpack_models(reader)
            result["models_info"] = models
            result["raw_models"] = raw_models

        elif token == "OBJS":
            result["objects"] = unpack_objects(reader)

        elif token == "MAKL":
            unpack_makl(reader)

        elif token == "TREE":
            result["world_tree"] = unpack_world(reader)

        else:
            print(f"Unknown token: {token}")
            break

    return result
