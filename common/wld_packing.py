#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Der Clou! 2 (The Sting! / Ва-Банк!) World Packer Logic

Description:
    This module contains the logic to pack extracted game assets into the
    proprietary .wld format. It operates on in-memory data structures and
    returns raw binary data. It performs no file I/O.

License: MIT License
"""

from .binary_writer import BinaryWriter


def pack_task_params(writer, val, param_type):
    if param_type == 2:
        writer.push_floats(val)
    elif param_type == 3:
        writer.push_float(val)
    elif param_type in [4, 5, 8, 9, 10]:
        writer.push_int(val)
    elif param_type in [6, 12, 16]:
        writer.push_string(val)
    elif param_type == 7:
        writer.push_word("ACOD")
        writer.push_big_endian_int(16)
        writer.push_ints(val)
    elif param_type == 15:
        writer.push_hex(val)


def pack_task(writer, task):
    temp = BinaryWriter()
    temp.push_int(task["unknown1"])
    temp.push_int(task["unknown2"])
    temp.push_int(task["task_id"])
    temp.push_bool(task["default"])
    temp.push_bool(task["critical"])
    temp.push_int(len(task["params"]))
    for param in task["params"]:
        temp.push_int(param["type"])
        pack_task_params(temp, param["values"], param["type"])

    writer.push_word("TASK")
    writer.push_big_endian_int(len(temp.get_data()))
    writer.push_bytes(temp.get_data())


def pack_dpnd(writer, dpnd):
    temp = BinaryWriter()
    temp.push_int(dpnd["unknown1"])
    temp.push_word("ACOD")
    temp.push_big_endian_int(16)
    temp.push_ints(dpnd["acod"])
    temp.push_ints(dpnd["unknown2"])

    # Nested TALI
    pack_task_list(temp, dpnd.get("sub_tasks", []))

    temp.push_ints(dpnd["unknown3"])
    temp.push_int(dpnd["dtype"])
    if "unknown4" in dpnd:
        temp.push_ints(dpnd["unknown4"])

    writer.push_word("DPND")
    writer.push_big_endian_int(len(temp.get_data()))
    writer.push_bytes(temp.get_data())


def pack_task_list(writer, tasks):
    content = BinaryWriter()
    content.push_int(0)  # Initial zero

    for task in tasks:
        if task["type"] == "TASK":
            pack_task(content, task)
        elif task["type"] == "DPND":
            pack_dpnd(content, task)

    writer.push_word("TALI")
    writer.push_big_endian_int(len(content.get_data()) + 8)  # +8 for END + 0
    writer.push_bytes(content.get_data())
    writer.push_word("END ")
    writer.push_int(0)


def pack_info_block(writer, info):
    writer.push_word("INFO")

    # Collecting data into a temporary buffer to calculate size
    temp = BinaryWriter()
    temp.push_int(info["unknown1"])
    temp.push_int(info["unknown2"])
    temp.push_int(info["unknown3"])

    # OPTS
    opts = info["opts"]
    temp_opts = BinaryWriter()
    temp_opts.push_int(opts["unknown1"])
    temp_opts.push_string(opts["id"])
    temp_opts.push_int(opts["type"])
    temp_opts.push_int(opts["story"])
    temp_opts.push_bool(opts["clickable"])
    temp_opts.push_bool(opts["process_when_visible"])
    temp_opts.push_bool(opts["process_always"])

    t = opts["type"]
    d = opts["info"]
    if t == 0:
        temp_opts.push_float(d["weight"])
    elif t == 1:
        temp_opts.push_float(d["weight"])
        temp_opts.push_float(d["value"])
    elif t == 2:
        temp_opts.push_float(d["weight"])
        temp_opts.push_float(d["value"])
        temp_opts.push_float(d["strength"])
        temp_opts.push_float(d["pick_locks"])
        temp_opts.push_float(d["pick_safes"])
        temp_opts.push_float(d["alarm_systems"])
        temp_opts.push_float(d["volume"])
        temp_opts.push_bool(d["damaging"])
        temp_opts.push_float(d["applicability"]["glass"])
        temp_opts.push_float(d["applicability"]["wood"])
        temp_opts.push_float(d["applicability"]["steel"])
        temp_opts.push_float(d["applicability"]["high_tech"])
        temp_opts.push_float(d["noise"]["glass"])
        temp_opts.push_float(d["noise"]["wood"])
        temp_opts.push_float(d["noise"]["steel"])
        temp_opts.push_float(d["noise"]["high_tech"])
    elif t in [3, 7, 8]:
        temp_opts.push_float(d["working_time"])
        temp_opts.push_int(d["material"])
        temp_opts.push_int(d["crack_type"])
    elif t == 4:
        temp_opts.push_float(d["speed"])
        temp_opts.push_string(d["occupation"])
    elif t in [5, 6]:
        temp_opts.push_float(d["speed"])
    elif t == 9:
        temp_opts.push_float(d["transp_space"])
        temp_opts.push_float(d["max_speed"])
        temp_opts.push_float(d["acceleration"])
        temp_opts.push_float(d["value"])
        temp_opts.push_float(d["driving"])

    temp.push_word("OPTS")
    temp.push_big_endian_int(len(temp_opts.get_data()))
    temp.push_bytes(temp_opts.get_data())

    # COND (Dialog)
    temp_cond = BinaryWriter()
    temp_cond.push_int(6)  # flag

    dialogs = info.get("dialogs", [])
    if info.get("with_dialogs"):
        temp_cond.push_int(info["dialogs_count"])
        for d in dialogs:
            temp_cond.push_int(d["active"])
            temp_cond.push_string(d["Q"])
            temp_cond.push_string(d["A"])
            temp_cond.push_string(d["Dlg-"])
            temp_cond.push_string(d["Dlg+"])
            temp_cond.push_string(d["Always-"])
            temp_cond.push_string(d["Always+"])
            temp_cond.push_int(d["Always"])
            temp_cond.push_int(d["Story"])
            temp_cond.push_int(d["Coohess"])
            temp_cond.push_int(d["DialogEvent"])

    if "unknow_cond_int" in info:
        temp_cond.push_int(info["unknow_cond_int"])

    # Custom
    c = info.get("custom")
    if c:
        if t in [7, 8]:
            temp_cond.push_int(c["open"])
            temp_cond.push_int(c["locked"])
        elif t == 3:
            temp_cond.push_int(c["open"])
            temp_cond.push_int(c["locked"])
            temp_cond.push_int(c["active"])
        elif t == 4:
            temp_cond.push_int(c["open"])
            temp_cond.push_int(c["locked"])
            temp_cond.push_floats(c["values"])

    temp.push_word("COND")
    temp.push_big_endian_int(len(temp_cond.get_data()))
    temp.push_bytes(temp_cond.get_data())

    # TALI
    pack_task_list(temp, info.get("task_list", []))

    temp.push_word("END ")
    temp.push_int(0)

    writer.push_big_endian_int(len(temp.get_data()))
    writer.push_bytes(temp.get_data())


def pack_wld_data(data):
    """
    Main function to pack data into WLD binary format.

    Args:
        data (dict): Dictionary containing all WLD components:
                     - texture_pages (list): List of page dicts. Must contain 'raw_bytes'.
                     - model_folders (list): List of folder dicts.
                     - object_folders (list): List of folder dicts.
                     - models_info (list): List of model dicts. Must contain 'raw_bytes' (NMF data).
                     - objects (list): List of object dicts.
                     - world_tree (list): List of node dicts. 'shadow' data must be embedded if present.

    Returns:
        bytes: The complete WLD binary file.
    """
    writer = BinaryWriter()
    writer.push_word("WRLD")
    writer.push_int(0)

    # 1. TEXTURE PAGES
    # Caller is responsible for reading DDS, calculating dimensions,
    # and populating 'raw_bytes' inside each page dict.
    if "texture_pages" in data and data["texture_pages"]:
        writer.push_word("TEXP")
        writer.push_int(0)

        for page in data["texture_pages"]:
            writer.push_word("PAGE")

            # Page body
            pw = BinaryWriter()
            pw.push_int(2)
            pw.push_int(page["width"])
            pw.push_int(page["height"])
            pw.push_int(page["id"])
            pw.push_int(len(page.get("textures", [])))

            for tex in page.get("textures", []):
                pw.push_string(tex["filepath"])
                b = tex["box"]
                pw.push_int(b["x0"])
                pw.push_int(b["y0"])
                pw.push_int(b["x2"])
                pw.push_int(b["y2"])
                b = tex["source_box"]
                pw.push_int(b["x0"])
                pw.push_int(b["y0"])
                pw.push_int(b["x2"])
                pw.push_int(b["y2"])

            pw.push_word("TXPG")
            pw.push_bool(page["is_alpha"])

            # The raw texture bytes (minus header) should be in 'raw_bytes'
            if "raw_bytes" not in page:
                raise ValueError(
                    f"Missing 'raw_bytes' for texture page {page.get('id')}"
                )
            pw.push_bytes(page["raw_bytes"])

            writer.push_big_endian_int(len(pw.get_data()))
            writer.push_bytes(pw.get_data())

        writer.push_word("END ")
        writer.push_int(0)

    # 2. MODEL FOLDERS
    if "model_folders" in data and data["model_folders"]:
        writer.push_word("GROU")
        writer.push_int(0)
        for folder in data["model_folders"]:
            writer.push_word("ENTR")
            fw = BinaryWriter()
            fw.push_int(0)
            fw.push_string(folder["name"])
            fw.push_int(folder["parent_folder_id"])
            writer.push_big_endian_int(len(fw.get_data()))
            writer.push_bytes(fw.get_data())
        writer.push_word("END ")
        writer.push_int(0)

    # 3. OBJECT FOLDERS
    if "object_folders" in data and data["object_folders"]:
        writer.push_word("OBGR")
        writer.push_int(0)
        for folder in data["object_folders"]:
            writer.push_word("ENTR")
            fw = BinaryWriter()
            fw.push_int(0)
            fw.push_string(folder["name"])
            fw.push_int(folder["parent_folder_id"])
            writer.push_big_endian_int(len(fw.get_data()))
            writer.push_bytes(fw.get_data())
        writer.push_word("END ")
        writer.push_int(0)

    # 4. MODELS
    # Caller is responsible for reading .nmf files and putting content in 'raw_bytes'
    if "models_info" in data and data["models_info"]:
        writer.push_word("LIST")
        writer.push_int(0)
        for model in data["models_info"]:
            writer.push_word("MODL")
            mw = BinaryWriter()
            mw.push_int(9)
            mw.push_int(1)
            mw.push_string(model["name"])
            mw.push_bool(model["influences_camera"])
            mw.push_bool(model["no_camera_check"])
            mw.push_bool(model["anti_ground"])
            mw.push_int(model["default_skeleton"])
            mw.push_int(model["use_skeleton"])

            if "camera" in model:
                mw.push_word("RMAC")
                c = model["camera"]["camera"]
                mw.push_float(c["x"])
                mw.push_float(c["y"])
                mw.push_float(c["z"])
                mw.push_float(c["pitch"])
                mw.push_float(c["yaw"])
                c = model["camera"]["item"]
                mw.push_float(c["x"])
                mw.push_float(c["y"])
                mw.push_float(c["z"])
                mw.push_float(c["pitch"])
                mw.push_float(c["yaw"])
            else:
                mw.push_int(0)

            mw.push_int(model["parent_folder_id"])
            aps = model.get("attack_points", [])
            mw.push_int(len(aps))
            for ap in aps:
                mw.push_float(ap["x"])
                mw.push_float(ap["y"])
                mw.push_float(ap["z"])
                mw.push_float(ap["radius"])

            # NMF Data
            if "raw_bytes" not in model:
                raise ValueError(f"Missing 'raw_bytes' for model {model.get('name')}")
            mw.push_bytes(model["raw_bytes"])

            writer.push_big_endian_int(len(mw.get_data()))
            writer.push_bytes(mw.get_data())
        writer.push_word("END ")
        writer.push_int(0)

    # 5. OBJECTS
    if "objects" in data and data["objects"]:
        writer.push_word("OBJS")
        writer.push_int(0)
        for obj in data["objects"]:
            writer.push_word("OBJ ")
            ow = BinaryWriter()
            ow.push_int(obj["type"])
            ow.push_string(obj["name"])
            ow.push_int(obj["parent_folder"])

            anims = obj.get("models", obj.get("animations", []))
            ow.push_int(len(anims))
            for anim in anims:
                ow.push_string(anim["name"])
                ow.push_int(anim["model_3d_id"])
                ow.push_float(anim["unknown2"])
                ow.push_float(anim["unknown3"])
                ow.push_int(anim["unknown4"])
                ow.push_float(anim["alway_negative100"])
                ow.push_bool(anim["loop_animation"])
                ow.push_bool(anim["default_action"])

                subs = anim.get("animations", anim.get("unknown7", []))
                ow.push_int(len(subs))
                for u in subs:
                    ow.push_string(u["name"])
                    ow.push_float(u["unknown1"])

            pack_info_block(ow, obj["info"])

            writer.push_big_endian_int(len(ow.get_data()))
            writer.push_bytes(ow.get_data())
        writer.push_word("END ")
        writer.push_int(0)

    # 6. MAKL (Empty)
    writer.push_word("MAKL")
    writer.push_int(0)
    writer.push_word("END ")
    writer.push_int(0)

    # 7. WORLD TREE
    if "world_tree" in data and data["world_tree"]:
        writer.push_word("TREE")
        writer.push_int(0)

        tree_buffer = BinaryWriter()

        for item in data["world_tree"]:
            tree_buffer.push_word("NODE")

            nw = BinaryWriter()
            nw.push_int(15)
            nw.push_int(item["parent_id"])
            nw.push_string(item["folder_name"])
            nw.push_float(item["x"])
            nw.push_float(item["y"])
            nw.push_float(item["z"])
            nw.push_float(item["rotation"])
            nw.push_float(item["unknown_n"])
            nw.push_float(item["scaling"])

            nw.push_int(item["unknown1"])
            nw.push_int(item["type"])

            t = item["type"]
            if t == 0:
                nw.push_ints(item["folder_unknow_values"])
            elif t == 1:
                nw.push_int(item["model_id"])
                cons = item.get("connections", [])
                nw.push_int(len(cons))
                for c in cons:
                    nw.push_ints(c)
                nw.push_int(0)

                # Shadow data must be pre-attached to the item dictionary by the caller
                shad = item.get("shadow")
                if shad:
                    nw.push_word("SHAD")
                    nw.push_int(shad["size1"])
                    nw.push_int(shad["size2"])
                    nw.push_uints16(shad["data"])
                else:
                    nw.push_int(0)

            elif t == 2:
                nw.push_int(item["object_id"])
                nw.push_int(0)
                if "info" in item:
                    pack_info_block(nw, item["info"])
                else:
                    nw.push_int(0)
                nw.push_int(0)

            elif t == 3:
                l = item["light"]
                nw.push_int(l["unknown1"])
                nw.push_floats(l["floats1"])
                nw.push_int(l["unknown2"])
                nw.push_floats(l["floats2"])
                nw.push_ints(l.get("ints", l.get("unknown3", [])))

            tree_buffer.push_big_endian_int(len(nw.get_data()))
            tree_buffer.push_bytes(nw.get_data())

        tree_buffer.push_word("END ")
        tree_buffer.push_int(0)
        writer.push_bytes(tree_buffer.get_data())

    writer.push_word("EOF ")
    writer.push_int(0)

    return writer.get_data()
