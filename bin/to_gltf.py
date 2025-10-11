#!/usr/bin/env python3
"""
Converter from the custom Sting-like JSON (as pasted in the prompt) to glTF 2.0 (.gltf + .bin).

USAGE
-----
python sting_json_to_gltf.py input.json output.gltf
# This will also write a sibling output.bin and reference it from the glTF.

ASSUMPTIONS & NOTES
-------------------
- The input is a JSON array of objects with fields: word (ROOT/FRAM/MESH), name, parent_iid, data, index.
- Hierarchy is formed by parent_iid linking to another object's index.
- For transforms we prefer `data.matrix` (4x4). We write it directly to glTF node.matrix (column-major per glTF). If the
  input is effectively row-major, you may need to transpose. Toggle TRANSPOSE_MATRIX to True if needed.
- Mesh vbuf entries appear to be 10 floats per vertex: [px,py,pz, nx,ny,nz, ?, ?, u, v]. We use the LAST TWO floats
  as TEXCOORD_0 (u, v) and ignore the two preceding floats (unknown/aux UV set). If your data differs, adjust slicing.
- Indices (ibuf) are triangle triplets referencing vbuf row indices.
- Materials: if a texture path is present, we create a baseColorTexture referencing the basename. Copy textures next to
  the output .gltf or change the image URI handling.
- Animations: experimental. If a FRAM/ROOT node has `data.anim.translation` with `values.x` (times) and `values.z`
  (displacements), we create a translation channel where only Z changes over time. You can expand similarly for X/Y.

This script aims to produce a valid minimal glTF 2.0 file consumable by viewers like Babylon/Three.js.
"""
from __future__ import annotations
import json
import math
import os
import struct
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

TRANSPOSE_MATRIX = False  # set True if your source matrices are row-major and appear flipped in viewers

# -------------------------
# Utility helpers
# -------------------------

def flatten(list_of_lists):
    for sub in list_of_lists:
        for x in sub:
            yield x

def mat4_to_gltf_array(m: List[List[float]]) -> List[float]:
    """glTF expects column-major order when providing node.matrix.
    If TRANSPOSE_MATRIX is True, transpose the 4x4 first.
    Input m is 4x4 nested list.
    """
    if TRANSPOSE_MATRIX:
        m = [
            [m[0][0], m[1][0], m[2][0], m[3][0]],
            [m[0][1], m[1][1], m[2][1], m[3][1]],
            [m[0][2], m[1][2], m[2][2], m[3][2]],
            [m[0][3], m[1][3], m[2][3], m[3][3]],
        ]
    # column-major flatten
    return [
        m[0][0], m[1][0], m[2][0], m[3][0],
        m[0][1], m[1][1], m[2][1], m[3][1],
        m[0][2], m[1][2], m[2][2], m[3][2],
        m[0][3], m[1][3], m[2][3], m[3][3],
    ]

# -------------------------
# Buffer builder
# -------------------------
@dataclass
class BufferBuilder:
    data: bytearray = field(default_factory=bytearray)
    bufferViews: List[dict] = field(default_factory=list)
    accessors: List[dict] = field(default_factory=list)

    def add_blob(self, blob: bytes, target: Optional[int] = None) -> int:
        # 4-byte align per glTF
        while len(self.data) % 4:
            self.data.append(0)
        offset = len(self.data)
        self.data.extend(blob)
        bv = {"buffer": 0, "byteOffset": offset, "byteLength": len(blob)}
        if target is not None:
            bv["target"] = target
        self.bufferViews.append(bv)
        return len(self.bufferViews) - 1

    def add_accessor(self, bufferView: int, componentType: int, count: int, type_: str, min_=None, max_=None, normalized: bool=False) -> int:
        acc = {
            "bufferView": bufferView,
            "componentType": componentType,
            "count": count,
            "type": type_,
        }
        if normalized:
            acc["normalized"] = True
        if min_ is not None:
            acc["min"] = min_
        if max_ is not None:
            acc["max"] = max_
        self.accessors.append(acc)
        return len(self.accessors) - 1

# -------------------------
# Main conversion
# -------------------------

def parse_input(path: str) -> List[dict]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

@dataclass
class Obj:
    word: str
    name: str
    parent_iid: Optional[int]
    data: dict
    index: int


def build_scene(objs: List[dict], out_gltf_path: str):
    # Map index -> object
    objs_parsed: Dict[int, Obj] = {}
    for o in objs:
        objs_parsed[o["index"]] = Obj(
            word=o.get("word"), name=o.get("name"), parent_iid=o.get("parent_iid"), data=o.get("data", {}), index=o.get("index")
        )

    # Collect children
    children_map: Dict[int, List[int]] = {idx: [] for idx in objs_parsed.keys()}
    for idx, obj in objs_parsed.items():
        pid = obj.parent_iid
        if pid in children_map:
            children_map[pid].append(idx)

    # glTF skeletons
    gltf = {
        "asset": {"version": "2.0", "generator": "sting_json_to_gltf.py"},
        "scene": 0,
        "scenes": [{"nodes": []}],
        "nodes": [],
        "meshes": [],
        "materials": [],
        "textures": [],
        "images": [],
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}],
        "buffers": [],
        "bufferViews": [],
        "accessors": [],
    }

    buf = BufferBuilder()

    # Material/texture registries
    mat_registry: Dict[str, int] = {}
    img_registry: Dict[str, int] = {}
    tex_registry: Dict[str, int] = {}

    def get_image_for_path(path: Optional[str]) -> Optional[int]:
        if not path:
            return None
        uri = os.path.basename(path)
        if uri not in img_registry:
            gltf["images"].append({"uri": uri})
            img_registry[uri] = len(gltf["images"]) - 1
        return img_registry[uri]

    def get_texture_for_image(img_idx: int) -> int:
        key = str(img_idx)
        if key not in tex_registry:
            gltf["textures"].append({"sampler": 0, "source": img_idx})
            tex_registry[key] = len(gltf["textures"]) - 1
        return tex_registry[key]

    def get_material(mat: dict) -> int:
        # Create a simple PBR metallicRoughness from the provided data
        name = mat.get("name") or "material"
        tex_path = (mat.get("texture") or {}).get("name")
        baseColorFactor = [mat.get("red", 1.0), mat.get("green", 1.0), mat.get("blue", 1.0), mat.get("alpha", 1.0)]
        key = json.dumps([name, tex_path, baseColorFactor])
        if key in mat_registry:
            return mat_registry[key]
        pbr = {"baseColorFactor": baseColorFactor, "metallicFactor": 0.0, "roughnessFactor": 1.0}
        if tex_path:
            img_idx = get_image_for_path(tex_path)
            if img_idx is not None:
                tex_idx = get_texture_for_image(img_idx)
                pbr["baseColorTexture"] = {"index": tex_idx}
        gltf["materials"].append({"name": name, "pbrMetallicRoughness": pbr})
        mat_registry[key] = len(gltf["materials"]) - 1
        return mat_registry[key]

    # Map from custom object index to glTF node index
    node_idx_map: Dict[int, int] = {}

    # Pre-pass to create nodes for FRAM/ROOT/MESH holders; meshes will be attached to their parent FRAM as glTF mesh
    for idx, obj in objs_parsed.items():
        if obj.word in ("ROOT", "FRAM"):
            node = {"name": obj.name}
            # transform
            M = obj.data.get("matrix")
            if isinstance(M, list) and len(M) == 4 and all(isinstance(r, list) and len(r) == 4 for r in M):
                node["matrix"] = mat4_to_gltf_array(M)
            else:
                # Fallback to TRS if present
                T = obj.data.get("translation"); R = obj.data.get("rotation"); S = obj.data.get("scaling")
                if T: node["translation"] = [float(T[0]), float(T[1]), float(T[2])]
                if S: node["scale"] = [float(S[0]), float(S[1]), float(S[2])]
                # rotation is ambiguous in source; if it is Euler (XYZ radians), you could convert to quaternion
                # We skip it here unless you add conversion.
            node["children"] = []
            gltf["nodes"].append(node)
            node_idx_map[idx] = len(gltf["nodes"]) - 1

    # Second pass: create mesh primitives and glTF mesh objects for each MESH object, then attach them to their FRAM parent
    for idx, obj in objs_parsed.items():
        if obj.word == "MESH":
            d = obj.data
            vbuf = d.get("vbuf", [])
            ibuf = d.get("ibuf", [])
            materials = d.get("materials", [])

            # Parse vertex attributes
            positions: List[Tuple[float, float, float]] = []
            normals: List[Tuple[float, float, float]] = []
            uvs: List[Tuple[float, float]] = []
            for v in vbuf:
                if not isinstance(v, list) or len(v) < 8:
                    continue
                px, py, pz = float(v[0]), float(v[1]), float(v[2])
                nx, ny, nz = float(v[3]), float(v[4]), float(v[5])
                # Take LAST TWO floats as UV0
                if len(v) >= 10:
                    u, vv = float(v[-2]), float(v[-1])
                elif len(v) >= 8:
                    u, vv = float(v[6]), float(v[7])
                else:
                    u, vv = 0.0, 0.0
                positions.append((px, py, pz))
                normals.append((nx, ny, nz))
                uvs.append((u, vv))

            # Flatten indices
            indices: List[int] = []
            for tri in ibuf:
                if isinstance(tri, list) and len(tri) == 3:
                    indices.extend([int(tri[0]), int(tri[1]), int(tri[2])])

            # Build buffers
            # Positions
            pos_blob = b"".join(struct.pack("<3f", *p) for p in positions)
            pos_bv = buf.add_blob(pos_blob, target=34962)  # ARRAY_BUFFER
            min_v = [min(p[i] for p in positions) if positions else 0.0 for i in range(3)]
            max_v = [max(p[i] for p in positions) if positions else 0.0 for i in range(3)]
            pos_acc = buf.add_accessor(pos_bv, 5126, len(positions), "VEC3", min_=min_v, max_=max_v)  # FLOAT

            # Normals
            nrm_blob = b"".join(struct.pack("<3f", *n) for n in normals)
            nrm_bv = buf.add_blob(nrm_blob, target=34962)
            nrm_acc = buf.add_accessor(nrm_bv, 5126, len(normals), "VEC3")

            # UVs
            uv_blob = b"".join(struct.pack("<2f", *uv) for uv in uvs)
            uv_bv = buf.add_blob(uv_blob, target=34962)
            uv_acc = buf.add_accessor(uv_bv, 5126, len(uvs), "VEC2")

            # Indices
            use_u16 = max(indices) < 65536 if indices else True
            if use_u16:
                idx_blob = b"".join(struct.pack("<H", i) for i in indices)
                comp = 5123  # UNSIGNED_SHORT
            else:
                idx_blob = b"".join(struct.pack("<I", i) for i in indices)
                comp = 5125  # UNSIGNED_INT
            idx_bv = buf.add_blob(idx_blob, target=34963)  # ELEMENT_ARRAY_BUFFER
            idx_acc = buf.add_accessor(idx_bv, comp, len(indices), "SCALAR")

            # Material (use the first one if multiple)
            mat_idx = None
            if materials:
                mat_idx = get_material(materials[0])

            # Create glTF mesh
            prim = {
                "attributes": {"POSITION": pos_acc, "NORMAL": nrm_acc, "TEXCOORD_0": uv_acc},
                "indices": idx_acc,
            }
            if mat_idx is not None:
                prim["material"] = mat_idx
            mesh_obj = {"name": obj.name, "primitives": [prim]}
            gltf["meshes"].append(mesh_obj)
            gltf_mesh_index = len(gltf["meshes"]) - 1

            # Attach to parent node (FRAM) if exists, else create a node
            parent = objs_parsed.get(obj.parent_iid)
            if parent and parent.index in node_idx_map:
                gltf_node_idx = node_idx_map[parent.index]
                gltf["nodes"][gltf_node_idx]["mesh"] = gltf_mesh_index
            else:
                # create standalone node
                node = {"name": obj.name, "mesh": gltf_mesh_index}
                gltf["nodes"].append(node)
                node_idx = len(gltf["nodes"]) - 1
                node_idx_map[idx] = node_idx

    # Wire up children in nodes
    for idx, obj in objs_parsed.items():
        if obj.word in ("ROOT", "FRAM") and idx in node_idx_map:
            node_i = node_idx_map[idx]
            kids = [k for k in children_map.get(idx, []) if k in node_idx_map]
            if kids:
                gltf["nodes"][node_i]["children"] = [node_idx_map[k] for k in kids]

    # Determine scene roots: objects whose parent is None or a non-existent id
    roots: List[int] = []
    for idx, obj in objs_parsed.items():
        if obj.word in ("ROOT", "FRAM") and idx in node_idx_map:
            pid = obj.parent_iid
            if pid not in node_idx_map:
                roots.append(node_idx_map[idx])
    if not roots:
        # fall back to any nodes without parents
        roots = list({node_idx_map[i] for i in node_idx_map.keys()})
    gltf["scenes"][0]["nodes"] = roots

    # --------- Animations (very limited, demo) ---------
    animations: List[dict] = []
    for idx, obj in objs_parsed.items():
        if obj.word in ("ROOT", "FRAM") and idx in node_idx_map:
            anim = obj.data.get("anim") or {}
            tanim = anim.get("translation") or {}
            values = tanim.get("values") or {}
            if "x" in values and ("z" in values or "y" in values):
                times = [float(t) for t in values["x"]]
                # Build vec3 outputs; only Z changes if available
                zvals = [float(v) for v in values.get("z", [0.0]*len(times))]
                yvals = [float(v) for v in values.get("y", [0.0]*len(times))]
                xvals = [float(v) for v in values.get("t", [0.0]*len(times))]  # non-standard; keep zero
                outs = []
                for i in range(len(times)):
                    outs.extend([xvals[i] if i < len(xvals) else 0.0,
                                 yvals[i] if i < len(yvals) else 0.0,
                                 zvals[i] if i < len(zvals) else 0.0])
                # Pack inputs/outputs
                inp_blob = b"".join(struct.pack("<f", t) for t in times)
                inp_bv = buf.add_blob(inp_blob)
                inp_acc = buf.add_accessor(inp_bv, 5126, len(times), "SCALAR", min_=[min(times)], max_=[max(times)])

                out_blob = b"".join(struct.pack("<3f", *outs[i*3:(i+1)*3]) for i in range(len(times)))
                out_bv = buf.add_blob(out_blob)
                out_acc = buf.add_accessor(out_bv, 5126, len(times), "VEC3")

                sampler = {"input": inp_acc, "output": out_acc, "interpolation": "LINEAR"}
                channel = {"sampler": 0, "target": {"node": node_idx_map[idx], "path": "translation"}}
                animations.append({"name": f"translation_{obj.name}", "samplers": [sampler], "channels": [channel]})

    if animations:
        gltf["animations"] = animations

    # Finalize buffer & write files
    buffer_uri = os.path.splitext(os.path.basename(out_gltf_path))[0] + ".bin"
    gltf["buffers"].append({"byteLength": len(buf.data), "uri": buffer_uri})
    gltf["bufferViews"] = buf.bufferViews
    gltf["accessors"] = buf.accessors

    # Write .gltf and .bin
    with open(out_gltf_path, 'w', encoding='utf-8') as f:
        json.dump(gltf, f, ensure_ascii=False, indent=2)
    with open(os.path.join(os.path.dirname(out_gltf_path), buffer_uri), 'wb') as f:
        f.write(buf.data)


def main():
    if len(sys.argv) < 3:
        print("Usage: python sting_json_to_gltf.py input.json output.gltf")
        sys.exit(1)
    inp, outp = sys.argv[1], sys.argv[2]
    objs = parse_input(inp)
    build_scene(objs, outp)
    print(f"Wrote {outp} and sibling .bin. Don't forget to place textures (if any) next to the .gltf by filename.")

if __name__ == "__main__":
    main()
