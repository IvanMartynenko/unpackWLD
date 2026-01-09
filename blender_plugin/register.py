# -*- coding: utf-8 -*-

"""
NMF Addon Registration

Description:
    Registers the addon in Blender, adding the import menu entry.
"""

bl_info = {
    "name": "Neo Software NMF format",
    "author": "Ivan Martyneko / GPT",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "File > Import",
    "description": "Import Neo Software 3D files (.nmf) from Der Clou2!/The Sting!/VaBank",
    "warning": "Experimental",
    "doc_url": "",
    "support": "COMMUNITY",
    "category": "Import-Export",
}

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper


class IMPORT_SCENE_OT_nmf(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.nmf"
    bl_label = "Import NMF"
    bl_options = {"PRESET", "UNDO"}

    filename_ext = ".nmf"
    filter_glob: StringProperty(default="*.nmf", options={"HIDDEN"})

    def execute(self, context):
        try:
            load(self, context, filepath=self.filepath)
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, f"NMF import failed: {e}")
            return {"CANCELLED"}


def menu_func_import(self, context):
    self.layout.operator(IMPORT_SCENE_OT_nmf.bl_idname, text="NMF (.nmf)")


def register():
    bpy.utils.register_class(IMPORT_SCENE_OT_nmf)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(IMPORT_SCENE_OT_nmf)
