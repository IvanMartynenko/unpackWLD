#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

"""
Der Clou! 2 (The Sting! / Ва-Банк!) NMF to FBX Converter

Converts extracted NMF models directly into binary FBX (version 7500),
including a standalone binary FBX writer, so no FBX SDK is required. Handles
geometry, skeletal hierarchy, materials/textures and animation.

Usage:
    python nmf_to_fbx.py <input.nmf> <output.fbx>

Pipeline (see `main`) is three stages, one class each:

    raw NMF nodes
        -> NmfSceneConverter.convert()   # no FBX knowledge at all
    processed node list
        -> FbxSceneAssembler.assemble()  # builds the FBX object/property DSL
    nested-list FBX structure
        -> FbxBinaryWriter.write()       # pure binary encoding, no NMF/scene
                                          # knowledge
    .fbx file

The "DSL" each `[name, values, type_codes, children]` list node uses is
documented on `FbxBinaryWriter`. Every stateless helper (matrix/vector math,
FBX property-list builders, ...) is a `@staticmethod` on whichever of the
three stage classes actually uses it, rather than a bare module-level
function - only small immutable constants (FPS, type codes, fixed IDs, ...)
and the two small standalone data-holder classes (`FBXElem`, `TransformFold`)
live at module scope.

Coordinate systems: the source engine is DirectX-based (row-major matrices).
`NmfSceneConverter._dx_to_blender_matrix` transposes into the row/column
convention this file's math expects; the DirectX-Y-up to Blender/FBX-Z-up
axis swap is applied exactly once, at the scene ROOT (see
`NmfSceneConverter._convert_root_node`) - every other node's matrix stays in
its own parent-relative local space and the swap cascades down through
ordinary hierarchical transform composition.

Non-obvious fixes worth knowing before touching this file (each was found by
comparing against real extracted assets - see the docstring/comment at its
definition for the full story):

1. Textures are referenced as plain PNG pages
   (`NmfSceneConverter._resolve_material_texture`); there is no DDS/atlas-
   cropping step.
2. `NmfSceneConverter._build_fbx_uv_layer` flips V (`1.0 - v`): the source
   bakes DirectX-style V (0 = top of the page); FBX/OpenGL-style consumers
   read V as 0 = bottom. Without the flip, sampled rects land mirrored
   vertically.
3. A material's own baked UV (vbuf columns 6/7) is already an absolute
   coordinate on the *whole* shared texture page - verified against every
   material's real placement in the `.wld` texture-page manifest. No extra
   per-material offset/scale is derived from the MTRL's box fields; doing so
   re-applies a placement the exporter already baked in.
4. For the same reason, `uv_mapping_flip_horizontal/vertical` are read but
   deliberately NOT turned into a `ModelUVScaling` sign flip - the flip is
   already baked into the UV values themselves. Re-applying it as a second
   sign flip un-does the V-flip fix above for exactly the materials where it
   would matter.
5. `TransparentColor` is only wired to a material's texture when
   `blend_mode` is alpha/additive (1/2). Wiring it unconditionally makes
   FBX importers treat every textured (even fully opaque) material as
   alpha-blended, which looks "see-through" wherever opaque mesh pieces
   overlap (EEVEE's alpha-blend depth sorting).
6. `NmfSceneConverter._unwrap_degrees` removes spurious +/-360 jumps from
   animated rotation keyframes (each axis is an independent angle sequence,
   not a shared quaternion) so consecutive keys differ by at most 180 -
   otherwise a real small rotation through the 180 boundary (e.g. 170 ->
   -170, an actual 20 degree step) gets interpolated the long way around.
7. `InheritType` is written as 0 (RrSs / plain hierarchical composition),
   not FBX's default of 1 (RSrs / Maya joint-chain scale compensation).
   This engine's hierarchy is baked DirectX matrices, not Maya joints;
   InheritType 1 silently distorts deeper nodes in a chain, worse the
   deeper they are.
8. `NmfSceneConverter._compute_transform_folds` bakes non-animated
   FRAM/JOIN chains (however they branch) into descendant mesh
   vertices/normals instead of decomposing their matrix into
   Translation/Rotation/Scale. FBX's Model transform cannot represent
   shear, and close to a gimbal-lock angle even a tiny amount of shear gets
   amplified into a wildly wrong rotation/scale by the decomposition -
   geometry has no such limitation.
9. `NmfSceneConverter._is_mesh_right_handed` is checked exactly once per
   mesh, before per-material vertex index shifting - checking it again
   afterwards (on already-shifted indices) can flip winding a second time
   for meshes with multiple materials.
10. The same source texture page is frequently shared by many materials
    (e.g. a whole character's skin) -
    `FbxSceneAssembler._get_or_create_video` embeds its PNG bytes into the
    FBX once and lets every Texture object reference the same Video, rather
    than re-reading/re-embedding per material.
11. A material's `DiffuseColor` is only a *live* value when the material
    has no texture. Once textured, the plain FBX pattern this file emits
    (Texture -> `DiffuseColor` via a direct `OP` connection, no multiply/
    `LayeredTexture` node - that construct doesn't exist here) makes
    importers - Blender included - just show the texture's own pixels and
    silently drop the static color, even though the game itself renders
    `diffuse_color * texture` (this is why some materials use a plain
    white/grey texture and rely entirely on that color for their actual
    look - correct in-game, flat white in Blender). Since there's no
    portable way to express that multiply as a connection graph without a
    real shader-node FBX extension, `FbxSceneAssembler._resolve_tinted_texture_path`
    bakes the color into a cached per-(page, color) copy of the PNG instead
    (skipped when the color is ~white, a no-op) and the material's
    `DiffuseColor` is then written as white so a smarter importer that DOES
    respect it won't double-apply the tint.
12. An animated FRAM's `RotationPivot`/`RotationOffset`/`ScalingPivot`/
    `ScalingOffset` (its Maya-style pivot, e.g. a door's hinge point) are
    real and correctly read, but most FBX importers - Blender included -
    only honor those Model properties for the *static* pose; once Rotation
    is a keyframed curve they ignore the pivot and spin the node around its
    own local origin instead (JOIN doesn't hit this because its own static
    component, `PreRotation`, is a pure orientation with no pivot *point*
    to lose). `NmfSceneConverter._split_fram_pivot_chain` sidesteps this by
    algebraically re-grouping the same pivot formula into a short chain of
    plain Translation/Rotation/Scaling nodes instead - exact, not an
    approximation, and reuses the original Rotation/Scaling keyframes
    verbatim (only Translation gets a constant shift), at the cost of
    inserting up to 2 extra Null nodes per pivoted FRAM. Verified exact via
    `ufbx_evaluate_scene` every time it's been re-checked, but the actual
    target (Blender) has repeatedly shown wrong-looking results anyway -
    see gotchas #14/#15/#16 for what's been tried against it so far, and
    gotcha #17 for the debug tooling now in place to keep chasing it. A
    single-node "bake the pivot into a synthesized Translation curve on the
    same node" alternative (no extra nodes at all) was tried and reverted -
    it turned out to compute genuinely wrong transforms, not just an
    importer-compatibility mismatch, so this split-chain approach is back
    to being the only verified-correct implementation and is what gotcha
    #17's debug instrumentation targets.
13. A continuously-spinning part (fan, propeller, radar dish, rotating
    light cone, ...) is commonly authored as just 2 rotation keyframes, 0 ->
    360 degrees (one full loop, meant to be played on repeat) - which looks
    identical, as a raw delta, to the spurious +/-360 storage wraparound
    gotcha #6's `_unwrap_degrees` exists to fix, except collapsing a genuine
    whole turn via the same shortest-path correction lands on ~0 degrees
    instead of a small residual, silently erasing all visible rotation (the
    reported symptom was "the fan doesn't spin"). `_unwrap_degrees` now only
    applies that correction when it leaves a non-trivial angle; a clearly
    non-zero raw delta that would collapse to ~0 is kept as-is instead.
    That alone wasn't sufficient: a keyframe pair whose start/end angles
    describe the same final orientation (0 and 360 are the same pose) plays
    no motion in at least one real FBX consumer regardless of the literal
    stored numbers - it resolves rotation by the pose at each key, not the
    raw value, and a 2-key "loop" has no genuinely distinct pose to
    interpolate towards. `NmfSceneConverter._subdivide_wide_rotation_segments`
    fixes this the rest of the way by inserting intermediate keyframes into
    any >= ~180 degree segment, so a 0->360 turn becomes e.g. 0->180->360 -
    a genuinely distinct intermediate pose that can't be collapsed away.
14. `FbxSceneAssembler._build_animation_data` used to name every
    AnimCurveNode/AnimationCurve object with a fixed, non-unique string
    ("R::AnimCurveNode", "::AnimCurve", ...) - the same literal name reused
    for the same kind of curve on every single animated node in the file.
    IDs (not names) are what FBX's own Connections graph resolves by, so
    this looked harmless, but Blender's FBX importer apparently keys some
    of its own per-object animation reconstruction off these names
    internally: with gotcha #12 splitting one animated FRAM into an
    `outer`/`middle` pair (e.g. `group3` for Rotation, `group3_scalePivot`
    for Scaling) sitting right next to each other in the hierarchy,
    Blender ended up attaching the wrong Action to the wrong object -
    `group3`'s own Rotation curve simply didn't show up on `group3` at
    all, while `group3_scalePivot` displayed an (unrelated) Action instead
    (confirmed via a screenshot of Blender's Outliner, even though
    `ufbx_evaluate_scene` proved `group3`'s Rotation curve itself decodes
    and evaluates correctly). Every curve node/curve is now named after
    its owning Model plus property/axis (e.g. "group3_R::AnimCurveNode",
    "group3_scalePivot_SX::AnimCurve"), matching the uniqueness this file
    already relies on for Model/Material names elsewhere. Renaming alone
    did not fix the report - see gotcha #15.
15. `RotationActive=1` was being written on *every* "fram" Model
    unconditionally, including gotcha #12's pivot-split outer/middle/inner
    nodes, even though those carry no RotationOffset/RotationPivot/
    ScalingOffset/ScalingPivot at all (RotationActive only means anything
    alongside at least one of those). Setting it with no actual pivot
    property behind it likely routes an importer through its "decode the
    full Maya pivot chain" path regardless, which for a chain of adjacent,
    pivot-less split nodes is presumably where gotcha #14's
    misattributed-Action symptom actually came from (confirmed the rename
    in #14 alone did not fix it). `_build_model_transform_props` now only
    writes `RotationActive` when a pivot property was actually written
    alongside it - plain nodes (including every gotcha #12 split segment)
    get the same bare Translation/Rotation/Scaling any ordinary FBX Model
    would. Still didn't fix the report.
16. A degenerate single-keyframe track (one time, one value - e.g. a
    "scale" track authored as a single `1.0` sample by whatever tool
    exported the source NMF) carries no actual motion, so an earlier fix
    here dropped any axis whose track had fewer than 2 keys instead of
    emitting a pointless 1-key curve for it. Reverted by gotcha #18: it
    turns out Blender's importer needs that axis present (padded to 2 keys,
    not dropped) for an unrelated reason - see #18.
17. Debug instrumentation, added while chasing gotcha #12's Blender report
    (see gotcha #18 for the actual fix that came out of using it): run with
    `--debug` (see `main`) to have `debug_output` actually print (to
    stderr) instead of being a no-op. This turns on `[pivot]` logging in
    `_split_fram_pivot_chain` (the pivot values read off each animated
    FRAM and the resulting outer/middle/inner chain, per node), `[wire]`
    logging in `NmfSceneConverter.convert` (the final id/parent_id/
    with_animation actually assigned to each chain segment once ids are
    resolved), `[curve]` logging in
    `FbxSceneAssembler._build_animation_data` (which AnimCurveNode ends up
    OP-connected to which Model id/name, for which property), and
    `[curve-pad]` logging in
    `NmfSceneConverter._animation_build_tracks_by_axis` (see gotcha #18).
18. Root-caused gotcha #12's Blender report by direct experiment (not
    inspection - editing the intermediate JSON and re-testing in Blender):
    Blender's FBX importer silently drops an ENTIRE AnimCurveNode unless
    its "d|X" channel specifically has >= 2 keyframes - confirmed by moving
    the only real keyframes from d|Z to d|X (animation appeared, wrong
    axis but present), to d|Y (nothing), and by padding a real d|Z curve
    with a 2-key constant d|X curve alongside it (animation appeared,
    correct axis) vs. a 1-key d|X curve (still nothing). This explains
    every earlier symptom in one shot: `group3`'s Rotation-only curve
    (d|Z only, no d|X at all) was silently dropped in its entirety, while
    `_scalePivot`'s old single-key-but-all-3-axes Scaling curve (gotcha
    #16, before it was dropped) at least had *a* d|X channel and partially
    showed up. `_animation_build_tracks_by_axis` now pads every axis of
    every track to >= 2 keys - a shared time span borrowed from whichever
    real multi-key axis exists on the node, constant-value keys for any
    axis that's genuinely never animated - instead of gotcha #16's leaving
    gaps (reverted) or omitting axes with no data at all.
19. A continuously-spinning part (gotcha #13) still visibly reversed
    direction after gotcha #18 - root-caused, again by direct experiment,
    to Blender's FBX importer normalizing each rotation keyframe's Euler
    value into (-180, 180] INDEPENDENTLY, with no continuity correction
    against neighbouring keys: literal continuous values like 240/360
    silently become -120/-0 on import (confirmed: the reported "180
    degrees, then back, then back again" matches interpolating between
    those *displaced* numbers exactly). Since Blender re-derives its own
    wrapped copy regardless of what's sent, every stored value has to
    already fit in that range. `NmfSceneConverter._wrap_rotation_into_range`
    re-expresses the curve as a "sawtooth": whenever it would cross +-180,
    it inserts the exact crossing point followed, `_ROTATION_WRAP_STEP_FRAMES`
    later (a thousandth of a frame), by the same true angle's equivalent on
    the other side - real playback only ever samples whole/half frames, so
    it can't land inside a gap that small. That alone still weakly
    distorted the curve well before each crossing, because FBX's
    "auto" cubic tangent formula (confirmed against ufbx's own source) is
    the straight chord between a key's PREVIOUS and NEXT neighbours,
    ignoring the key's own value - a neighbour 0.001 frames away produces
    a huge, wrong-sign slope. `_build_animation_data` now writes any axis
    that went through a wrap using LINEAR interpolation instead of cubic
    (no tangent computation to go wrong), leaving cubic easing untouched
    for every other rotation axis (e.g. a door hinge's few widely-spaced,
    never-wrapped keys).
20. A multi-axis animated FRAM with an asymmetric pivot (RotationPivot !=
    ScalingPivot) reported a specific, narrower symptom than any of
    #14-#19: rotating around the correct axis/point but in the wrong
    direction. Both gotcha #12's pivot algebra (the true fixed point
    verified constant via `node_to_world`, once corrected to check
    ScalingPivot rather than RotationPivot when scale isn't identity -
    they only coincide when scale is 1:1) and gotcha #19's wrap-into-range
    (the unwrapped trajectory verified continuous and correctly-signed for
    a *decreasing* rotation, the first real case of one) checked out
    correct in isolation, including recombined compound X+Y+Z. A first
    attempt at fixing this by splitting the rotation itself across 3
    single-axis nodes (RotateZ->RotateY->RotateX, to rule out Blender's
    own compound-Euler-order handling) was reverted in favor of
    `_split_fram_pivot_chain`'s current form: one node per raw pivot field
    (RotationOffset/RotationPivot/ScalingOffset/ScalingPivot) instead of
    gotcha #12's algebraic Roff+Rp / Sp+Soff-Rp re-grouping - mathematically
    equivalent (verified by hand, same target formula, just not re-grouped
    down to 3 nodes), tried as a different angle on the same still-open
    wrong-direction report.
21. Refined gotcha #20's report: with `_wrap_rotation_into_range` active,
    the symptom wasn't a simple wrong-direction spin anymore but an
    unpredictable tumble pulling in axes that barely move on their own
    (e.g. an X/Y that only drift a couple of degrees end to end). Likely
    cause: a node with several rotation axes genuinely animated together
    had gotcha #19's LINEAR interpolation on only the one axis that
    crossed +-180, leaving the others on CUBIC - inconsistent
    interpolation across axes of the *same* compound rotation.
    `_animation_build_tracks_by_axis` now forces every axis of a node's
    rotation to LINEAR as soon as any one of them needed the wrap, instead
    of leaving that per-axis.
22. Gotcha #21 alone still didn't fix it - root-caused by dumping the
    actual imported F-curve keyframes from Blender's own Python console
    (`obj.animation_data.action...fcurves`; Blender 4.4+ moved these
    behind a layers/strips/channelbags structure instead of a flat
    `action.fcurves` - see the `iter_fcurves` fallback wherever this gets
    re-checked). Confirmed exactly: when a node's rotation axes don't all
    share the same keyframe *times* (gotcha #19's wrap adds extra points
    to whichever axis crosses +-180; the others keep their original 2),
    Blender's importer resamples the missing axes itself by round-
    tripping through a rotation matrix/quaternion and re-decomposing back
    to XYZ Euler - and picks the decomposition branch independently at
    each new sample, with no continuity check against the curve's own
    other keys. At the wrap-crossing frame, Blender's own resampled X/Y/Z
    came back as (rx+180, 180-ry, rz+180) - the other mathematically-
    equivalent Euler branch - while the original endpoint keys stayed on
    the direct branch; both encode the same rotation individually, but
    interpolating from a direct-branch key to a flipped-branch one traces
    a completely wrong path (reported as "rotates however, tumbles
    through other axes too"). Fix: give Blender nothing to resample -
    `_animation_build_tracks_by_axis` now forces every rotation axis of a
    wrapped node onto the exact same set of keyframe times (the union of
    all of them), filling any point an axis didn't already have via plain
    linear interpolation (`_interp_linear`) of its own already-correct
    curve.
23. Gotcha #22 alone still didn't fix it - confirmed by rebuilding and
    re-dumping Blender's own imported F-curve keyframes a second time:
    identical (still-flipped) numbers came back even though the file now
    supplied every axis with matching, already-correct keyframe times at
    the wrap crossing. Conclusion: Blender's FBX importer round-trips a
    multi-axis "Lcl Rotation" curve through a rotation matrix/quaternion
    on import regardless of what per-key values are supplied, and
    re-decomposes it back to XYZ Euler using its own branch choice - so no
    amount of pre-computing "correct" values can win against that
    re-decomposition. `_build_rotation_axis_nodes` (originally gotcha
    #20, reverted at the time in favor of gotcha #12's per-pivot-field
    split) is back, layered on top of that same per-pivot-field chain:
    once a node's rotation involves more than one genuinely-animated
    axis, it's split into 3 chained single-axis nodes instead of staying
    on one compound curve. A single-axis rotation has no Euler-branch
    ambiguity to begin with, so there's nothing left for Blender's
    importer to reprocess differently.
24. An animated FRAM with a non-zero RotationOffset (`rotate_pivot_
    translate`) whose own translation is *also* animated (not just the
    pivot/rotation) came out positioned wrong relative to its
    non-animated siblings, even though the rotation itself played back
    correctly. `_split_fram_pivot_chain`'s `outer` node's *static*
    default (`translation` Model property) was correctly `T + Roff`, but
    once translation is animated, FBX/Blender use only the connected
    "Lcl Translation" curve's own values at every keyframe - the static
    default becomes a pure fallback that's never consulted - and that
    curve was built straight from the raw NMF `translation` animation
    channel (`T` alone), never adding `Roff`. See
    `NmfSceneConverter._offset_translation_track` for the fix (add
    `rotate_pivot_translate` onto every keyframe of the outer node's own
    translation curve, not just its static default) and its docstring
    for the exact evidence trail (ufbx-evaluated curve values matched the
    raw NMF channel exactly; the static default matched `Roff` alone).
25. `MESH_ANIM` blocks (per-vertex keyframed position deltas, parsed by
    `common/nmf_parser.py` into each MESH node's `payload["vertex_animations"]`,
    format documented in `docs/NMF_SPEC.md`) were previously parsed but
    never consumed - `_convert_mesh_node` ignored them entirely. Reverse-
    engineered from real assets (window flaps, a breaking crate, an
    elephant's skin, machine vibration, water ripples - see
    `NmfSceneConverter._build_mesh_vertex_animations` for the field-by-
    field evidence): each clip names one or more vertex indices
    (`vertex_indices`) sharing a base/rest position (`rest_position`,
    matches `vertices[idx][0:3]` almost always - see that method for the
    "water" files' small exception) and up to 3 independent per-axis
    delta curves (`key_count_x..z` + `delta_x..z`, same times/values
    layout as FRAM/JOIN's own animation axis curves) that are *added* to
    the base position, not absolute replacements - every animated axis's
    first keyframe value is 0.0, matching the rest pose. `interpolation`'s
    purpose was confirmed via the game's own runtime loader (see
    `docs/GHIDRA_FINDINGS.md`): it's a linear-vs-eased (sine-curve)
    keyframe-interpolation toggle, applied per-axis-curve when sampling
    `delta_x..z` - consistent with it
    being seen 0 (linear) almost always and 1 (eased) on some
    very-small-amplitude machine-vibration clips, where smoothed motion
    reads better than a jerky linear ramp. Still deliberately not used by
    this implementation (FBX's own curve tangent settings are a separate,
    lower-priority concern than getting the keyframe values themselves
    right).
    Represented in FBX as one `BlendShapeChannel` per animated
    (vertex-group, axis) pair (`FbxSceneAssembler.
    _build_mesh_blendshape_data`), each with a unit-delta `Shape` target
    and a `DeformPercent` curve - axes are independent and not
    proportional to each other (verified on the elephant asset), so a
    single blend channel per vertex group cannot represent them. See
    gotcha #26 for why the weight curve is *not* simply the raw delta
    values * 100, despite that being what a literal FBX/Maya scalar
    multiplier would suggest.
26. Gotcha #25's `BlendShapeChannel` weights were originally the raw
    per-axis delta values * 100 directly (a signed, unbounded percentage
    - normal for FBX/Maya, where blend shape weight is just a scalar
    multiplier). Blender's FBX importer disagreed: it defaults every
    imported shape key's `slider_min`/`slider_max` to 0/1 and - unlike
    plain `FCurve.evaluate()`, which is unaffected - actually clamps the
    shape key's real `value` property to that range once the driving
    animation is applied, silently discarding any negative or >100%
    weight before it ever reaches the mesh. Found by comparing a broken
    asset's (`Maschine4x4_2621`, part `pPlaneShape227`) own F-curve
    evaluation (correct) against its shape key's actual `value` at the
    same frame (stuck at 0.0) in the user's own Blender console, then
    confirming the clamp directly (widening `slider_min` to -10 and
    assigning the value by hand immediately fixed it).
    `_build_mesh_vertex_animations` now never emits a channel whose
    weight needs to leave [0, 1]: each axis's curve is split into up to
    two channels - one for its positive-going part, one for its
    negative-going part - each normalized against its own peak magnitude
    (which also fixes swings past 100%, e.g. the crate's -10.68 spike),
    with the corresponding `Shape` target's delta scaled by that same
    peak so `weight(t) * scaled_delta` reconstructs the exact original
    signed displacement at every keyframe.
27. `ANIM`/`MESH_ANIM`'s `interpolation` flag (see `docs/GHIDRA_FINDINGS.md`)
    selects the engine's own eased keyframe interpolation - a cosine
    ease-in-out, `(1 - cos(pi*t)) / 2`, confirmed from the exact float
    constants read out of `VaBank.exe`'s `.rdata` - instead of plain
    linear. This was assumed to be a rare edge case (gotcha #25's own
    write-up called it "seen almost always 0") until actually checked
    against the full asset set: it's set on 77% of `ANIM` blocks
    (999/1304) and 51% of `MESH_ANIM` clips (335/651) - the majority
    case, not an outlier. Neither FBX's nor glTF's animation-curve
    formats have a native "cosine ease between exactly these two keys"
    curve type, so `NmfSceneConverter._apply_ease_supersampling` bakes
    it by inserting `_EASE_SAMPLES_PER_SEGMENT` extra, densely-eased
    intermediate keyframes along each real segment - the same
    supersample-instead-of-relying-on-the-target-format's-own-curve-type
    approach `_subdivide_wide_rotation_segments` (gotcha #19) already
    uses for a different curve-shape problem - so plain linear playback
    on the FBX/glTF side reproduces the eased motion closely without
    needing a new interpolation mode.

License: MIT License
"""

import sys, os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import array
import time
import zlib
from struct import pack, unpack, error as struct_error

import numpy as np

from common import Nmf
import nmf_scene_converter
from nmf_scene_converter import NmfSceneConverter, FPS

# =============================================================================
# Section 1: Binary FBX writer building blocks (low-level; no NMF knowledge)
# =============================================================================
#
# FBX objects/properties are described throughout this file as plain nested
# lists: `[name, values, type_codes, children]`, where `type_codes` is a
# string with one letter per entry in `values` (see the type table below).
# `FbxBinaryWriter` walks that shape and turns it into a tree of `FBXElem`,
# then serializes it to the actual binary format. This indirection exists
# purely so the rest of the file can describe FBX objects as data instead of
# hand-calling `FBXElem` methods everywhere.

# Property type codes (single value)
BOOL = b"B"[0]
CHAR = b"C"[0]
INT8 = b"Z"[0]
INT16 = b"Y"[0]
INT32 = b"I"[0]
INT64 = b"L"[0]
FLOAT32 = b"F"[0]
FLOAT64 = b"D"[0]
BYTES = b"R"[0]
STRING = b"S"[0]
# Property type codes (array value)
INT32_ARRAY = b"i"[0]
INT64_ARRAY = b"l"[0]
FLOAT32_ARRAY = b"f"[0]
FLOAT64_ARRAY = b"d"[0]
BOOL_ARRAY = b"b"[0]
BYTE_ARRAY = b"c"[0]

# `array` module type codes, resolved to whichever letter gives the right
# item size on this platform/Python build.
ARRAY_BOOL = "b"
ARRAY_BYTE = "B"
ARRAY_INT32 = None
ARRAY_INT64 = None
for _t in "ilq":
    size = array.array(_t).itemsize
    if size == 4:
        ARRAY_INT32 = _t
    elif size == 8:
        ARRAY_INT64 = _t
    if ARRAY_INT32 and ARRAY_INT64:
        break

ARRAY_FLOAT32 = None
ARRAY_FLOAT64 = None
for _t in "fd":
    size = array.array(_t).itemsize
    if size == 4:
        ARRAY_FLOAT32 = _t
    elif size == 8:
        ARRAY_FLOAT64 = _t
    if ARRAY_FLOAT32 and ARRAY_FLOAT64:
        break

if not (ARRAY_INT32 and ARRAY_INT64 and ARRAY_FLOAT32 and ARRAY_FLOAT64):
    raise Exception("Impossible to determine array types for current architecture.")

# Filled in by `FbxBinaryWriter._init_version()` once the target FBX version
# is known (7500+ uses 64-bit element offsets/counts; older versions use
# 32-bit).
_BLOCK_SENTINEL_LENGTH = ...
_BLOCK_SENTINEL_DATA = ...
_ELEM_META_FORMAT = ...
_ELEM_META_SIZE = ...
_IS_BIG_ENDIAN = sys.byteorder != "little"
_HEAD_MAGIC = b"Kaydara FBX Binary\x20\x20\x00\x1a\x00"

# Fixed IDs, applied by `FbxBinaryWriter._write_timedate_hack` so re-running
# the converter on the same input produces byte-identical output (see its
# docstring).
_TIME_ID = b"1970-01-01 10:00:00:000"
_FILE_ID = b"\x28\xb3\x2a\xeb\xb6\x24\xcc\xc2\xbf\xc8\xb0\x2a\xa9\x2b\xfc\xf1"
_FOOT_ID = b"\xfa\xbc\xab\x09\xd0\xc8\xd4\x66\xb1\x76\xfb\x83\x1c\xf7\x26\x7e"

# Elements that must always be terminated with a block sentinel even when
# empty - matches what real FBX SDK output does for these specific types.
_ELEMS_ID_ALWAYS_BLOCK_SENTINEL = {
    b"AnimationStack",
    b"AnimationLayer",
    b"Properties70",
    b"PropertyTemplate",
    b"References",
    b"Definitions",
    b"ObjectType",
    b"MetaData",
}

# Toggled by the `--debug` CLI flag (see `main`); also gates the extra
# `[pivot]`/`[wire]` logging in `NmfSceneConverter._split_fram_pivot_chain`/
# `convert` and the `[curve]` logging in
# `FbxSceneAssembler._build_animation_data`.
DEBUG = False


def debug_output(data):
    if DEBUG:
        print(data, file=sys.stderr)


class FBXElem:
    """One node in the binary FBX element tree: an id, a flat list of typed
    properties, and child elements. Built and consumed by `FbxBinaryWriter`."""

    __slots__ = ("id", "props", "props_type", "elems", "_props_length", "_end_offset")

    def __init__(self, id):
        assert len(id) < 256
        self.id = id
        self.props = []
        self.props_type = bytearray()
        self.elems = []
        self._end_offset = -1
        self._props_length = -1

    def add_bool(self, data):
        self.props_type.append(BOOL)
        self.props.append(pack("?", data))

    def add_char(self, data):
        self.props_type.append(CHAR)
        self.props.append(pack("<c", data))

    def add_int8(self, data):
        self.props_type.append(INT8)
        self.props.append(pack("<b", data))

    def add_int16(self, data):
        self.props_type.append(INT16)
        self.props.append(pack("<h", data))

    def add_int32(self, data):
        self.props_type.append(INT32)
        self.props.append(pack("<i", data))

    def add_int64(self, data):
        self.props_type.append(INT64)
        self.props.append(pack("<q", data))

    def add_float32(self, data):
        self.props_type.append(FLOAT32)
        self.props.append(pack("<f", data))

    def add_float64(self, data):
        self.props_type.append(FLOAT64)
        self.props.append(pack("<d", data))

    def add_bytes(self, data):
        self.props_type.append(BYTES)
        self.props.append(pack("<I", len(data)) + data)

    def add_string(self, data):
        self.props_type.append(STRING)
        self.props.append(pack("<I", len(data)) + data)

    def _add_array_helper(self, data, prop_type, length):
        self.props_type.append(prop_type)
        data = pack("<3I", length, 0, len(data)) + data
        self.props.append(data)

    def _add_parray_helper(self, data, array_type, prop_type):
        length = len(data)
        if _IS_BIG_ENDIAN:
            data = data[:]
            data.byteswap()
        self._add_array_helper(data.tobytes(), prop_type, length)

    def _add_ndarray_helper(self, data, dtype, prop_type):
        length = data.size
        if _IS_BIG_ENDIAN and data.dtype.isnative:
            data = data.byteswap()
        self._add_array_helper(data.tobytes(), prop_type, length)

    def add_int32_array(self, data):
        if isinstance(data, np.ndarray):
            self._add_ndarray_helper(data, np.int32, INT32_ARRAY)
        else:
            self._add_parray_helper(
                (
                    array.array(ARRAY_INT32, data)
                    if not isinstance(data, array.array)
                    else data
                ),
                ARRAY_INT32,
                INT32_ARRAY,
            )

    def add_int64_array(self, data):
        if isinstance(data, np.ndarray):
            self._add_ndarray_helper(data, np.int64, INT64_ARRAY)
        else:
            self._add_parray_helper(
                (
                    array.array(ARRAY_INT64, data)
                    if not isinstance(data, array.array)
                    else data
                ),
                ARRAY_INT64,
                INT64_ARRAY,
            )

    def add_float32_array(self, data):
        if isinstance(data, np.ndarray):
            self._add_ndarray_helper(data, np.float32, FLOAT32_ARRAY)
        else:
            self._add_parray_helper(
                (
                    array.array(ARRAY_FLOAT32, data)
                    if not isinstance(data, array.array)
                    else data
                ),
                ARRAY_FLOAT32,
                FLOAT32_ARRAY,
            )

    def add_float64_array(self, data):
        if isinstance(data, np.ndarray):
            self._add_ndarray_helper(data, np.float64, FLOAT64_ARRAY)
        else:
            self._add_parray_helper(
                (
                    array.array(ARRAY_FLOAT64, data)
                    if not isinstance(data, array.array)
                    else data
                ),
                ARRAY_FLOAT64,
                FLOAT64_ARRAY,
            )

    def add_bool_array(self, data):
        if isinstance(data, np.ndarray):
            self._add_ndarray_helper(data, bool, BOOL_ARRAY)
        else:
            self._add_parray_helper(
                (
                    array.array(ARRAY_BOOL, data)
                    if not isinstance(data, array.array)
                    else data
                ),
                ARRAY_BOOL,
                BOOL_ARRAY,
            )

    def add_byte_array(self, data):
        if isinstance(data, np.ndarray):
            self._add_ndarray_helper(data, np.byte, BYTE_ARRAY)
        else:
            self._add_parray_helper(
                (
                    array.array(ARRAY_BYTE, data)
                    if not isinstance(data, array.array)
                    else data
                ),
                ARRAY_BYTE,
                BYTE_ARRAY,
            )

    def _calc_offsets(self, offset, is_last):
        assert self._end_offset == -1
        offset += _ELEM_META_SIZE + 1 + len(self.id)
        props_length = 0
        for data in self.props:
            props_length += 1 + len(data)
        self._props_length = props_length
        offset += props_length
        return self._calc_offsets_children(offset, is_last)

    def _calc_offsets_children(self, offset, is_last):
        if self.elems:
            elem_last = self.elems[-1]
            for elem in self.elems:
                offset = elem._calc_offsets(offset, (elem is elem_last))
            offset += _BLOCK_SENTINEL_LENGTH
        elif (
            not self.props and not is_last
        ) or self.id in _ELEMS_ID_ALWAYS_BLOCK_SENTINEL:
            offset += _BLOCK_SENTINEL_LENGTH
        self._end_offset = offset
        return offset

    def _write(self, write, tell, is_last):
        write(
            pack(
                _ELEM_META_FORMAT, self._end_offset, len(self.props), self._props_length
            )
        )
        write(bytes((len(self.id),)))
        write(self.id)
        for i, data in enumerate(self.props):
            write(bytes((self.props_type[i],)))
            write(data)
        self._write_children(write, tell, is_last)

    def _write_children(self, write, tell, is_last):
        if self.elems:
            elem_last = self.elems[-1]
            for elem in self.elems:
                elem._write(write, tell, (elem is elem_last))
            write(_BLOCK_SENTINEL_DATA)
        elif (
            not self.props and not is_last
        ) or self.id in _ELEMS_ID_ALWAYS_BLOCK_SENTINEL:
            write(_BLOCK_SENTINEL_DATA)


class FbxBinaryWriter:
    """Stage 3 of the pipeline: nested-list FBX structure -> binary .fbx
    file. Pure binary serialization - knows nothing about NMF or scene data,
    only the `[name, values, type_codes, children]` DSL (see the module
    docstring) and the FBX binary format itself."""

    def write(self, list_structure, output_path):
        """Converts `list_structure` (as produced by
        `FbxSceneAssembler.assemble`) into an `FBXElem` tree and writes it
        to `output_path`."""
        debug_output("Converting to binary blocks...")
        root, version = self._structure_to_fbx_elem(list_structure)
        debug_output(f"Writing binary FBX (Version {version}) to {output_path}...")
        self._write_fbx_file(output_path, root, version)

    def _structure_to_fbx_elem(self, list_root):
        root = self._elem_empty(None, b"")
        ver = 0
        for n in list_root:
            node_ver = self._parse_list_structure(root, n)
            if node_ver:
                ver = node_ver
        return root, ver

    def _parse_list_structure(self, fbx_root, list_node):
        """Recursively converts one `[name, values, type_codes, children]`
        list node into `FBXElem`s appended under `fbx_root`."""
        name, data, data_types, children = list_node
        ver = 0
        assert len(data_types) == len(data)
        e = self._elem_empty(fbx_root, name.encode())

        for d, dt in zip(data, data_types):
            if dt == "B":
                e.add_bool(d)
            elif dt == "C":
                if isinstance(d, str):
                    d = d.encode("latin1")
                e.add_char(d)
            elif dt == "Z":
                e.add_int8(d)
            elif dt == "Y":
                e.add_int16(d)
            elif dt == "I":
                e.add_int32(d)
            elif dt == "L":
                e.add_int64(d)
            elif dt == "F":
                e.add_float32(d)
            elif dt == "D":
                e.add_float64(d)
            elif dt == "R":
                e.add_bytes(d)
            elif dt == "S":
                if isinstance(d, str):
                    # FBX binary uses NUL+SOH as the "::" namespace
                    # separator seen in ASCII/text FBX (e.g.
                    # "298.png::Texture").
                    d = d.encode().replace(b"::", b"\x00\x01")
                e.add_string(d)
            elif dt == "i":
                e.add_int32_array(d)
            elif dt == "l":
                e.add_int64_array(d)
            elif dt == "f":
                e.add_float32_array(d)
            elif dt == "d":
                e.add_float64_array(d)
            elif dt == "b":
                e.add_bool_array(d)
            elif dt == "c":
                e.add_byte_array(d)

        if name == "FBXVersion":
            assert data_types == "I"
            ver = int(data[0])

        for child in children:
            child_ver = self._parse_list_structure(e, child)
            if child_ver:
                ver = child_ver
        return ver

    @staticmethod
    def _elem_empty(elem, name):
        sub_elem = FBXElem(name)
        if elem is not None:
            elem.elems.append(sub_elem)
        return sub_elem

    @staticmethod
    def _init_version(fbx_version):
        global _BLOCK_SENTINEL_LENGTH, _BLOCK_SENTINEL_DATA, _ELEM_META_FORMAT, _ELEM_META_SIZE
        if fbx_version < 7500:
            _ELEM_META_FORMAT = "<3I"
            _ELEM_META_SIZE = 12
        else:
            _ELEM_META_FORMAT = "<3Q"
            _ELEM_META_SIZE = 24
        _BLOCK_SENTINEL_LENGTH = _ELEM_META_SIZE + 1
        _BLOCK_SENTINEL_DATA = b"\0" * _BLOCK_SENTINEL_LENGTH

    @staticmethod
    def _write_timedate_hack(elem_root):
        """Overwrites the top-level FileId/CreationTime with fixed values so
        re-running the converter on the same input is reproducible (useful
        for regression-testing this file by diffing output bytes). Note
        this only covers the top-level `CreationTime` string - the
        separate, nested `CreationTimeStamp` struct inside
        FBXHeaderExtension (see `FbxSceneAssembler._generate_fbx_header_json`)
        still uses the real time and is not fully deterministic."""
        ok = 0
        for elem in elem_root.elems:
            if elem.id == b"FileId":
                elem.props.clear()
                elem.props_type.clear()
                elem.add_bytes(_FILE_ID)
                ok += 1
            elif elem.id == b"CreationTime":
                elem.props.clear()
                elem.props_type.clear()
                elem.add_string(_TIME_ID)
                ok += 1
            if ok == 2:
                break

    def _write_fbx_file(self, fn, elem_root, version):
        with open(fn, "wb") as f:
            write = f.write
            tell = f.tell
            self._init_version(version)
            write(_HEAD_MAGIC)
            write(pack("<I", version))
            self._write_timedate_hack(elem_root)
            elem_root._calc_offsets_children(tell(), False)
            elem_root._write_children(write, tell, False)
            write(_FOOT_ID)
            write(b"\x00" * 4)
            ofs = tell()
            pad = ((ofs + 15) & ~15) - ofs
            if pad == 0:
                pad = 16
            write(b"\0" * pad)
            write(pack("<I", version))
            write(b"\0" * 120)
            write(b"\xf8\x5a\x8c\x6a\xde\xf5\xd9\x7e\xec\xe9\x0c\xe3\x75\x8f\x29\x0b")


# =============================================================================
# Section 2: FBX-specific constants (Stage 2/3 only - `NmfSceneConverter`,
# `TransformFold` and the format-agnostic constants it needs, FPS included,
# now live in `nmf_scene_converter.py`, shared with `nmf_to_gltf.py`)
# =============================================================================

KTIME_SEC = 46186158000
KTIME_PER_FRAME = int(KTIME_SEC / FPS)

# RrSs (0): plain hierarchical matrix composition, no Maya-style parent-scale
# compensation. This engine's transforms are baked DirectX matrices, not
# Maya joint chains, so FBX's default InheritType 1 (RSrs) was silently
# distorting deeper joints in a chain - the discrepancy compounds with
# depth, which is why a knee/shin joint (several levels down) visibly breaks
# while its parent and child look fine. See gotcha #7 in the module
# docstring.
_INHERIT_TYPE_RRSS_PROP = ["P", ["InheritType", "enum", "", "", 0], "SSSSI", []]


# =============================================================================
# Stage 2 (intermediate): FbxSceneAssembler - processed node list -> nested-
# list FBX object/property structure (the DSL FbxBinaryWriter consumes).
# Knows FBX's object model (Model/Material/Texture/Video/Geometry/...) and
# the "processed node" shape from stage 1, but nothing about NMF or binary
# encoding.
# =============================================================================


class FbxSceneAssembler:
    """Builds the full FBX object/connection list (headers, definitions,
    Models, Materials, Textures, Videos, Geometries, animation curves) from
    the processed node list produced by `NmfSceneConverter.convert`."""

    def __init__(self, uid_gen):
        self.uid_gen = uid_gen
        # Several materials commonly point at the same source page (e.g.
        # every material on a character sharing its one skin texture) -
        # see `_get_or_create_video` (gotcha #10).
        self.video_by_path = {}

    # -- FBX header/definitions/property-list builders (static) -----------

    @staticmethod
    def _generate_fbx_header_json():
        t = time.localtime()
        ms = int(time.time() * 1000) % 1000
        return [
            [
                "FBXHeaderExtension",
                [],
                "",
                [
                    ["FBXHeaderVersion", [1003], "I", []],
                    ["FBXVersion", [7500], "I", []],
                    ["EncryptionType", [0], "I", []],
                    [
                        "CreationTimeStamp",
                        [],
                        "",
                        [
                            ["Version", [1000], "I", []],
                            ["Year", [t.tm_year], "I", []],
                            ["Month", [t.tm_mon], "I", []],
                            ["Day", [t.tm_mday], "I", []],
                            ["Hour", [t.tm_hour], "I", []],
                            ["Minute", [t.tm_min], "I", []],
                            ["Second", [t.tm_sec], "I", []],
                            ["Millisecond", [ms], "I", []],
                        ],
                    ],
                    ["Creator", ["FBX SDK/FBX Plugins version 2020.3.6"], "S", []],
                    [
                        "SceneInfo",
                        ["GlobalInfo::SceneInfo", "UserData"],
                        "SS",
                        [
                            ["Type", ["UserData"], "S", []],
                            ["Version", [100], "I", []],
                            [
                                "MetaData",
                                [],
                                "",
                                [
                                    ["Version", [100], "I", []],
                                    ["Title", [""], "S", []],
                                    ["Subject", [""], "S", []],
                                    ["Author", [""], "S", []],
                                    ["Keywords", [""], "S", []],
                                    ["Revision", [""], "S", []],
                                    ["Comment", [""], "S", []],
                                ],
                            ],
                            [
                                "Properties70",
                                [],
                                "",
                                [
                                    [
                                        "P",
                                        [
                                            "DocumentUrl",
                                            "KString",
                                            "Url",
                                            "",
                                            "D:\\export.fbx",
                                        ],
                                        "SSSSS",
                                        [],
                                    ],
                                    [
                                        "P",
                                        [
                                            "SrcDocumentUrl",
                                            "KString",
                                            "Url",
                                            "",
                                            "D:\\export.fbx",
                                        ],
                                        "SSSSS",
                                        [],
                                    ],
                                    [
                                        "P",
                                        [
                                            "Original|ApplicationVendor",
                                            "KString",
                                            "",
                                            "",
                                            "Autodesk",
                                        ],
                                        "SSSSS",
                                        [],
                                    ],
                                    [
                                        "P",
                                        [
                                            "Original|ApplicationName",
                                            "KString",
                                            "",
                                            "",
                                            "Maya",
                                        ],
                                        "SSSSS",
                                        [],
                                    ],
                                    [
                                        "P",
                                        [
                                            "Original|ApplicationVersion",
                                            "KString",
                                            "",
                                            "",
                                            "2025",
                                        ],
                                        "SSSSS",
                                        [],
                                    ],
                                ],
                            ],
                        ],
                    ],
                ],
            ],
            [
                "FileId",
                [b",\xb0(\xea\xb7%\xcd\xc0\xbd\xc8\xb3 \xa6!\xf6\xff"],
                "R",
                [],
            ],
            [
                "CreationTime",
                [
                    f"{t.tm_year}-{t.tm_mon:02}-{t.tm_mday:02} {t.tm_hour:02}:{t.tm_min:02}:{t.tm_sec:02}:{ms:03}"
                ],
                "S",
                [],
            ],
            ["Creator", ["FBX SDK/FBX Plugins version 2020.3.6 build=0"], "S", []],
            [
                "GlobalSettings",
                [],
                "",
                [
                    ["Version", [1000], "I", []],
                    [
                        "Properties70",
                        [],
                        "",
                        [
                            ["P", ["UpAxis", "int", "Integer", "", 2], "SSSSI", []],
                            ["P", ["UpAxisSign", "int", "Integer", "", 1], "SSSSI", []],
                            ["P", ["FrontAxis", "int", "Integer", "", 1], "SSSSI", []],
                            [
                                "P",
                                ["FrontAxisSign", "int", "Integer", "", -1],
                                "SSSSI",
                                [],
                            ],
                            ["P", ["CoordAxis", "int", "Integer", "", 0], "SSSSI", []],
                            [
                                "P",
                                ["CoordAxisSign", "int", "Integer", "", 1],
                                "SSSSI",
                                [],
                            ],
                            [
                                "P",
                                ["UnitScaleFactor", "double", "Number", "", 100.0],
                                "SSSSD",
                                [],
                            ],
                            [
                                "P",
                                [
                                    "OriginalUnitScaleFactor",
                                    "double",
                                    "Number",
                                    "",
                                    1.0,
                                ],
                                "SSSSD",
                                [],
                            ],
                            ["P", ["TimeMode", "enum", "", "", 11], "SSSSI", []],
                            ["P", ["TimeProtocol", "enum", "", "", 2], "SSSSI", []],
                            ["P", ["SnapOnFrameMode", "enum", "", "", 0], "SSSSI", []],
                        ],
                    ],
                ],
            ],
            [
                "Documents",
                [],
                "",
                [
                    ["Count", [1], "I", []],
                    [
                        "Document",
                        [1780765614704, "", "Scene"],
                        "LSS",
                        [
                            [
                                "Properties70",
                                [],
                                "",
                                [
                                    [
                                        "P",
                                        ["SourceObject", "object", "", ""],
                                        "SSSS",
                                        [],
                                    ],
                                    [
                                        "P",
                                        [
                                            "ActiveAnimStackName",
                                            "KString",
                                            "",
                                            "",
                                            "Take 001",
                                        ],
                                        "SSSSS",
                                        [],
                                    ],
                                ],
                            ],
                            ["RootNode", [0], "L", []],
                        ],
                    ],
                ],
            ],
            ["References", [], "", []],
        ]

    @staticmethod
    def _generate_fbx_definitions(objects):
        """Every count here is derived directly from the final, already-
        built `objects` list rather than recomputed separately from the
        processed node list - so it can never drift out of sync with
        what's actually written to the Objects section below.

        Previously AnimationCurve/AnimationCurveNode were hardcoded to
        Count: 0 unconditionally, and Material/Texture/Video weren't
        declared at all. For every non-animated model that "happened" to
        work (0 declared, 0 actual curves - accidentally consistent), but
        every door - the only assets with real Model-level animation in
        this game (open/close) - has dozens of real AnimationCurve
        objects against a declared count of 0, and failed to import in
        Godot (`ufbx: Failed to load`) while otherwise-identical static
        models didn't. Strict binary FBX readers can use Definitions/
        Count for pre-allocation, so a declared-vs-actual mismatch is
        exactly the kind of thing that reads fine to a lenient parser and
        chokes a strict one."""

        def count(tag):
            return sum(1 for o in objects if o[0] == tag)

        model_count = count("Model")
        mesh_count = count("Geometry")
        material_count = count("Material")
        texture_count = count("Texture")
        video_count = count("Video")
        deformer_count = count("Deformer")
        anim_stack_count = count("AnimationStack")
        anim_layer_count = count("AnimationLayer")
        anim_curve_count = count("AnimationCurve")
        anim_curve_node_count = count("AnimationCurveNode")

        total_count = (
            model_count
            + mesh_count
            + material_count
            + texture_count
            + video_count
            + deformer_count
            + anim_stack_count
            + anim_layer_count
            + anim_curve_count
            + anim_curve_node_count
        )

        object_types = [
            ["ObjectType", ["GlobalSettings"], "S", [["Count", [1], "I", []]]],
            [
                "ObjectType",
                ["Model"],
                "S",
                [
                    ["Count", [model_count], "I", []],
                    [
                        "PropertyTemplate",
                        ["FbxNode"],
                        "S",
                        [["Properties70", [], "", []]],
                    ],
                ],
            ],
            [
                "ObjectType",
                ["Geometry"],
                "S",
                [
                    ["Count", [mesh_count], "I", []],
                    [
                        "PropertyTemplate",
                        ["FbxMesh"],
                        "S",
                        [["Properties70", [], "", []]],
                    ],
                ],
            ],
        ]
        if material_count:
            object_types.append(
                ["ObjectType", ["Material"], "S", [["Count", [material_count], "I", []]]]
            )
        if texture_count:
            object_types.append(
                ["ObjectType", ["Texture"], "S", [["Count", [texture_count], "I", []]]]
            )
        if video_count:
            object_types.append(
                ["ObjectType", ["Video"], "S", [["Count", [video_count], "I", []]]]
            )
        if deformer_count:
            # Gotcha #25: BlendShape/BlendShapeChannel deformer objects
            # (mesh vertex animation) both use the "Deformer" object tag -
            # same reasoning as the historical AnimationCurve/
            # AnimationCurveNode Count=0 bug documented above, a strict
            # reader can choke on a declared-vs-actual mismatch.
            object_types.append(
                ["ObjectType", ["Deformer"], "S", [["Count", [deformer_count], "I", []]]]
            )
        object_types.append(
            [
                "ObjectType",
                ["AnimationStack"],
                "S",
                [
                    ["Count", [anim_stack_count], "I", []],
                    ["PropertyTemplate", ["FbxAnimStack"], "S", []],
                ],
            ]
        )
        object_types.append(
            [
                "ObjectType",
                ["AnimationLayer"],
                "S",
                [
                    ["Count", [anim_layer_count], "I", []],
                    ["PropertyTemplate", ["FbxAnimLayer"], "S", []],
                ],
            ]
        )
        object_types.append(
            ["ObjectType", ["AnimationCurve"], "S", [["Count", [anim_curve_count], "I", []]]]
        )
        object_types.append(
            [
                "ObjectType",
                ["AnimationCurveNode"],
                "S",
                [
                    ["Count", [anim_curve_node_count], "I", []],
                    ["PropertyTemplate", ["FbxAnimCurveNode"], "S", []],
                ],
            ]
        )

        return [
            [
                "Definitions",
                [],
                "",
                [
                    ["Version", [100], "I", []],
                    ["Count", [total_count], "I", []],
                ]
                + object_types,
            ],
        ]

    @staticmethod
    def _vector3d_prop(name, values):
        return [
            "P",
            [
                name,
                "Vector3D",
                "Vector",
                "",
                float(values[0]),
                float(values[1]),
                float(values[2]),
            ],
            "SSSSDDD",
            [],
        ]

    @staticmethod
    def _model_values_prop(name, values):
        return [
            "P",
            [name, name, "", "A+", float(values[0]), float(values[1]), float(values[2])],
            "SSSSDDD",
            [],
        ]

    # -- per-model / material / geometry / animation object builders ------

    @staticmethod
    def _build_model_transform_props(node):
        """Builds the common Lcl Translation/Rotation/Scaling (+ pivots /
        joint-orient / InheritType) Properties70 entries and picks the FBX
        Model subtype, for fram/joint/mesh node types."""
        nt = node["node_type"]
        props70 = [
            FbxSceneAssembler._model_values_prop(
                "Lcl Translation", node.get("translation", [0.0, 0.0, 0.0])
            ),
            FbxSceneAssembler._model_values_prop(
                "Lcl Rotation", node.get("rotation", [0.0, 0.0, 0.0])
            ),
            FbxSceneAssembler._model_values_prop(
                "Lcl Scaling", node.get("scale", [1.0, 1.0, 1.0])
            ),
        ]

        model_type = "Null"
        if nt == "fram":
            model_type = "Mesh" if node.get("mesh") else "Null"
            has_pivot = False
            if node.get("rotate_pivot_translate"):
                props70.append(
                    FbxSceneAssembler._vector3d_prop(
                        "RotationOffset", node["rotate_pivot_translate"]
                    )
                )
                has_pivot = True
            if node.get("rotate_pivot"):
                props70.append(
                    FbxSceneAssembler._vector3d_prop("RotationPivot", node["rotate_pivot"])
                )
                has_pivot = True
            if node.get("scale_pivot_translate"):
                props70.append(
                    FbxSceneAssembler._vector3d_prop(
                        "ScalingOffset", node["scale_pivot_translate"]
                    )
                )
                has_pivot = True
            if node.get("scale_pivot"):
                props70.append(
                    FbxSceneAssembler._vector3d_prop("ScalingPivot", node["scale_pivot"])
                )
                has_pivot = True
            # Gotcha #15: RotationActive=1 tells an importer "this Model
            # uses the full Maya-style pivot chain, decode it accordingly"
            # - only meaningful (and only written) when a pivot property
            # above actually made that true. Writing it unconditionally on
            # every plain fram (including gotcha #12's pivot-split
            # outer/middle/inner nodes, which deliberately carry NO pivot
            # properties at all) may be why Blender's importer mis-handled
            # those nodes' animation - see the gotcha #14 write-up.
            if has_pivot:
                props70.append(["P", ["RotationActive", "bool", "", "", 1], "SSSSI", []])
            props70.append(_INHERIT_TYPE_RRSS_PROP)
        elif nt == "joint":
            model_type = "LimbNode"
            if node.get("joint_orient"):
                props70.append(
                    FbxSceneAssembler._vector3d_prop("PreRotation", node["joint_orient"])
                )
            props70.append(["P", ["RotationActive", "bool", "", "", 1], "SSSSI", []])
            props70.append(_INHERIT_TYPE_RRSS_PROP)
        elif nt == "mesh":
            model_type = "Mesh"

        return props70, model_type

    # -- texture tinting (bakes gotcha #11's diffuse*texture multiply into
    # a cached PNG copy, since the FBX connection graph has no multiply
    # node to express it directly) ----------------------------------------

    _TINT_EPSILON = 0.004  # ~1 unit of an 8-bit channel; below this, skip.

    @staticmethod
    def _is_white_tint(rgb):
        return all(abs(c - 1.0) < FbxSceneAssembler._TINT_EPSILON for c in rgb)

    @staticmethod
    def _png_paeth(a, b, c):
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        if pa <= pb and pa <= pc:
            return a
        elif pb <= pc:
            return b
        return c

    @staticmethod
    def _decode_png_rgba(png_bytes):
        """Minimal decoder for 8-bit RGB/RGBA, non-interlaced PNGs (all
        five standard filter types, though in practice every page here was
        itself produced by extract_textures.py's save_png_pure, which only
        ever emits filter type 0 - the other branches exist purely so this
        stays correct if ever pointed at a PNG from elsewhere). Returns
        (width, height, rgba_bytes)."""
        if png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("not a PNG")
        pos = 8
        width = height = bit_depth = color_type = None
        idat = bytearray()
        while pos < len(png_bytes):
            length = unpack(">I", png_bytes[pos : pos + 4])[0]
            tag = png_bytes[pos + 4 : pos + 8]
            data = png_bytes[pos + 8 : pos + 8 + length]
            pos += 12 + length
            if tag == b"IHDR":
                width, height, bit_depth, color_type = unpack(">IIBB", data[:10])
            elif tag == b"IDAT":
                idat.extend(data)
            elif tag == b"IEND":
                break
        if width is None:
            raise ValueError("missing IHDR")
        if bit_depth != 8 or color_type not in (2, 6):
            raise ValueError(
                f"unsupported PNG format (bit_depth={bit_depth}, color_type={color_type})"
            )
        channels = 4 if color_type == 6 else 3
        raw = zlib.decompress(bytes(idat))
        stride = width * channels
        prev = np.zeros(stride, dtype=np.int16)
        out = np.empty((height, width, 4), dtype=np.uint8)
        pos = 0
        for y in range(height):
            filt = raw[pos]
            pos += 1
            row = np.frombuffer(raw, dtype=np.uint8, count=stride, offset=pos).astype(
                np.int16
            )
            pos += stride
            if filt == 1:  # Sub
                row = row.copy()
                for i in range(channels, stride):
                    row[i] = (row[i] + row[i - channels]) & 0xFF
            elif filt == 2:  # Up
                row = (row + prev) & 0xFF
            elif filt == 3:  # Average
                row = row.copy()
                for i in range(stride):
                    a = row[i - channels] if i >= channels else 0
                    row[i] = (row[i] + ((a + int(prev[i])) >> 1)) & 0xFF
            elif filt == 4:  # Paeth
                row = row.copy()
                for i in range(stride):
                    a = row[i - channels] if i >= channels else 0
                    b = int(prev[i])
                    c = int(prev[i - channels]) if i >= channels else 0
                    row[i] = (row[i] + FbxSceneAssembler._png_paeth(a, b, c)) & 0xFF
            # filt == 0 (None): row is already correct as decoded.
            prev = row
            row_u8 = row.astype(np.uint8).reshape(width, channels)
            if channels == 4:
                out[y] = row_u8
            else:
                out[y, :, :3] = row_u8
                out[y, :, 3] = 255
        return width, height, out.tobytes()

    @staticmethod
    def _encode_png_rgba(width, height, rgba_bytes):
        """Encodes 8-bit RGBA raw pixel data as a PNG - filter type 0 on
        every row, mirroring extract_textures.py's save_png_pure."""
        arr = np.frombuffer(rgba_bytes, dtype=np.uint8).reshape(height, width * 4)
        filtered = np.empty((height, width * 4 + 1), dtype=np.uint8)
        filtered[:, 0] = 0
        filtered[:, 1:] = arr
        compressed = zlib.compress(filtered.tobytes(), level=6)

        def chunk(tag, data):
            c = pack(">I", len(data)) + tag + data
            crc = zlib.crc32(tag)
            crc = zlib.crc32(data, crc)
            return c + pack(">I", crc & 0xFFFFFFFF)

        out = bytearray(b"\x89PNG\r\n\x1a\n")
        out += chunk(b"IHDR", pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        out += chunk(b"IDAT", compressed)
        out += chunk(b"IEND", b"")
        return bytes(out)

    @staticmethod
    def _tint_rgba(rgba_bytes, rgb):
        """Multiplies RGB (not alpha) by `rgb` - the same diffuse*texture
        multiply the game applies at render time (see gotcha #11)."""
        arr = np.frombuffer(rgba_bytes, dtype=np.uint8).reshape(-1, 4).astype(np.float32)
        factors = np.array([rgb[0], rgb[1], rgb[2], 1.0], dtype=np.float32)
        arr = np.clip(arr * factors + 0.5, 0, 255).astype(np.uint8)
        return arr.tobytes()

    def _resolve_tinted_texture_path(self, raw_tex_path, rgb):
        """Returns a path to a cached, tinted copy of `raw_tex_path` sitting
        next to it in a "_tinted" subfolder - reused across materials/runs
        that share the same (page, color) via a plain on-disk cache, since
        the same page+color combo recurs a lot (e.g. many identically
        colored copies of one prop)."""
        base_dir = os.path.dirname(raw_tex_path)
        base_name = os.path.splitext(os.path.basename(raw_tex_path))[0]
        tint_dir = os.path.join(base_dir, "_tinted")
        tinted_name = f"{base_name}_{rgb[0]:.3f}_{rgb[1]:.3f}_{rgb[2]:.3f}.png"
        tinted_path = os.path.join(tint_dir, tinted_name)
        if os.path.exists(tinted_path):
            return tinted_path

        with open(raw_tex_path, "rb") as f:
            png_bytes = f.read()
        width, height, rgba = self._decode_png_rgba(png_bytes)
        tinted_rgba = self._tint_rgba(rgba, rgb)
        tinted_png = self._encode_png_rgba(width, height, tinted_rgba)

        os.makedirs(tint_dir, exist_ok=True)
        with open(tinted_path, "wb") as f:
            f.write(tinted_png)
        debug_output(
            f"[texture] baked color ({rgb[0]:.3f},{rgb[1]:.3f},{rgb[2]:.3f}) "
            f"into {tinted_path}"
        )
        return tinted_path

    def _get_or_create_video(self, raw_tex_path, file_path, new_objects):
        """Embeds a texture PNG as a Video "Clip" object, or reuses an
        already-embedded one for the same file path - several materials on
        a character commonly share one page texture, and embedding it once
        instead of once per material keeps the FBX from growing
        needlessly."""
        cached = self.video_by_path.get(file_path)
        if cached is not None:
            return cached

        vid_id = self.uid_gen.next()
        filename_raw = os.path.basename(file_path)
        vid_obj_name = f"{filename_raw}::Video"
        vid_obj = [
            "Video",
            [vid_id, vid_obj_name, "Clip"],
            "LSS",
            [
                ["Type", ["Clip"], "S", []],
                [
                    "Properties70",
                    [],
                    "",
                    [
                        ["P", ["Path", "KString", "XRefUrl", "", file_path], "SSSSS", []],
                    ],
                ],
                ["UseMipMap", [0], "I", []],
                ["Filename", [file_path], "S", []],
                ["RelativeFilename", [f"textures/{filename_raw}"], "S", []],
            ],
        ]
        # Embed the actual PNG bytes so the texture displays even when the
        # FBX is moved/opened somewhere that doesn't have the sibling
        # "textures" folder or can't resolve the absolute Filename path -
        # without this, every importer falls back to its own
        # missing-texture placeholder (typically solid pink).
        try:
            with open(raw_tex_path, "rb") as f:
                tex_bytes = f.read()
            vid_obj[3].append(["Content", [tex_bytes], "R", []])
            debug_output(f"[texture] embedded {file_path} ({len(tex_bytes)} bytes)")
        except OSError as e:
            debug_output(f"[texture] FAILED to embed {file_path} ({e})")

        new_objects.append(vid_obj)
        result = (vid_id, vid_obj_name)
        self.video_by_path[file_path] = result
        return result

    def _build_texture_objects(self, mat_data, tint=None):
        """Builds (or reuses, via `_get_or_create_video`) the Video+Texture
        FBX objects for one textured material. Returns (tex_id, vid_id,
        new_objects) - `new_objects` holds whichever of Video/Texture are
        newly created, in the order they should be appended.

        `tint`, when given a non-white (r, g, b), swaps in a cached tinted
        copy of the page (see gotcha #11 / `_resolve_tinted_texture_path`)
        so the material's baked color actually shows up in Blender instead
        of being silently dropped once a texture is connected.

        tex_id is allocated before vid_id (matching uid_gen call order kept
        from before this method existed) - the two ids are otherwise
        interchangeable internal cross-references, but keeping the same
        allocation order keeps generated ids reproducible run-to-run."""
        new_objects = []
        raw_tex_path = mat_data["tex_path"]
        if tint is not None:
            raw_tex_path = self._resolve_tinted_texture_path(raw_tex_path, tint)
        file_path = raw_tex_path.replace("\\", "/")
        filename_raw = os.path.basename(file_path)
        tex_obj_name = f"{filename_raw}::Texture"
        tex_id = self.uid_gen.next()

        vid_id, vid_obj_name = self._get_or_create_video(
            raw_tex_path, file_path, new_objects
        )
        offset_u = float(mat_data.get("offsetU", 0.0))
        offset_v = float(mat_data.get("offsetV", 0.0))
        tex_props = [
            ["P", ["CurrentTextureBlendMode", "enum", "", "", 0], "SSSSI", []],
            ["P", ["UVSet", "KString", "", "", "map1"], "SSSSS", []],
            ["P", ["UseMaterial", "bool", "", "", 1], "SSSSI", []],
            [
                "P",
                ["Translation", "Vector", "", "A", offset_u, offset_v, 0.0],
                "SSSSDDD",
                [],
            ],
            [
                "P",
                ["Rotation", "Vector", "", "A", 0.0, 0.0, float(mat_data["rotateUV"])],
                "SSSSDDD",
                [],
            ],
            [
                "P",
                [
                    "Scaling",
                    "Vector",
                    "",
                    "A",
                    float(mat_data["repeatU"]),
                    float(mat_data["repeatV"]),
                    1.0,
                ],
                "SSSSDDD",
                [],
            ],
        ]
        new_objects.append(
            [
                "Texture",
                [tex_id, tex_obj_name, "TextureVideoClip"],
                "LSS",
                [
                    ["Type", ["TextureVideoClip"], "S", []],
                    ["Version", [202], "I", []],
                    ["TextureName", [tex_obj_name], "S", []],
                    ["Properties70", [], "", tex_props],
                    ["Media", [vid_obj_name], "S", []],
                    ["FileName", [file_path], "S", []],
                    ["ModelUVTranslation", [offset_u, offset_v], "DD", []],
                    [
                        "ModelUVScaling",
                        [float(mat_data["repeatU"]), float(mat_data["repeatV"])],
                        "DD",
                        [],
                    ],
                    ["Texture_Alpha_Source", ["None"], "S", []],
                ],
            ]
        )
        return tex_id, vid_id, new_objects

    def _build_material_objects(self, node, model_id):
        """Builds Material (+ Video/Texture, for textured materials) FBX
        objects and connections for one mesh node's `materials_data`."""
        objects = []
        connections = []

        for mat_data in node.get("materials_data", []):
            mat_id = self.uid_gen.next()
            transparency_factor = 1.0 - float(mat_data["opacity"])
            # blend_mode: 0=opaque(decal) 1=alpha 2=additive 3=multiply.
            # Only alpha/additive materials should have the texture's alpha
            # channel drive transparency - see gotcha #5 in the module
            # docstring.
            wants_alpha_from_texture = mat_data.get("blend_mode", 0) in (1, 2)
            transparent_rgb = (
                (1.0, 1.0, 1.0) if wants_alpha_from_texture else (0.0, 0.0, 0.0)
            )

            mtrl_rgb = (float(mat_data["r"]), float(mat_data["g"]), float(mat_data["b"]))
            # See gotcha #11: once textured, DiffuseColor is dead data to
            # most importers (the texture is wired straight to it, no
            # multiply node) - bake the color into the texture instead and
            # report white here so nothing double-tints.
            needs_tint = mat_data["has_tex"] and not self._is_white_tint(mtrl_rgb)
            diffuse_rgb = (1.0, 1.0, 1.0) if needs_tint else mtrl_rgb

            mat_props = [
                ["P", ["ShadingModel", "KString", "", "", "Lambert"], "SSSSS", []],
                ["P", ["MultiLayer", "bool", "", "", 0], "SSSSI", []],
                ["P", ["EmissiveColor", "Color", "", "A", 0.0, 0.0, 0.0], "SSSSDDD", []],
                ["P", ["AmbientColor", "Color", "", "A", 0.0, 0.0, 0.0], "SSSSDDD", []],
                [
                    "P",
                    [
                        "DiffuseColor",
                        "Color",
                        "",
                        "A",
                        diffuse_rgb[0],
                        diffuse_rgb[1],
                        diffuse_rgb[2],
                    ],
                    "SSSSDDD",
                    [],
                ],
                [
                    "P",
                    ["TransparentColor", "Color", "", "A", *transparent_rgb],
                    "SSSSDDD",
                    [],
                ],
                [
                    "P",
                    ["TransparencyFactor", "Number", "", "A", float(transparency_factor)],
                    "SSSSD",
                    [],
                ],
                [
                    "P",
                    ["Opacity", "double", "Number", "", float(mat_data["opacity"])],
                    "SSSSD",
                    [],
                ],
            ]
            objects.append(
                [
                    "Material",
                    [mat_id, f"{mat_data['mat_name']}::Material", ""],
                    "LSS",
                    [
                        ["Version", [102], "I", []],
                        ["ShadingModel", ["lambert"], "S", []],
                        ["MultiLayer", [0], "I", []],
                        ["Properties70", [], "", mat_props],
                    ],
                ]
            )
            connections.append(["C", ["OO", mat_id, model_id], "SLL", []])

            if mat_data["has_tex"]:
                tex_id, vid_id, new_objects = self._build_texture_objects(
                    mat_data, tint=mtrl_rgb if needs_tint else None
                )
                objects.extend(new_objects)
                connections.append(["C", ["OO", vid_id, tex_id], "SLL", []])
                connections.append(
                    ["C", ["OP", tex_id, mat_id, "DiffuseColor"], "SLLS", []]
                )
                if wants_alpha_from_texture:
                    connections.append(
                        ["C", ["OP", tex_id, mat_id, "TransparentColor"], "SLLS", []]
                    )

        return objects, connections

    @staticmethod
    def _build_mesh_geometry_object(node, geom_id, mat_data_list):
        poly_mat_indices = node.get("poly_mat_indices", [0])
        if len(mat_data_list) > 1:
            # Multiple materials: assign per-polygon via the material index map.
            layer_material = [
                "LayerElementMaterial",
                [0],
                "I",
                [
                    ["Version", [101], "I", []],
                    ["Name", [""], "S", []],
                    ["MappingInformationType", ["ByPolygon"], "S", []],
                    ["ReferenceInformationType", ["IndexToDirect"], "S", []],
                    ["Materials", [poly_mat_indices], "i", []],
                ],
            ]
        else:
            # Single material: applies to the whole mesh.
            layer_material = [
                "LayerElementMaterial",
                [0],
                "I",
                [
                    ["Version", [101], "I", []],
                    ["Name", [""], "S", []],
                    ["MappingInformationType", ["AllSame"], "S", []],
                    ["ReferenceInformationType", ["IndexToDirect"], "S", []],
                    ["Materials", [[0]], "i", []],
                ],
            ]
        return [
            "Geometry",
            [geom_id, f"{node['node_name']}::Geometry", "Mesh"],
            "LSS",
            [
                ["Vertices", [[x for v in node["vrts"] for x in v]], "d", []],
                ["PolygonVertexIndex", [node["PolygonVertexIndex"]], "i", []],
                ["Edges", [node["Edges"]], "i", []],
                ["GeometryVersion", [124], "I", []],
                [
                    "LayerElementNormal",
                    [0],
                    "I",
                    [
                        ["Version", [102], "I", []],
                        ["Name", [""], "S", []],
                        ["MappingInformationType", ["ByPolygonVertex"], "S", []],
                        ["ReferenceInformationType", ["Direct"], "S", []],
                        ["Normals", [node["Normals"]], "d", []],
                        ["NormalsW", [node["NormalsW"]], "d", []],
                    ],
                ],
                [
                    "LayerElementUV",
                    [0],
                    "I",
                    [
                        ["Version", [101], "I", []],
                        ["Name", ["map1"], "S", []],
                        ["MappingInformationType", ["ByPolygonVertex"], "S", []],
                        ["ReferenceInformationType", ["IndexToDirect"], "S", []],
                        ["UV", [node["UV"]], "d", []],
                        ["UVIndex", [node["UVIndex"]], "i", []],
                    ],
                ],
                layer_material,
                [
                    "Layer",
                    [0],
                    "I",
                    [
                        ["Version", [100], "I", []],
                        [
                            "LayerElement",
                            [],
                            "",
                            [
                                ["Type", ["LayerElementNormal"], "S", []],
                                ["TypedIndex", [0], "I", []],
                            ],
                        ],
                        [
                            "LayerElement",
                            [],
                            "",
                            [
                                ["Type", ["LayerElementMaterial"], "S", []],
                                ["TypedIndex", [0], "I", []],
                            ],
                        ],
                        [
                            "LayerElement",
                            [],
                            "",
                            [
                                ["Type", ["LayerElementUV"], "S", []],
                                ["TypedIndex", [0], "I", []],
                            ],
                        ],
                    ],
                ],
            ],
        ]

    @staticmethod
    def _compute_auto_tangent_slopes(frames, values):
        """Per-key auto-tangent slope, in value-per-SECOND units (matching
        ufbx's/FBX's on-disk `KeyAttrDataFloat` convention - confirmed by
        reading ufbx's own tangent solver: it converts `KeyTime` ticks to
        seconds before ever computing or comparing a slope). Interior keys
        use the same neighbour-chord formula already documented on the
        caller (`(next_value - prev_value) / (next_time - prev_time)`,
        matching ufbx's `ufbxi_solve_auto_tangent` under the
        TIME_INDEPENDENT flag this file always sets); boundary keys fall
        back to the one-sided difference ufbx itself uses there
        (`ufbxi_solve_auto_tangent_left`/`_right`). `frames` are in
        frame-number units (see `KTIME_PER_FRAME`), so converted to
        seconds via `/ FPS` here to get value-per-second slopes."""
        n = len(frames)
        times_sec = [f / FPS for f in frames]
        tangents = [0.0] * n
        for i in range(n):
            if i == 0:
                if n > 1:
                    dt = times_sec[1] - times_sec[0]
                    tangents[i] = (values[1] - values[0]) / dt if dt else 0.0
            elif i == n - 1:
                dt = times_sec[i] - times_sec[i - 1]
                tangents[i] = (values[i] - values[i - 1]) / dt if dt else 0.0
            else:
                dt = times_sec[i + 1] - times_sec[i - 1]
                tangents[i] = (values[i + 1] - values[i - 1]) / dt if dt else 0.0
        return tangents

    def _build_animation_data(self, node, model_id, layer_id):
        fbx_objects = []
        fbx_connections = []
        spec_map = {
            "translation": {
                "prop": "Lcl Translation",
                "prefix": "T",
                "def": [0.0, 0.0, 0.0],
            },
            "rotation": {"prop": "Lcl Rotation", "prefix": "R", "def": [0.0, 0.0, 0.0]},
            "scale": {"prop": "Lcl Scaling", "prefix": "S", "def": [1.0, 1.0, 1.0]},
        }
        axes = ["x", "y", "z"]
        axis_labels = ["d|X", "d|Y", "d|Z"]

        for track, spec in spec_map.items():
            tdata = node.get("animations", {}).get(track)
            if not tdata:
                continue
            has_keys = any(tdata.get(ax) and tdata[ax].get("frames") for ax in axes)
            if not has_keys:
                continue

            curve_node_id = self.uid_gen.next()
            # Gotcha #14: must be unique per owning node - see below.
            curve_node_name = f"{node['node_name']}_{spec['prefix']}::AnimCurveNode"

            props_list = [
                ["P", [axis_labels[i], "Number", "", "A", spec["def"][i]], "SSSSD", []]
                for i in range(3)
            ]

            fbx_objects.append(
                [
                    "AnimationCurveNode",
                    [curve_node_id, curve_node_name, ""],
                    "LSS",
                    [["Properties70", [], "", props_list]],
                ]
            )
            fbx_connections.append(
                ["C", ["OP", curve_node_id, model_id, spec["prop"]], "SLLS", []]
            )
            fbx_connections.append(["C", ["OO", curve_node_id, layer_id], "SLL", []])
            DEBUG and debug_output(
                f"[curve] '{curve_node_name}' id={curve_node_id} -> OP -> "
                f"model '{node['node_name']}::Model' id={model_id} prop={spec['prop']!r}; "
                f"axes_with_keys={[ax for ax in axes if tdata.get(ax) and tdata[ax].get('frames')]}"
            )

            for i, ax in enumerate(axes):
                ax_data = tdata.get(ax)
                if not ax_data:
                    continue
                frames = ax_data.get("frames")
                values = ax_data.get("values")
                if not frames:
                    continue
                curve_id = self.uid_gen.next()
                n_keys = len(frames)
                times = [int(f * KTIME_PER_FRAME) for f in frames]
                vals = [float(v) for v in values]
                # Gotcha #19: a rotation axis that went through
                # `_wrap_rotation_into_range` (its instant-reset pairs -
                # e.g. 179.9 with a neighbour just 0.001 frames later at
                # -179.9) uses LINEAR (0x4) instead of the
                # CUBIC|TANGENT_AUTO|TIME_INDEPENDENT (8456) combo
                # everything else still uses. Auto-tangent's slope formula
                # (confirmed against ufbx's own source) is the straight
                # chord between a key's PREVIOUS and NEXT neighbours,
                # `(next_value-prev_value)/(next_time-prev_time)`,
                # completely ignoring the key's own value - harmless
                # normally, but that neighbour-chord formula turns the
                # tiny reset gap into a wildly wrong, huge-magnitude slope
                # that visibly distorts the curve well before the actual
                # crossing (confirmed by dense ufbx sampling - the
                # rotation measurably reversed ~0.05s before the wrap).
                # Wrapped axes are already densely subdivided (see
                # `_subdivide_wide_rotation_segments`), so losing cubic
                # smoothing between keys is not noticeable there, and
                # LINEAR has no tangent computation to go wrong; other
                # rotation axes (e.g. a door hinge's few widely-spaced
                # keys, never wrapped) keep cubic easing.
                is_linear = track == "rotation" and ax_data.get("linear")
                flags = [4 if is_linear else 8456] * n_keys
                refs = [1] * n_keys
                DEBUG and debug_output(
                    f"[curve-detail] '{node['node_name']}' {spec['prop']} "
                    f"axis={axis_labels[i]} id={curve_id} n_keys={n_keys} "
                    f"frames(FPS-units)={frames} KeyTime(raw)={times} values={vals}"
                )
                # KeyAttrDataFloat: 4 floats per KeyAttrRefCount run (here
                # one run per key, since refs is all 1s) - (slope_right,
                # next_slope_left, packed_weight_lo, packed_weight_hi).
                # ufbx (and, per the module docstring's whole reason for
                # existing, presumably any equally strict reader) requires
                # this array to be PRESENT with exactly refs_total*4
                # entries - it was missing here entirely, which is why
                # every animated model (doors, or anything else with a
                # keyframed FRAM/JOIN - anything static never touches this
                # code path) failed to import
                # (`ufbxi_find_array(..., KeyAttrDataFloat)` -> null ->
                # "Failed to load", confirmed against ufbx v0.21.3
                # directly). Gotcha #27: it used to be all zero here,
                # relying on TANGENT_AUTO to make every reader recompute
                # the real slope instead of trusting this array - true for
                # ufbx (confirmed against its source: an all-zero
                # slope_right + next_slope_left pair is exactly the
                # signal ufbx's own auto-tangent solver treats as "not
                # supplied, please compute") and apparently for Godot, but
                # NOT for Blender's own FBX importer: on a character rig's
                # dense, genuinely-multi-axis JOIN rotation curves,
                # Blender's resampling (gotcha #22's mechanism) sometimes
                # picked the wrong Euler branch at specific frames only
                # when this array was present as all-zero - confirmed by
                # the user directly, A/B, on byte-identical curve values:
                # omitting the element fixed it, re-adding it as zeros
                # reproduced the bad frame. Simply omitting it for JOIN
                # (tried first) traded away ufbx/Godot loadability for
                # every character rig, which isn't an acceptable trade-off
                # either - so this now computes the *real* per-key
                # auto-tangent slope instead (see
                # `_compute_auto_tangent_slopes` - same neighbour-chord
                # formula ufbx's own solver uses under TIME_INDEPENDENT,
                # in value-per-second units to match its on-disk
                # convention), for every node type, not just JOIN: ufbx
                # reads a supplied non-near-zero slope verbatim instead of
                # recomputing it, so a *correct* value here is provably a
                # no-op for ufbx/Godot either way, while giving Blender
                # the real tangent shape it apparently expects.
                tangents = FbxSceneAssembler._compute_auto_tangent_slopes(
                    frames, vals
                )
                attr_data = []
                for k in range(n_keys):
                    nxt = tangents[k + 1] if k + 1 < n_keys else tangents[k]
                    attr_data.extend([tangents[k], nxt, 0.0, 0.0])
                fbx_objects.append(
                    [
                        "AnimationCurve",
                        [
                            curve_id,
                            f"{node['node_name']}_{spec['prefix']}{ax.upper()}::AnimCurve",
                            "",
                        ],
                        "LSS",
                        [
                            ["Default", [0.0], "D", []],
                            ["KeyVer", [4009], "I", []],
                            ["KeyTime", [times], "l", []],
                            ["KeyValueFloat", [vals], "f", []],
                            ["KeyAttrFlags", [flags], "i", []],
                            ["KeyAttrDataFloat", [attr_data], "f", []],
                            ["KeyAttrRefCount", [refs], "i", []],
                        ],
                    ]
                )
                fbx_connections.append(
                    ["C", ["OP", curve_id, curve_node_id, axis_labels[i]], "SLLS", []]
                )
        return fbx_objects, fbx_connections

    def _build_mesh_blendshape_data(self, node, geom_id, layer_id):
        """Gotcha #25: one `BlendShape` deformer per mesh, one
        `BlendShapeChannel` per (vertex group, animated axis) entry in
        `node["mesh_animations"]` (see `NmfSceneConverter.
        _build_mesh_vertex_animations`) - connection graph and field names
        verified directly against `ufbx`'s own parser (`ufbxi_read_shape`/
        `ufbxi_read_blend_channel`/`ufbxi_fetch_blend_keyframes` in
        ufbx.c): `Geometry(...,"Shape")` --OO--> `Deformer(...,
        "BlendShapeChannel")` --OO--> `Deformer(...,"BlendShape")` --OO-->
        the mesh's own `geom_id`. `DeformPercent` is declared as a normal
        animatable Properties70 entry (not a bare child element) - ufbx's
        own comment notes that form is what "Blender saves blend shapes
        with", but confirms animation always resolves through the
        Properties70 property regardless of which form declares it, and
        this codebase's whole curve-building convention already goes
        through Properties70 for everything else (Lcl Translation/
        Rotation/Scaling) - so this stays consistent rather than
        introducing a second declaration style. `FullWeights: [100.0]`
        marks the single shape as reaching full effect at weight 100 (an
        empty/absent array would default to the same 100% per ufbx, but
        it's written explicitly for clarity and for stricter readers).
        """
        channels = node.get("mesh_animations") or []
        if not channels:
            return [], []

        fbx_objects = []
        fbx_connections = []

        blend_deformer_id = self.uid_gen.next()
        fbx_objects.append(
            [
                "Deformer",
                [blend_deformer_id, f"{node['node_name']}::BlendShape", "BlendShape"],
                "LSS",
                [["Version", [100], "I", []]],
            ]
        )
        fbx_connections.append(
            ["C", ["OO", blend_deformer_id, geom_id], "SLL", []]
        )

        for i, ch in enumerate(channels):
            indices = ch["indices"]
            dx, dy, dz = ch["delta_dir"]
            shape_id = self.uid_gen.next()
            shape_name = f"{node['node_name']}_{i}::Shape"
            fbx_objects.append(
                [
                    "Geometry",
                    [shape_id, shape_name, "Shape"],
                    "LSS",
                    [
                        ["Version", [100], "I", []],
                        ["Indexes", [list(indices)], "i", []],
                        [
                            "Vertices",
                            [[c for _ in indices for c in (dx, dy, dz)]],
                            "d",
                            [],
                        ],
                    ],
                ]
            )

            channel_id = self.uid_gen.next()
            channel_name = f"{node['node_name']}_{i}::BlendShapeChannel"
            fbx_objects.append(
                [
                    "Deformer",
                    [channel_id, channel_name, "BlendShapeChannel"],
                    "LSS",
                    [
                        ["Version", [100], "I", []],
                        ["FullWeights", [[100.0]], "d", []],
                        [
                            "Properties70",
                            [],
                            "",
                            [
                                [
                                    "P",
                                    ["DeformPercent", "Number", "", "A", 0.0],
                                    "SSSSD",
                                    [],
                                ],
                            ],
                        ],
                    ],
                ]
            )
            fbx_connections.append(["C", ["OO", shape_id, channel_id], "SLL", []])
            fbx_connections.append(
                ["C", ["OO", channel_id, blend_deformer_id], "SLL", []]
            )

            curve_node_id = self.uid_gen.next()
            curve_node_name = f"{node['node_name']}_{i}_DeformPercent::AnimCurveNode"
            fbx_objects.append(
                [
                    "AnimationCurveNode",
                    [curve_node_id, curve_node_name, ""],
                    "LSS",
                    [
                        [
                            "Properties70",
                            [],
                            "",
                            [["P", ["d", "Number", "", "A", 0.0], "SSSSD", []]],
                        ]
                    ],
                ]
            )
            fbx_connections.append(
                ["C", ["OP", curve_node_id, channel_id, "DeformPercent"], "SLLS", []]
            )
            fbx_connections.append(["C", ["OO", curve_node_id, layer_id], "SLL", []])
            DEBUG and debug_output(
                f"[blendshape] '{node['node_name']}' channel {i} indices={indices} "
                f"delta_dir={ch['delta_dir']} frames={ch['frames']} values={ch['values']}"
            )

            frames = ch["frames"]
            values = ch["values"]
            n_keys = len(frames)
            times = [int(f * KTIME_PER_FRAME) for f in frames]
            vals = [float(v) * 100.0 for v in values]
            flags = [8456] * n_keys
            refs = [1] * n_keys
            attr_data = [0.0] * (len(refs) * 4)
            curve_id = self.uid_gen.next()
            fbx_objects.append(
                [
                    "AnimationCurve",
                    [
                        curve_id,
                        f"{node['node_name']}_{i}_DeformPercent::AnimCurve",
                        "",
                    ],
                    "LSS",
                    [
                        ["Default", [0.0], "D", []],
                        ["KeyVer", [4009], "I", []],
                        ["KeyTime", [times], "l", []],
                        ["KeyValueFloat", [vals], "f", []],
                        ["KeyAttrFlags", [flags], "i", []],
                        ["KeyAttrDataFloat", [attr_data], "f", []],
                        ["KeyAttrRefCount", [refs], "i", []],
                    ],
                ]
            )
            fbx_connections.append(
                ["C", ["OP", curve_id, curve_node_id, "d"], "SLLS", []]
            )
        return fbx_objects, fbx_connections

    # -- entry point -------------------------------------------------------

    def assemble(self, nodes):
        animation_layer_id = self.uid_gen.next()
        anim_stack_id = self.uid_gen.next()

        objects = []
        connections = []
        max_frame = 100.0

        for node in nodes:
            nt = node["node_type"]
            if nt not in ("fram", "joint", "locator", "mesh"):
                continue

            props70, model_type = self._build_model_transform_props(node)
            model_id = node["id"]
            model_name = f'{node["node_name"]}::Model'
            objects.append(
                [
                    "Model",
                    [model_id, model_name, model_type],
                    "LSS",
                    [
                        ["Version", [232], "I", []],
                        ["Properties70", [], "", props70],
                        ["Shading", ["Y"], "C", []],
                        ["Culling", ["CullingOff"], "S", []],
                    ],
                ]
            )
            connections.append(
                ["C", ["OO", model_id, node.get("parent_id") or 0], "SLL", []]
            )

            if nt == "mesh":
                geom_id = self.uid_gen.next()
                mat_data_list = node.get("materials_data", [])
                mat_objects, mat_connections = self._build_material_objects(
                    node, model_id
                )
                objects.extend(mat_objects)
                connections.extend(mat_connections)
                objects.append(
                    self._build_mesh_geometry_object(node, geom_id, mat_data_list)
                )
                connections.append(["C", ["OO", geom_id, model_id], "SLL", []])

                bs_objs, bs_conns = self._build_mesh_blendshape_data(
                    node, geom_id, animation_layer_id
                )
                objects.extend(bs_objs)
                connections.extend(bs_conns)
                for ch in node.get("mesh_animations") or []:
                    if ch["frames"]:
                        max_frame = max(max_frame, ch["frames"][-1])

            if node.get("with_animation"):
                anim_objs, anim_conns = self._build_animation_data(
                    node, model_id, animation_layer_id
                )
                objects.extend(anim_objs)
                connections.extend(anim_conns)
                # Deliberately NOT counted towards `max_frame`: unlike
                # MESH_ANIM (see above - genuinely truncated at the old
                # fixed 100-frame LocalStop, e.g. the crate's 120-frame
                # clip), FRAM/JOIN curves were already playing correctly
                # under that same fixed LocalStop before gotcha #25/#26 -
                # nothing about them needed a longer timeline. A character
                # rig's JOIN curves can span a much wider raw keyframe
                # range than any single clip actually needs (multiple
                # baked-together clips with long gaps between their own
                # dense key clusters - confirmed on `baby_new2_2660`:
                # letting FRAM/JOIN drive `max_frame` stretched LocalStop
                # from 100 to 1398 frames, turning what used to be a
                # sensible ~4s default playback/scrub range into a
                # 58-second one dominated by mostly-static gaps, which
                # reads as "the animation broke" even though every curve's
                # own values are unchanged and correct).

        objects.append(
            ["AnimationLayer", [animation_layer_id, "BaseLayer::AnimLayer", ""], "LSS", []]
        )
        objects.append(
            [
                "AnimationStack",
                [anim_stack_id, "Take 001::AnimStack", ""],
                "LSS",
                [
                    [
                        "Properties70",
                        [],
                        "",
                        [
                            ["P", ["LocalStart", "KTime", "Time", "", 0], "SSSSL", []],
                            [
                                "P",
                                [
                                    "LocalStop",
                                    "KTime",
                                    "Time",
                                    "",
                                    # Gotcha #25: used to be a hardcoded 100
                                    # frames - MESH_ANIM clips can run past
                                    # that (up to 120 frames confirmed on
                                    # real assets), which would silently
                                    # truncate the playback range. Now the
                                    # real max keyframe across every node's
                                    # FRAM/JOIN *and* mesh-vertex animation
                                    # is tracked above and used instead
                                    # (still floored at 100 so short/static
                                    # scenes keep the same range as before).
                                    int(max_frame * KTIME_PER_FRAME),
                                ],
                                "SSSSL",
                                [],
                            ],
                        ],
                    ]
                ],
            ]
        )
        connections.append(["C", ["OO", animation_layer_id, anim_stack_id], "SLL", []])

        out = []
        out.extend(self._generate_fbx_header_json())
        out.extend(self._generate_fbx_definitions(objects))
        out.append(["Objects", [], "", objects])
        out.append(["Connections", [], "", connections])
        out.append(
            [
                "Takes",
                [],
                "",
                [
                    ["Current", ["Take 001"], "S", []],
                    [
                        "Take",
                        ["Take 001"],
                        "S",
                        [["FileName", ["Take_001.tak"], "S", []]],
                    ],
                ],
            ]
        )
        return out


class UidGen:
    def __init__(self, start=10_000_000_000):
        self.v = int(start)

    def next(self):
        self.v += 1
        return self.v


# =============================================================================
# CLI
# =============================================================================


def main():
    global DEBUG
    args = sys.argv[1:]
    if "--debug" in args:
        DEBUG = True
        nmf_scene_converter.DEBUG = True
        args = [a for a in args if a != "--debug"]

    if len(args) < 2:
        sys.stderr.write(
            f"Usage: python {sys.argv[0]} [--debug] input.nmf output.fbx\n"
        )
        return 1

    input_path = args[0]
    output_path = args[1]

    debug_output(f"Reading {input_path}...")
    uid_gen = UidGen(start=1776339759000)
    parser = Nmf()
    raw_nodes = parser.unpack(input_path)

    debug_output("Processing scene nodes...")
    input_dir = os.path.dirname(os.path.abspath(input_path))
    textures_dir = NmfSceneConverter.find_textures_dir(input_dir)
    if textures_dir:
        debug_output(f"[texture] found textures directory {textures_dir}")
    else:
        textures_dir = os.path.join(input_dir, "textures")
        debug_output(
            f"[texture] no textures directory found above {input_dir} - "
            f"falling back to {textures_dir}"
        )
    page_manifest = NmfSceneConverter.load_texture_page_manifest(input_dir)
    converter = NmfSceneConverter(uid_gen, textures_dir, page_manifest)
    scene_nodes = converter.convert(raw_nodes)

    debug_output("Building FBX structure...")
    assembler = FbxSceneAssembler(uid_gen)
    fbx_list_structure = assembler.assemble(scene_nodes)

    writer = FbxBinaryWriter()
    writer.write(fbx_list_structure, output_path)

    debug_output("Done.")
    return 0


if __name__ == "__main__":
    main()
