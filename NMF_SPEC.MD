# NMF File Format Specification

NMF ("Neo Model Format") is a chunk-based 3D scene format storing a hierarchy of
transform, locator, joint, and mesh nodes, with optional per-node and per-vertex
keyframe animation and per-triangle materials.

An NMF stream may appear as a standalone `.nmf` file, or embedded inside another
container format.

---

## 1. Conventions

| | |
| --- | --- |
| Integers | 32-bit, signed, little-endian, unless noted otherwise |
| Floats | IEEE-754, 32-bit, little-endian |
| `vec2` / `vec3` | 2 / 3 consecutive `float`s |
| `mat4` | 16 consecutive `float`s, row-major |
| `color4` | 4 consecutive `float`s, `(red, green, blue, alpha)` |
| `string` | Bytes up to and including a `0x00` terminator, `Windows-1252` encoded, then padded with additional `0x00` bytes so the total length (string + terminator + padding) is a multiple of 4 |

Every `mat4` is used in a row-vector, left-to-right composition convention (`v' = v · M`;
for a product of several matrices, the leftmost is applied first) - the same convention
Direct3D and Maya use. A consumer built around column-vector matrices (`v' = M · v`, e.g.
OpenGL/Blender) must transpose every `mat4` on read; a plain transpose is sufficient
(there is no separate row/column-order ambiguity beyond that - see the worked example in
§4's Remarks).

---

## 2. File Structure

```
File
    magic          char[4]     "NMF " (note trailing space)
    reserved       int32       0
    nodes          Node[]      sequence of nodes, terminated by end_marker
    end_marker     char[4]     "END " (note trailing space)
    reserved       int32       0
```

`nodes` is a flat list. The scene hierarchy is reconstructed from each node's `parent`
field (see `Node Header` below): a 1-based index into this list, or `0` for the root.

---

## 3. Node Header

Every entry in `nodes` begins with a common header:

```
Node
    type           char[4]     "ROOT", "LOCA", "FRAM", "JOIN", or "MESH"
    payload_size   uint32 (big-endian)   size, in bytes, of everything below this header
    version        int32       ROOT / FRAM / JOIN = 2, LOCA = 0, MESH = 14
    parent         int32       1-based index of the parent node in `nodes`; 0 for ROOT
    name           string
    payload        <node-type-specific data, see below>
```

`payload_size` covers only the bytes after the header itself (`version` through the end
of `payload`).

There is exactly one `ROOT` node per file, and it is always the scene root
(`parent == 0`). `FRAM`, `JOIN`, `LOCA` and `MESH` nodes may appear any number of times.

---

## 4. Transform Node (`ROOT`, `FRAM`)

`ROOT` and `FRAM` share an identical payload. A transform node positions itself and its
descendants in the scene.

```
TransformNode
    local_matrix              mat4
    translation                vec3
    scale                        vec3
    rotation                       vec3       Euler angles (X, Y, Z), radians
    rotate_pivot_translate            vec3
    rotate_pivot                        vec3
    scale_pivot_translate                  vec3
    scale_pivot                              vec3
    shear                                       vec3
    animation                                     Animation, optional (§7)
```

**Remarks**

- `local_matrix` and the `translation`/`rotation`/`scale`/pivot/`shear` fields are two
  parallel representations of the same transform and are not required to agree.
  - If `animation` is present, treat `translation`/`rotation`/`scale`/pivot/`shear` as
    authoritative.
  - If `animation` is absent, treat `local_matrix` as authoritative and decompose it
    directly; the TRS/pivot/shear fields may hold stale or default values.
- `translation`/`rotation`/`scale`/`rotate_pivot`/`rotate_pivot_translate`/
  `scale_pivot`/`scale_pivot_translate`/`shear` correspond one-to-one with a standard
  Maya transform node's `translate`/`rotate`/`scale`/`rotatePivot`/
  `rotatePivotTranslate`/`scalePivot`/`scalePivotTranslate`/`shear` attributes.
- Worked example confirming the row-vector convention above: for a non-animated `FRAM`
  with zero pivots/shear, `local_matrix`'s upper-left 3×3 equals
  `Diag(scale) · Rx(rotation.x) · Ry(rotation.y) · Rz(rotation.z)` (X applied first) using
  the standard row-vector rotation matrices, and `translation` sits verbatim in
  `local_matrix`'s last row - both confirmed numerically against real exported assets.
- **Coordinate system (`ROOT` only):** the engine is left-handed and Y-up (Direct3D's
  default). `ROOT.local_matrix` is *not* a ready-made conversion to any other convention -
  it is only that particular asset's own placement inside the engine's native, left-handed,
  Y-up scene, exactly like any other `TransformNode`'s `local_matrix`. A consumer that
  wants a right-handed, Z-up result (OpenGL/Blender) must apply one additional, fixed
  axis swap on top of `ROOT`'s own transform - e.g. `[[1,0,0,0],[0,0,1,0],[0,1,0,0],[0,0,0,1]]`
  (swap Y and Z) left-multiplied onto `ROOT`'s already-transposed (column-vector)
  `local_matrix` - applied once, at the scene root; every other node's `local_matrix`
  stays purely parent-relative and needs no further axis handling, since the swap
  cascades down through ordinary hierarchical composition. Skipping this swap (using
  `ROOT.local_matrix` verbatim) produces a scene that is both mirrored and lying on its
  side relative to a right-handed, Z-up viewer.

---

## 5. Locator Node (`LOCA`)

```
LocatorNode
    (no payload beyond the Node Header)
```

A named, transform-less attachment point in the hierarchy.

---

## 6. Joint Node (`JOIN`)

```
JointNode
    local_matrix           mat4
    translation              vec3
    scale                       vec3
    rotation                      vec3       Euler angles (X, Y, Z), radians
    joint_orient_matrix              mat4    rest-pose orientation
    rotation_limit_min                  vec3
    rotation_limit_max                     vec3
    animation                                 Animation, optional (§7)
```

**Remarks**

- Same `local_matrix`-vs-TRS reliability rule as the Transform Node (§4), with one
  addition specific to `JOIN`: **`joint_orient_matrix` only matters when `animation` is
  present.**
  - If `animation` is present: the final local orientation is
    `rotation × joint_orient_matrix`, with the (animated) `rotation` applied first and
    `joint_orient_matrix` applied outside/after it - confirmed by live-debugging the
    engine's own animated-joint evaluation code, which builds exactly this product
    (`animated_rotation_matrix × rotation_matrix`, the file's `joint_orient_matrix` as
    the right/outer operand) each time it samples a keyframed joint. It is not folded
    into `rotation`, `local_matrix`, or `animation`'s rotation curves.
  - If `animation` is absent: `local_matrix` is used verbatim (decomposed directly,
    exactly as for a non-animated Transform Node) and `joint_orient_matrix` is **not**
    applied at all, despite still being present in the file. This matches the engine's
    own behavior: the code path that composes `joint_orient_matrix` with a rotation only
    ever runs while sampling a keyframed animation curve; a non-animated joint's rest
    transform is read straight off `local_matrix`, which already has this baked in by
    the exporter, and `joint_orient_matrix` is simply never consulted for it. Applying it
    anyway double-counts a rotation that's already inside `local_matrix` - for joints
    whose `joint_orient_matrix` represents a large rotation (commonly ~90°, sometimes up
    to 180° in practice), this rotates the non-animated joint - and everything chained
    below it - roughly that far from its correct place.

---

## 7. Node Animation (`Animation`)

Embedded, optionally, in a `TransformNode` or `JointNode` payload. Provides keyframe
curves for up to 9 channels: the X, Y, and Z axes of `translation`, `rotation`, and
`scale`.

```
Animation
    marker         char[4]     "ANIM"
    interpolation  int32       0 = linear, 1 = eased (see below)
    key_counts     int32[9]    key count per channel, in order:
                                translation.x, translation.y, translation.z,
                                rotation.x,    rotation.y,    rotation.z,
                                scale.x,       scale.y,       scale.z
    curves         Curve[]     one entry for each channel above with a non-zero key
                                count, in the same order (channels with a zero key
                                count contribute no entry)
```

```
Curve
    times          float[key_count]     keyframe times, seconds
    values         float[key_count]     keyframe values
```

**Remarks**

- `interpolation` selects how a value is sampled between two keyframes: `0` samples
  linearly; `1` remaps the interpolation fraction through a sine ease curve before
  sampling (ease-in/ease-out).
- **How "optional" is actually encoded:** the `marker` field is always present - 4 bytes
  are always there, whether or not the node is animated. If those 4 bytes read `"ANIM"`,
  the rest of the `Animation` struct follows as documented above. If they don't (observed
  as 4 zero bytes in practice), there is no more animation data for this node; those 4
  bytes are a "no animation" sentinel and are still part of the payload byte count - a
  parser must consume them either way, never treat them as belonging to whatever comes
  after.
- A channel's raw keyframe values can contain a spurious ±360° (±2π) jump between two
  keyframes that doesn't correspond to real motion - e.g. two consecutive keys of `0.0`
  and `-360.0` degrees, meant to represent the same orientation (observed regularly
  across real assets: well over a hundred such jumps across a handful of sample files).
  Interpolating the raw values literally plays a full spurious spin instead of holding
  still. A consumer should normalize each channel so consecutive values differ by at
  most 180° (unwrapping through the shortest path) *unless* doing so would collapse an
  already-small, clearly-nonzero delta down to ~0° - that case is a genuine full turn
  (e.g. a continuously-spinning fan authored as a two-key 0° → 360° loop), not
  wraparound, and must be left as-is or the visible rotation is silently erased.

---

## 8. Mesh Node (`MESH`)

```
MeshNode
    triangle_count        int32
    vertex_count           int32
    vertices                  Vertex[vertex_count]
    source_uv                    vec2[vertex_count]
    index_count                     int32
    indices                            int16[index_count]
    pad                                  int16         present only if index_count is odd
    backface_culling                        int32
    complex                                    int32
    inside                                        int32
    smooth                                          int32
    light_flare                                        int32
    material_count                                        int32
    materials                                                Material[material_count]  (§10)
    vertex_animations                                            VertexAnimationClip[]  (§9)
                                                                  zero or more, chained
    collision_vertex_count                                          int32
    collision_vertices                                                  vec3[collision_vertex_count]
                                                                         present if collision_vertex_count > 0
    collision_index_count                                                  int32
    collision_indices                                                          int32[collision_index_count]
                                                                                present if collision_index_count > 0
```

```
Vertex
    position       vec3
    normal         vec3
    uv0            vec2     primary UV
    uv1            vec2     secondary UV
```

**Remarks**

- `indices[3*i .. 3*i+2]` is triangle `i`; `pad` exists only to keep the following field
  4-byte aligned.
- **`indices` values are *not* absolute indices into `vertices`.** Per §10, each
  material owns a contiguous block of both `vertices` (`vertex_offset`/`vertex_count`)
  and `indices` (`index_offset`/`index_count`). Within a given material's own index
  block, the stored index values are local to that material's own `vertex_offset` - the
  absolute vertex index is `indices[k] + material.vertex_offset` for whichever material
  owns the triangle containing `indices[k]`, not `indices[k]` on its own. This is only
  visible once a mesh has more than one material and a later material's `vertex_offset`
  is nonzero (the common single-material case has `vertex_offset == 0`, where local and
  absolute indices happen to coincide and the distinction is invisible) - confirmed
  against a real multi-material mesh, where a second material's raw index values (small,
  single-digit numbers) only form a sane, compact triangle fan once its own
  `vertex_offset` is added back; read as absolute, they instead point at unrelated
  vertices belonging to the mesh's first material.
- `backface_culling`, `complex`, `inside`, `smooth`, and `light_flare` are per-mesh
  render flags.
- `source_uv` holds each vertex's original, pre-atlas UV coordinates. `uv0` in
  `vertices` is the corresponding final UV already placed within its material's texture
  atlas sub-rectangle (see `Material.atlas_rect`, §10) - the two are related by a fixed
  2D affine transform (rotation from `Material.uv_rotation`, translation/scale from the
  atlas rectangle).
- `uv1` values lie in `[0, 1]`; within a single mesh they typically occupy a small,
  non-overlapping sub-rectangle of that range, consistent with a lightmap atlas UV.
- `vertex_animations` is a linked chain, not an array: after one `VertexAnimationClip`
  (or, if there are none, immediately after `materials`), the next 4 bytes are checked
  against `"ANIM"`; if they match, another clip follows immediately. If they don't
  (observed as 4 zero bytes in practice), the chain ends there - **those 4 bytes are a
  discarded terminator, not `collision_vertex_count`**: `collision_vertex_count` is a
  separate, freshly-read `int32` immediately following the terminator. (A literal
  reading of "otherwise those 4 bytes are `collision_vertex_count`" does not match real
  files - confirmed against a mesh with genuine, nonzero collision data, where treating
  the terminator as `collision_vertex_count` desyncs every field that follows it.)

---

## 9. Vertex Animation Clip (`VertexAnimationClip`)

Embedded, zero or more times (chained, see §8), in a `MeshNode` payload. Animates the
position of a named group of vertices.

```
VertexAnimationClip
    marker            char[4]        "ANIM"
    interpolation     int32          0 = linear, 1 = eased (see §7)
    vertex_count      int32
    vertex_indices    int32[vertex_count]     indices into the owning mesh's `vertices`
    rest_position     vec3                    reference rest position for this group
    key_counts        int32[3]                key counts for the X, Y, Z delta curves
    delta_curves      Curve[]                 one entry per axis (X, Y, Z) above with a
                                               non-zero key count, in the same order (§7
                                               for `Curve`)
```

**Remarks**

- `rest_position` should equal `vertices[vertex_indices[i]].position` for every index in
  `vertex_indices`.
- Each `delta_curves` value is *added* to `rest_position` (not an absolute replacement)
  to obtain the animated position at that time. A channel's first keyframe value is
  always `0.0`.

---

## 10. Material (`Material`)

```
Material
    marker              char[4]     "MTRL"
    name                string
    blend_mode          int32
    vertex_offset       int32       base vertex index of this material's block within
                                     the owning mesh's `vertices`
    vertex_count        int32       size of that block
    index_offset        int32       base index of this material's block within the
                                     owning mesh's `indices`
    index_count         int32       size of that block
    uv_flip_u           int32
    uv_flip_v           int32
    uv_rotation         int32
    uv_scale_u          float
    uv_scale_v          float
    diffuse             color4
    ambient             color4
    specular            color4
    emissive            color4
    specular_power      float
    texture             TextureReference (§11)
```

**Remarks**

- When a mesh has more than one material, its `vertices` and `indices` are partitioned
  into contiguous, non-overlapping blocks - one per material, described by that
  material's `vertex_offset`/`vertex_count` and `index_offset`/`index_count`.
- `diffuse`, `ambient`, `specular`, `emissive`, and `specular_power` together form a
  standard Phong/Blinn-Phong material (matching Direct3D's `D3DMATERIAL8`/
  `D3DMATERIAL9` layout). In practice `ambient` is always equal to `diffuse`, and
  `specular`/`emissive`/`specular_power` are usually all zero.
- When `texture` is present, the engine renders `diffuse × texture`, not the texture
  alone - `diffuse` is a live tint, not just a decomposed-material fallback for the
  untextured case. Some materials deliberately use a flat white/grey texture and rely
  entirely on `diffuse` for their actual in-game color; a consumer that wires the
  texture straight to a base-color input and ignores `diffuse` once a texture is present
  renders those materials as flat white/grey instead of their intended color.

---

## 11. Texture Reference (`TextureReference`)

```
TextureReference
    kind        char[4]     "TXPG", "TEXT", or 4 zero bytes

    // if kind == "TXPG" (texture-atlas page reference):
    name             string
    page             int32
    index_on_page    int32
    atlas_rect       int32[4]    (x0, y0, x2, y2)

    // if kind == "TEXT" (direct resource reference):
    name             string

    // if kind is 4 zero bytes: no further data (untextured material)
```

**Remarks**

- For `kind == "TXPG"`, the referenced texture page is conventionally stored on disk as
  `<page>.dds` in a `texture_pages` folder alongside the `.nmf` file (or its container);
  `name` is the *original* (pre-atlas) source path baked in by the exporter and is not
  needed to locate the page file at runtime.
- Every sampled `texture_pages/*.dds` file observed in practice (hundreds, across
  several unrelated assets) uses the same simple, uncompressed pixel format: 16
  bits/pixel, no `FourCC` (i.e. not DXT/BC-compressed), 5-5-5 RGB with either no alpha
  channel or a 1-bit alpha (`A` mask `0x8000`), no mipmaps. Row 0 of the pixel data is
  the texture's top row (standard DDS/Direct3D convention), consistent with `uv0`/`uv1`
  also being authored with `V=0` at the top of the page - a consumer that keeps both
  conventions as-is (no row flip, no V flip) samples correctly; the mismatch only
  arises if just one side gets normalized to a different convention (e.g. via an
  intermediate PNG re-export, which is always top-row-first regardless of the pixel
  format, but is commonly consumed as `V=0`-at-bottom).
