# WLD File Tools

Scripts to unpack and repack **WLD** files for *The Sting!* (*Der Clou 2*, *Ва-банк*).

---

## Installation

1. **Install Ruby**

   * **Windows:** use [RubyInstaller](https://rubyinstaller.org/downloads/).
2. **Clone the repository**

   ```bash
   git clone <your-repo-url>
   cd script_project
   ```

---

## Usage

### Unpack a WLD file

Copy your `.WLD` file into the script directory and run:

```bash
ruby unpack.rb
```

### Pack files into a WLD file

From the script directory:

```bash
ruby pack.rb
```

---

## Texture Page Files

`path_to_unpacked_files/pack/texture_pages.yml` describes all unpacked texture pages and **is required** for repacking.

### Editing a texture page in GIMP

* **Compression:** None
* **Format:** RGB5A1
* **Save:** All visible layers
* **Mipmaps:** No
* **Max size:** **512 × 512 px**

---

## Binary Formats

All multi‑byte integers are little‑endian unless explicitly marked **(BE)** for Big‑Endian. Fixed string markers include spaces if shown (e.g., `"END "`).
Files use Windows‑1252 encoding for strings.

### Conventions

* **name**: null‑terminated Windows‑1252 string, padded with `\0` to a 4‑byte boundary.
* **Markers**: fixed 4‑byte ASCII; some include trailing space (e.g., `"END "`).
* **Endianness**: integers are little‑endian unless explicitly stated.
* **Unknown fields**: listed as *Unknown*; hints are provided as “possibly …” when reasonable.

---

## WLD Container

### WLD File (top‑level)

| Field  | Type / Size     | Description                               |
| ------ | --------------- | ----------------------------------------- |
| `WRLD` | `const char[4]` | File type identifier `"WRLD"`.            |
| `zero` | `int32`         | Always `0`.                               |
| `data` | —               | WLD payload (see **WLD Data Block**).     |
| `EOF ` | `const char[4]` | End‑of‑file marker (note trailing space). |
| `zero` | `int32`         | Always `0`.                               |

### WLD Data Block

| Field    | Type / Size     | Description                                                  |
| -------- | --------------- | ------------------------------------------------------------ |
| `MARKER` | `const char[4]` | Section type (see **Supported MARKERs**).                    |
| `zero`   | `int32`         | Always `0`.                                                  |
| `array`  | —               | Array of section items separated by item markers (per type). |
| `END `   | `const char[4]` | End‑of‑data marker (note trailing space).                    |
| `zero`   | `int32`         | Always `0`.                                                  |

### Supported MARKERs

| MARKER | Description              | Array Item Separator |
| ------ | ------------------------ | -------------------- |
| `TEXP` | Texture Pages            | `PAGE`               |
| `GROU` | Model List Tree Folders  | `ENTR`               |
| `OBGR` | Object List Tree Folders | `ENTR`               |
| `LIST` | Model List               | `MODL`               |
| `OBJS` | Object List              | `"OBJ "`             |
| `MAKL` | Macro List               | `"OBJ "`             |
| `TREE` | World Tree               | `NODE`               |

---

## Texture Pages (`TEXP`)

### Texture Page (`PAGE`)

> `size` is stored in **Big‑Endian**.

| Field           | Type / Size     | Description                                                  |
| --------------- | --------------- | ------------------------------------------------------------ |
| `PAGE`          | `const char[4]` | Page marker.                                                 |
| `size`          | `int32 (BE)`    | Page block size in bytes.                                    |
| `2`             | `int32`         | Constant `2`.                                                |
| `width`         | `int32`         | Page width (px).                                             |
| `height`        | `int32`         | Page height (px).                                            |
| `id`            | `int32`         | Texture page id (1‑based: page index).                       |
| `texture_count` | `int32`         | Number of sub‑textures on the page.                          |
| `texture_info`  | —               | Array of **Texture Info** entries.                           |
| `TXPG`          | `const char[4]` | End marker for texture info array.                           |
| `has_alpha`     | `bool (int32)`  | Has alpha channel.                                           |
| `PIXELS`        | `DDS blob`      | Uncompressed **DDS pixel data without header** for the page. |

### Texture Info

| Field       | Type / Size | Description                              |
| ----------- | ----------- | ---------------------------------------- |
| `filepath`  | `char[]`    | Null‑terminated string (4‑byte aligned). |
| `x0`        | `int32`     | Top‑left X on page.                      |
| `y0`        | `int32`     | Top‑left Y on page.                      |
| `x2`        | `int32`     | Bottom‑right X on page.                  |
| `y2`        | `int32`     | Bottom‑right Y on page.                  |
| `source_x0` | `int32`     | Source crop top‑left X.                  |
| `source_y0` | `int32`     | Source crop top‑left Y.                  |
| `source_x2` | `int32`     | Source crop bottom‑right X.              |
| `source_y2` | `int32`     | Source crop bottom‑right Y.              |

---

## Model / Object Trees — Folders

### Model List Tree Folder (`GROU` → `ENTR`)

> `size` is stored in **Big‑Endian**.

| Field       | Type / Size     | Description                                          |
| ----------- | --------------- | ---------------------------------------------------- |
| `ENTR`      | `const char[4]` | Entry marker.                                        |
| `size`      | `int32 (BE)`    | Entry size.                                          |
| `0`         | `int32`         | Constant `0`.                                        |
| `name`      | `char[]`        | Entry name. Null‑terminated string (4‑byte aligned). |
| `parent_id` | `int32`         | Parent folder entry id (2‑based index).              |
| `alignment` | padding         | `\0` padding to 4‑byte boundary for strings.         |

### Object List Tree Folder (`OBGR` → `ENTR`)

Same structure as **Model List Tree Folder**.

---

## Model List (`LIST` → `MODL`)

| Field                    | Type / Size      | Description                                                |
| ------------------------ | ---------------- | ---------------------------------------------------------- |
| `MODL`                   | `const char[4]`  | Model entry marker.                                        |
| `size`                   | `int32 (BE)`     | Entry size.                                                |
| `9`                      | `int32`          | Constant `9`.                                              |
| `1`                      | `int32`          | Constant `1`.                                              |
| `name`                   | `char[]`         | Model name (may be non‑unique). Null‑terminated (aligned). |
| `parent_id`              | `int32`          | Parent entry id (2‑based index).                           |
| `influences_camera`      | `bool (int32)`   | `-1` = yes, `0` = no.                                      |
| `no_camera_check`        | `bool (int32)`   | `-1` = disable check, `0` = default.                       |
| `anti_ground`            | `bool (int32)`   | `-1` = ignore ground, `0` = default.                       |
| `default_skeleton`       | `bool (int32)`   | `-1` = use default skeleton, `0` = no.                     |
| `use_skeleton`           | `bool (int32)`   | `-1` = use skeleton, `0` = no.                             |
| `camera`                 | `const char[4]`  | `"RMAC"` if camera present, otherwise zeroed.              |
| `camera_struct`          | `struct CAMERA`  | Present if `camera == 'RMAC'`.                             |
| `parent_folder_id`       | `int32`          | Folder id from Model List Tree Folders.                    |
| `count_of_attack_points` | `int32`          | Number of `ATTACK_POINT` entries.                          |
| `attack_points`          | `ATTACK_POINT[]` | Present if `count_of_attack_points > 0`.                   |
| `NMF`                    | `struct NMF`     | Embedded model data (see **NMF Model Format**).            |

#### CAMERA

| Field                | Type / Size | Description            |
| -------------------- | ----------- | ---------------------- |
| `coordinates_camera` | `float[5]`  | `x, y, z, pitch, yaw`. |
| `coordinates_item`   | `float[5]`  | `x, y, z, pitch, yaw`. |

#### ATTACK\_POINT

| Field    | Type / Size | Description   |
| -------- | ----------- | ------------- |
| `x`      | `float`     | X coordinate. |
| `y`      | `float`     | Y coordinate. |
| `z`      | `float`     | Z coordinate. |
| `radius` | `float`     | Radius.       |

---

## NMF Model Format

### NMF File (embedded)

| Field      | Type / Size     | Description                                        |
| ---------- | --------------- | -------------------------------------------------- |
| `NMF `     | `const char[4]` | Model header (note trailing space).                |
| `zero`     | `int32`         | Always `0`.                                        |
| `ROOT`     | `struct ROOT`   | Root element.                                      |
| `children` | array           | Zero or more of `LOCA` / `FRAM` / `JOIN` / `MESH`. |
| `END `     | `const char[4]` | End marker (note trailing space).                  |
| `zero`     | `int32`         | Always `0`.                                        |

### ROOT

> `size` is **Big‑Endian**.

| Field       | Type / Size     | Description                           |
| ----------- | --------------- | ------------------------------------- |
| `ROOT`      | `const char[4]` | Marker.                               |
| `size`      | `int32 (BE)`    | Block size.                           |
| `2`         | `int32`         | Constant `2`.                         |
| `parent_id` | `int32`         | Always `0` for root.                  |
| `name`      | `char[]`        | Node name. Null‑terminated (aligned). |
| `data`      | `byte[164]`     | Fixed data (purpose unknown).         |

### LOCA

> `size` is **Big‑Endian**.

| Field       | Type / Size     | Description                           |
| ----------- | --------------- | ------------------------------------- |
| `LOCA`      | `const char[4]` | Marker.                               |
| `size`      | `int32 (BE)`    | Block size.                           |
| `0`         | `int32`         | Constant `0`.                         |
| `parent_id` | `int32`         | Parent id.                            |
| `name`      | `char[]`        | Node name. Null‑terminated (aligned). |

### FRAM

> `size` is **Big‑Endian**.

| Field                    | Type / Size     | Description                                                     |
| ------------------------ | --------------- | --------------------------------------------------------------- |
| `FRAM`                   | `const char[4]` | Marker.                                                         |
| `size`                   | `int32 (BE)`    | Block size.                                                     |
| `2`                      | `int32`         | Constant `2`.                                                   |
| `parent_id`              | `int32`         | Parent id.                                                      |
| `name`                   | `char[]`        | Node name. Null‑terminated (aligned).                           |
| `matrix`                 | `float[16]`     | 4×4 transform.                                                  |
| `translation`            | `float[3]`      | Translation.                                                    |
| `scaling`                | `float[3]`      | Scale.                                                          |
| `rotation`               | `float[3]`      | Rotation.                                                       |
| `rotate_pivot_translate` | `float[3]`      | Rotate pivot translation.                                       |
| `rotate_pivot`           | `float[3]`      | Rotate pivot.                                                   |
| `scale_pivot_translate`  | `float[3]`      | Scale pivot translation.                                        |
| `scale_pivot`            | `float[3]`      | Scale pivot.                                                    |
| `shear`                  | `float[3]`      | Shear.                                                          |
| `ANIM`                   | `const char[4]` | Present and equals `"ANIM"` if animation follows (else zeroed). |
| `anim`                   | `struct ANIM`   | Present if above condition is true.                             |

### JOIN

> `size` is **Big‑Endian**.

| Field             | Type / Size     | Description                                                     |
| ----------------- | --------------- | --------------------------------------------------------------- |
| `JOIN`            | `const char[4]` | Marker.                                                         |
| `size`            | `int32 (BE)`    | Block size.                                                     |
| `2`               | `int32`         | Constant `2`.                                                   |
| `parent_id`       | `int32`         | Parent id.                                                      |
| `name`            | `char[]`        | Joint name. Null‑terminated (aligned).                          |
| `matrix`          | `float[16]`     | 4×4 transform.                                                  |
| `translation`     | `float[3]`      | Translation.                                                    |
| `scaling`         | `float[3]`      | Scale.                                                          |
| `rotation`        | `float[3]`      | Rotation.                                                       |
| `rotation_matrix` | `float[16]`     | 4×4 rotation.                                                   |
| `min_rot_limit`   | `float[3]`      | Min rotation limits.                                            |
| `max_rot_limit`   | `float[3]`      | Max rotation limits.                                            |
| `ANIM`            | `const char[4]` | Present and equals `"ANIM"` if animation follows (else zeroed). |
| `anim`            | `struct ANIM`   | Present if above condition is true.                             |

### ANIM (node animation)

| Field                        | Type / Size  | Description                              |
| ---------------------------- | ------------ | ---------------------------------------- |
| `flag`                       | `bool (int)` | Unknown flag.                            |
| `translation_sizes`          | `int32[3]`   | Key counts for X/Y/Z.                    |
| `scaling_sizes`              | `int32[3]`   | Key counts for X/Y/Z.                    |
| `rotation_sizes`             | `int32[3]`   | Key counts for X/Y/Z.                    |
| `translation_curve_values_*` | `float[]`    | Values for each axis; lengths per sizes. |
| `translation_curve_keys_*`   | `int32[]`    | Key indices per axis.                    |
| `scaling_curve_values_*`     | `float[]`    | Values for each axis; lengths per sizes. |
| `scaling_curve_keys_*`       | `int32[]`    | Key indices per axis.                    |
| `rotation_curve_values_*`    | `float[]`    | Values for each axis; lengths per sizes. |
| `rotation_curve_keys_*`      | `int32[]`    | Key indices per axis.                    |

### MESH

> `size` is **Big‑Endian**.

| Field                     | Type / Size                | Description                           |
| ------------------------- | -------------------------- | ------------------------------------- |
| `MESH`                    | `const char[4]`            | Marker.                               |
| `size`                    | `int32 (BE)`               | Block size.                           |
| `14`                      | `int32`                    | Constant `14`.                        |
| `parent_id`               | `int32`                    | Parent id.                            |
| `name`                    | `char[]`                   | Mesh name. Null‑terminated (aligned). |
| `tnum`                    | `int32`                    | Triangle count.                       |
| `vnum`                    | `int32`                    | Vertex count.                         |
| `vbuf`                    | `float[vnum*10]`           | Vertex attributes (10 floats/vertex). |
| `uvpt`                    | `float[vnum*2]`            | UVs (2 floats/vertex).                |
| `inum`                    | `int32`                    | Index count.                          |
| `ibuf`                    | `int16[inum]`              | Indices (16‑bit).                     |
| `zero_pad`                | `int16`                    | Present if `inum` is odd.             |
| `backface_culling`        | `int32`                    | Culling flag.                         |
| `complex`                 | `int32`                    | Complexity flag.                      |
| `inside`                  | `int32`                    | Inside flag.                          |
| `smooth`                  | `int32`                    | Smooth shading flag.                  |
| `light_flare`             | `int32`                    | Light flare flag.                     |
| `material_count`          | `int32`                    | Number of materials.                  |
| `materials`               | `MATERIAL[material_count]` | Material array.                       |
| `mesh_anim_array`         | `MESH_ANIM[]`              | Mesh animation blocks (optional).     |
| `unknown_count_of_floats` | `int32`                    | Count.                                |
| `unknown_floats`          | `float[]`                  | Extra float payload.                  |
| `unknown_count_of_ints`   | `int32`                    | Count.                                |
| `unknown_ints`            | `int32[]`                  | Extra int payload.                    |

#### MATERIAL (`MTRL`)

| Field                         | Type / Size     | Description                                          |
| ----------------------------- | --------------- | ---------------------------------------------------- |
| `MTRL`                        | `const char[4]` | Marker.                                              |
| `name`                        | `char[]`        | Material name. Null‑terminated (aligned).            |
| `unknown_ints`                | `int32[4]`      | Unknown usage.                                       |
| `uv_flip_h`                   | `int32`         | Horizontal flip flag.                                |
| `uv_flip_v`                   | `int32`         | Vertical flip flag.                                  |
| `rotate`                      | `int32`         | Rotation flag/value.                                 |
| `horizontal_stretch`          | `float`         | Horizontal stretch.                                  |
| `vertical_stretch`            | `float`         | Vertical stretch.                                    |
| `red, green, blue, alpha`     | `float ×4`      | RGBA.                                                |
| `red2, green2, blue2, alpha2` | `float ×4`      | Secondary RGBA.                                      |
| `unknown_zero_ints`           | `int32[9]`      | Typically zero.                                      |
| `TXPG/TEXT/0000`              | `const char[4]` | Texture ref kind: `"TXPG"` / `"TEXT"` or four zeros. |

##### TEXTURE (when `TXPG`)

| Field                   | Type / Size | Description                              |
| ----------------------- | ----------- | ---------------------------------------- |
| `name`                  | `char[]`    | Texture path. Null‑terminated (aligned). |
| `texture_page`          | `int32`     | Page id.                                 |
| `index_texture_on_page` | `int32`     | Index within page.                       |
| `x0, y0, x2, y2`        | `int32 ×4`  | Atlas rect.                              |

##### TEXT (when `TEXT`)

| Field  | Type / Size | Description                                           |
| ------ | ----------- | ----------------------------------------------------- |
| `name` | `char[]`    | File path (text resource). Null‑terminated (aligned). |

#### MESH\_ANIM (per‑mesh)

| Field                  | Type / Size     | Description                     |
| ---------------------- | --------------- | ------------------------------- |
| `ANIM`                 | `const char[4]` | Marker.                         |
| `unknown_bool`         | `int32`         | Flag.                           |
| `unknown_size_of_ints` | `int32`         | Count of following ints.        |
| `unknown_ints`         | `int32[]`       | Payload.                        |
| `unknown_floats3`      | `float[3]`      | Three floats.                   |
| `s1, s2, s3`           | `int32 ×3`      | Sizes for float arrays.         |
| `unknown_floats1`      | `float[s1]`     | Payload.                        |
| `unknown_floats2`      | `float[s2]`     | Payload.                        |
| `unknown_floats3_arr`  | `float[s3]`     | Payload.                        |
| `ANIM (end)`           | `const char[4]` | May repeat for multiple blocks. |

---

## Objects (`OBJS` → `"OBJ "`)

### Object Entry (`"OBJ "`)

> `size` is **Big‑Endian**.

| Field             | Type / Size         | Description                                                |
| ----------------- | ------------------- | ---------------------------------------------------------- |
| `"OBJ "`          | `const char[4]`     | Marker.                                                    |
| `size`            | `int32 (BE)`        | Entry size.                                                |
| `type`            | `int32`             | Object type id.                                            |
| `name`            | `char[]`            | Object name. Null‑terminated (aligned).                    |
| `parent_id`       | `int32`             | Parent folder id from Object Tree Folders (2‑based index). |
| `animation_count` | `int32`             | Count of `ObjectAnimation`.                                |
| `animations`      | `ObjectAnimation[]` | Animation array.                                           |
| `INFO`            | `INFO`              | Info block (see below).                                    |

#### ObjectAnimation

| Field                     | Type / Size                | Description                                |
| ------------------------- | -------------------------- | ------------------------------------------ |
| `name`                    | `char[]`                   | Animation name. Null‑terminated (aligned). |
| `unknown1`                | `int32 or float`           | Possibly animation speed.                  |
| `unknown2`                | `float`                    | Possibly duration or time offset.          |
| `unknown3`                | `int32 or float`           | Possibly animation type / loop flag.       |
| `unknown4`                | `int32`                    | Possibly time scale.                       |
| `unknown5`                | `float`                    | Often `-100.0` (sentinel).                 |
| `unknown6`                | `bool (int32)`             | Flag (e.g., has position keys).            |
| `unknown7`                | `bool (int32)`             | Flag (e.g., has rotation keys).            |
| `unknown_animation_count` | `int32`                    | Count of `UnknownObjectAnimation`.         |
| `sub`                     | `UnknownObjectAnimation[]` | Sub‑animations (e.g., per‑bone).           |

##### UnknownObjectAnimation

| Field      | Type / Size | Description                                    |
| ---------- | ----------- | ---------------------------------------------- |
| `name`     | `char[]`    | Sub‑animation name. Null‑terminated (aligned). |
| `unknown1` | `float`     | Possibly blend weight.                         |

---

## INFO Block

### INFO (root)

| Field    | Type / Size     | Description                            |
| -------- | --------------- | -------------------------------------- |
| `INFO`   | `const char[4]` | Marker.                                |
| `size`   | `int32 (BE)`    | Block size including trailing.         |
| `int1`   | `int32`         | Unknown.                               |
| `int2`   | `int32`         | Unknown.                               |
| `int3`   | `int32`         | Unknown.                               |
| `OPTS`   | `OPTS`          | Options.                               |
| `DIALOG` | `COND`          | Dialog block.                          |
| `CUSTOM` | variant         | Extra fields depending on `OPTS.type`. |
| `TALI`   | `TALI`          | Task list.                             |
| `END `   | `const char[4]` | Terminator.                            |
| `zero`   | `int32`         | Always `0`.                            |

### OPTS

| Field                  | Type / Size     | Description                            |
| ---------------------- | --------------- | -------------------------------------- |
| `OPTS`                 | `const char[4]` | Marker.                                |
| `size`                 | `int32 (BE)`    | Payload size.                          |
| `int1`                 | `int32`         | Unknown.                               |
| `id`                   | `char[]`        | Identifier. Null‑terminated (aligned). |
| `type`                 | `int32`         | Info type (see below).                 |
| `story`                | `int32`         | Story object flag.                     |
| `clickable`            | `bool (int32)`  | Clickable.                             |
| `process_when_visible` | `bool (int32)`  | Process only when visible.             |
| `process_always`       | `bool (int32)`  | Process always.                        |
| `info`                 | variant         | One of sub‑structures by `type`.       |

#### OPTS: Types & Sub‑Structures

| Type | Meaning               | Struct        |
| ---- | --------------------- | ------------- |
| 0    | Item                  | `item`        |
| 1    | Item — Loot           | `item_loot`   |
| 2    | Item — Tool           | `item_tool`   |
| 3    | Passage / Real estate | `passage`     |
| 4    | Character A           | `character_a` |
| 5,6  | Character B / C       | `character_b` |
| 7,8  | Passage (Door/Window) | `passage`     |
| 9    | Car                   | `car`         |

##### `item` (type = 0)

| Field    | Type / Size | Description |
| -------- | ----------- | ----------- |
| `weight` | `float`     | Weight.     |

##### `item_loot` (type = 1)

| Field    | Type / Size | Description |
| -------- | ----------- | ----------- |
| `weight` | `float`     | Weight.     |
| `value`  | `float`     | Value.      |

##### `item_tool` (type = 2)

**Base**

| Field        | Type / Size | Description              |
| ------------ | ----------- | ------------------------ |
| `weight`     | `float`     | Weight.                  |
| `value`      | `float`     | Value.                   |
| `strength`   | `float`     | Strength.                |
| `pick_locks` | `float`     | Lockpicking.             |
| `pick_safes` | `float`     | Safe‑cracking.           |
| `alarm_sys`  | `float`     | Always `0.0`.            |
| `volume`     | `float`     | Always `0.0`.            |
| `damaging`   | `float`     | Negative means damaging. |

**Effectiveness**

| Field     | Type / Size | Description |
| --------- | ----------- | ----------- |
| `glass`   | `float`     | Vs glass.   |
| `wood`    | `float`     | Vs wood.    |
| `steel`   | `float`     | Vs steel.   |
| `hi_tech` | `float`     | Vs hi‑tech. |

**Noise**

| Field     | Type / Size | Description       |
| --------- | ----------- | ----------------- |
| `glass`   | `float`     | Noise on glass.   |
| `wood`    | `float`     | Noise on wood.    |
| `steel`   | `float`     | Noise on steel.   |
| `hi_tech` | `float`     | Noise on hi‑tech. |

##### `passage` (types = 3, 7, 8)

* Type 3: Real estate
* Type 7: Passage — Door
* Type 8: Passage — Window

| Field          | Type / Size | Description    |
| -------------- | ----------- | -------------- |
| `working_time` | `float`     | Work time.     |
| `material`     | `int32`     | Material type. |
| `crack_type`   | `int32`     | Crack type.    |

##### `character_a` (type = 4)

| Field        | Type / Size | Description                            |
| ------------ | ----------- | -------------------------------------- |
| `speed`      | `float`     | Movement speed.                        |
| `occupation` | `char[]`    | Occupation. Null‑terminated (aligned). |

##### `character_b` (types = 5, 6)

| Field   | Type / Size | Description     |
| ------- | ----------- | --------------- |
| `speed` | `float`     | Movement speed. |

##### `car` (type = 9)

| Field          | Type / Size | Description   |
| -------------- | ----------- | ------------- |
| `transp_space` | `float`     | Capacity.     |
| `max_speed`    | `float`     | Max speed.    |
| `acceleration` | `float`     | Acceleration. |
| `value`        | `float`     | Value.        |
| `driving`      | `float`     | Handling.     |

### COND (Dialog)

| Field     | Type / Size     | Description                     |
| --------- | --------------- | ------------------------------- |
| `COND`    | `const char[4]` | Marker.                         |
| `size`    | `int32 (BE)`    | Payload size.                   |
| `flag`    | `int32`         | Always `6`.                     |
| `opt`     | `int32`         | Optional (present if size = 8). |
| `count`   | `int32`         | Number of entries.              |
| `entries` | array           | Dialog entries (see below).     |

**Dialog Entry**

| Field         | Type / Size | Description                                   |
| ------------- | ----------- | --------------------------------------------- |
| `active`      | `int32`     | Active flag.                                  |
| `Q`           | `char[]`    | Question. Null‑terminated (aligned).          |
| `A`           | `char[]`    | Answer. Null‑terminated (aligned).            |
| `Dlg-`        | `char[]`    | Negative branch. Null‑terminated (aligned).   |
| `Dlg+`        | `char[]`    | Positive branch. Null‑terminated (aligned).   |
| `Always-`     | `char[]`    | Condition Always‑. Null‑terminated (aligned). |
| `Always+`     | `char[]`    | Condition Always+. Null‑terminated (aligned). |
| `Always`      | `int32`     | Always flag.                                  |
| `Story`       | `int32`     | Story flag.                                   |
| `Coohess`     | `int32`     | Coohess.                                      |
| `DialogEvent` | `int32`     | Dialog event.                                 |

**CUSTOM tail (by type)**

| Type(s) | Extra Fields                                    |
| ------- | ----------------------------------------------- |
| 7, 8    | `open:int32`, `locked:int32`                    |
| 3       | `open:int32`, `locked:int32`, `active:int32`    |
| 4       | `open:int32`, `locked:int32`, `values:float[8]` |

### TALI (Task List)

| Field     | Type / Size       | Description                            |
| --------- | ----------------- | -------------------------------------- |
| `TALI`    | `const char[4]`   | Marker.                                |
| `size`    | `int32`           | Payload size + 8 (for `END ` + `0`).   |
| `zero`    | `int32`           | Always `0`.                            |
| `entries` | `[TASK or DPND]*` | Sequence of task or dependency blocks. |
| `END `    | `const char[4]`   | Terminator.                            |
| `zero`    | `int32`           | Always `0`.                            |

#### TASK

| Field      | Type / Size     | Description           |
| ---------- | --------------- | --------------------- |
| `TASK`     | `const char[4]` | Marker.               |
| `size`     | `int32 (BE)`    | Payload size.         |
| `int1`     | `int32`         | Unknown.              |
| `int2`     | `int32`         | Unknown.              |
| `task_id`  | `int32`         | Identifier.           |
| `default`  | `bool (int)`    | Default flag.         |
| `critical` | `bool (int)`    | Critical flag.        |
| `count`    | `int32`         | Parameter count.      |
| `params`   | variant         | Parameters (by type). |

**Parameter Variants**

| Param Type   | Payload            |
| ------------ | ------------------ |
| `2`          | `float[3]`         |
| `3`          | `float`            |
| `4,5,8,9,10` | `int32`            |
| `6,12,16`    | `char[]` (aligned) |
| `7`          | `ACOD` (4×`int32`) |
| `15`         | `byte[36]`         |

#### DPND (Dependency)

| Field     | Type / Size     | Description                         |
| --------- | --------------- | ----------------------------------- |
| `DPND`    | `const char[4]` | Marker.                             |
| `size`    | `int32`         | Payload size.                       |
| `int1`    | `int32`         | Unknown.                            |
| `ACOD`    | `struct`        | 4×`int32`.                          |
| `ints4`   | `int32[4]`      | Array.                              |
| `TALI**`  | `struct`        | Nested task list.                   |
| `ints9`   | `int32[9]`      | Array.                              |
| `type`    | `int32`         | Branch type.                        |
| `variant` | `int32[]`       | Extra ints (2 or 4 by type 1 or 2). |

#### ACOD

| Field  | Type / Size | Description    |
| ------ | ----------- | -------------- |
| `ints` | `int32[4]`  | Four integers. |

---

## World Tree (`TREE` → `NODE`)

### TREE Container

| Field   | Type / Size     | Description        |
| ------- | --------------- | ------------------ |
| `TREE`  | `const char[4]` | Container marker.  |
| `size`  | `int32 (BE)`    | Payload size.      |
| `NODEs` | array           | Sequence of nodes. |

### NODE

| Field     | Type / Size | Description            |
| --------- | ----------- | ---------------------- |
| `15`      | `int32`     | Constant `15`.         |
| `base`    | `struct`    | **World Base Fields**. |
| `by_type` | variant     | Extra fields per type. |

#### World Base Fields

| Field              | Type / Size | Description                             |
| ------------------ | ----------- | --------------------------------------- |
| `parent_id`        | `int32`     | Parent id.                              |
| `folder_name`      | `char[]`    | Folder name. Null‑terminated (aligned). |
| `x, y, z, w, n, u` | `float ×6`  | Coordinates/params.                     |
| `unknown1`         | `int32`     | Flag/code.                              |
| `type`             | `int32`     | Node type (`0–3`).                      |
| `item`             | variant     | Fields by type.                         |

#### `by_type` Variants

| Type | Payload                                          |
| ---- | ------------------------------------------------ |
| `0`  | Four `int32` = `0, 0, 0, 0`.                     |
| `1`  | See **World Model**.                             |
| `2`  | `object_id:int32`, `INFO` (or `0`), terminators. |
| `3`  | Light parameters (floats + ints).                |

#### World Model (type = 1)

| Field               | Type / Size     | Description                                 |
| ------------------- | --------------- | ------------------------------------------- |
| `model_id`          | `int32`         | —                                           |
| `connections_count` | `int32`         | Count of connections to other ground items. |
| `connections`       | `connection[]`  | Array of connections.                       |
| `zero`              | `int32`         | Always `0`.                                 |
| `SHAD`              | `const char[4]` | `"SHAD"` or `\0\0\0\0`.                     |
| `shadows`           | `shadow`        | Present when `SHAD` is set.                 |

##### connection

| Field  | Type / Size | Description                         |
| ------ | ----------- | ----------------------------------- |
| `to`   | `int32`     | Target world item id (index‑based). |
| `flag` | `int32`     | `0` or `-1`.                        |

##### shadow

| Field   | Type / Size | Description                            |
| ------- | ----------- | -------------------------------------- |
| `size1` | `int32`     | —                                      |
| `size2` | `int32`     | —                                      |
| `data`  | `blob`      | Blob size = `(size1 * size2 + 1) / 2`. |

##### World Object (type = 2)

| Field       | Type / Size | Description           |
| ----------- | ----------- | --------------------- |
| `object_id` | `int32`     | —                     |
| `zero`      | `int32`     | —                     |
| `INFO`      | `INFO`      | `INFO` or `\0\0\0\0`. |
| `zero`      | `int32`     | Always `0`.           |

##### World Light (type = 3)

| Field              | Type / Size | Description |
| ------------------ | ----------- | ----------- |
| `unknown1`         | `int32`     | —           |
| `unknown_floats11` | `float[11]` | —           |
| `unknown2`         | `int32`     | —           |
| `unknown_floats13` | `float[13]` | —           |
| `unknown3`         | `int32[4]`  | —           |

---

## License

This project is licensed under the [MIT License](LICENSE).
