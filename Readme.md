# WLD File Tools

**This script allows you to unpack and repack WLD files for *The Sting!* (*Der Clou 2*, *Ва-банк*) game**

## Installation

1. **Install Ruby**  
   - For Windows, download Ruby from [RubyInstaller](https://rubyinstaller.org/downloads/).

2. **Clone the Repository**  
   - Clone or download this repository and navigate to the script directory in your terminal:
     ```
     cd script_project
     ```

## Usage

### Unpacking a WLD File
To extract the contents of a WLD file, copy WLD file to script folder and run:
```
ruby unpack.rb
```

### Packing Files into a WLD File
To pack files back into a WLD file, run:
```
ruby pack.rb
```

---

## Texture Page Files

The file located at `path_to_unpacked_files/pack/texture_pages.yml` contains descriptions of the unpacked texture pages and is required for repacking the WLD file.

### Editing a Texture Page
To modify a texture page using GIMP, save it in DDS format with the following settings:
- **Compression:** None  
- **Format:** RGB5A1  
- **Save:** All visible layers  
- **Mipmaps:** No mipmaps

**Note:** The maximum size for a texture page is **512x512 pixels**.

---


# Structure of WLD Game Binary File

### Main Structure of the WLD Game Binary File

| Field | Size              | Description                                           |
|-------|-------------------|-------------------------------------------------------|
| WRLD  | `const char[4]`   | "WRLD". File type identifier.                         |
| zero  | `int`             | A zero value.                                         |
| data  |                   | The main file data.                                   |
| EOF   | `const char[4]`   | "EOF ". End-of-file marker. Note: includes a space.   |
| zero  | `int`             | A zero value.                                         |

---

### Structure of WLD File Data

The data in this format is organized as follows:

| Field   | Size              | Description                                         |
|---------|-------------------|-----------------------------------------------------|
| MARKER  | `const char[4]`   | Identifier for the type of stored data.             |
| zero    | `int`             | A zero value.                                       |
| array   |                   | Array containing the current data type.             |
| END     | `const char[4]`   | "END ". End-of-data marker. Note: includes a space. |
| zero    | `int`             | A zero value.                                       |

---

### List of Supported Data Types

| MARKER Value | Description       | Array Item Separator |
|--------------|-------------------|----------------------|
| TEXP         | Texture Pages     | PAGE                 |
| GROU         | Model List Tree   | ENTR                 |
| OBGR         | Object List Tree  | ENTR                 |
| LIST         | Model List        | MODL                 |
| OBJS         | Object List       | "OBJ "               |
| MAKL         | Macro List        | "OBJ "               |
| TREE         | World Tree        | NODE                 |

---

### Texture Page Structure

| Field              | Size             | Description                                                            |
|--------------------|------------------|------------------------------------------------------------------------|
| PAGE               | `const char[4]`  | Texture page identifier.                                               |
| size               | `int`            | Binary size of the texture page, stored in Big-Endian format.          |
| 2                  | `int`            | Texture page identifier in integer format. Always 2.                   |
| width              | `int`            | Width of the texture page.                                             |
| height             | `int`            | Height of the texture page.                                            |
| iid                | `int`            | Id of the texture page. For id using page index. Start from 1.         |
| texture count      | `int`            | Number of textures contained on the texture page.                      |
| texture info array |                  | Array containing information about textures stored on the texture page.|
| TXPG               | `const char[4]`  | End-of-texture-info array marker.                                      |
| is_alpha           | `int`            | Alpha channel indicator: 0 if none, -1 if present.                     |
| PIXELS             |                  | Pixel data of the texture page, stored in uncompressed DDS file format.|

---

### Texture Info Structure

| Field     | Size            | Description                                                              |
|-----------|-----------------|--------------------------------------------------------------------------|
| Filepath  | `const char*`   | File name with its path, null-terminated (`'\0'`).                       |
| alignment | `const char*`   | Padding array of `'\0'` to align `filepath` to a 4-byte boundary.        |
| x0        | `int`           | Top-left X coordinate of the texture on the texture page.                |
| y0        | `int`           | Top-left Y coordinate of the texture on the texture page.                |
| x2        | `int`           | Bottom-right X coordinate of the texture on the texture page.            |
| y2        | `int`           | Bottom-right Y coordinate of the texture on the texture page.            |
| source_x0 | `int`           | Top-left X coordinate of the cropped texture from the original file.     |
| source_y0 | `int`           | Top-left Y coordinate of the cropped texture from the original file.     |
| source_x2 | `int`           | Bottom-right X coordinate of the cropped texture from the original file. |
| source_y2 | `int`           | Bottom-right Y coordinate of the cropped texture from the original file. |

---

### Model List Tree

| Field      | Size             | Description                                                                              |
|------------|------------------|------------------------------------------------------------------------------------------|
| ENTR       | `const char[4]`  | Model List Tree identifier.                                                              |
| size       | `int`            | Binary size of the Model List Tree, stored in Big-Endian format.                         |
| 0          | `int`            | Model List Tree identifier in integer format. Always zero.                               |
| name       | `const char*`    | Entity name.                                                                             |
| alignment  | `const char*`    | Padding array of `'\0'` to align `filepath` to a 4-byte boundary.                        |
| parent_iid | `int`            | Identifier of the parent entity. For entry index using index of this entry. Start from 2.|

---

### Object List Tree

Same of Model List Tree.

### Model List

| Field                    | Size                      | Description                                                                |
|-------------------------|----------------------------|----------------------------------------------------------------------------|
| MODL                    | const char[4]              | Model List identifier.                                                     |
| size                    | int                        | Binary size of the Model List, stored in Big-Endian format.                |
| 9                       | int                        | Constant value. Always `9`.                                                |
| 1                       | int                        | Constant value. Always `1`.                                                |
| name                    | const char*                | Entity name (not guaranteed to be unique).                                 |
| alignment               | const char*                | Padding array of `'\0'` to align to a 4-byte boundary.                     |
| parent_iid              | int                        | Index of the parent entity. Entry index starts from `2`.                   |
| influences_camera       | int                        | If `-1`, this entity influences the camera; `0` otherwise.                 |
| no_camera_check         | int                        | If `-1`, disables camera check; `0` otherwise.                             |
| anti_ground             | int                        | If `-1`, entity ignores ground collision; `0` otherwise.                   |
| default_skeleton        | int                        | If `-1`, uses a default skeleton; `0` otherwise.                           |
| use_skeleton            | int                        | If `-1`, uses a skeleton; `0` otherwise.                                   |
| camera                  | const char[4]              | `'RMAC'` if a camera struct is present; otherwise zeroed.                  |
| camera struct           | struct camera              | Camera structure. Present if `camera == 'RMAC'`.                           |
| parent_folder_iid       | int                        | Parent folder IID from the Model List Tree.                                |
| count_of_attack_points  | int                        | Number of `attack_points` entries.                                         |
| array of attack_points  | struct attack_points[]     | Array of `attack_points` structs. Present if count > 0.                    |
| NMF                     | struct NMF                 | 3D model data (NMF format).                                                |


---

### Struct Camera

| Field               | Size      | Description                               |
|---------------------|-----------|-------------------------------------------|
| coordinates_camera  | `float[5]`| x, y, z, pitch, yaw coordinate of camera  |
| coordinates_item    | `float[5]`| x, y, z, pitch, yaw coordinate of item    |

---

### Struct AtackPoint

| Field  | Size    | Description                             |
|--------|---------|-----------------------------------------|
| x      | `float` | x coordinate                            |
| y      | `float` | y coordinate                            |
| z      | `float` | z coordinate                            |
| radius | `float` | radius                                  |

Below is the revised markdown documentation for the NMF file format. Each structure is described in detail with clear field names, sizes, and descriptions.

---

## NMF File Structure

This is the top-level structure for the NMF file, which organizes the overall model data.

| Field                         | Size                     | Description                                                                                 |
|-------------------------------|--------------------------|---------------------------------------------------------------------------------------------|
| **NMF**                       | const char[4]            | Model List identifier. Always contains the string `"NMF "` (note the trailing space).       |
| **zero**                      | int                      | A placeholder integer value, always zero.                                                   |
| **ROOT**                      | struct ROOT              | The root element of the 3D model file, containing global information.                       |
| **LOCA/FRAM/JOIN/MESH**       | Array of corresponding structs | An array of child elements (location, frame, joint, or mesh data).                    |
| **END**                       | const char[4]            | End-of-data marker. Always contains the string `"END "` (including the trailing space).     |
| **zero**                      | int                      | A placeholder integer value, always zero.                                                   |

---

## NMF ROOT Structure

The ROOT structure holds the global information for the model.

| Field         | Size              | Description                                                                           |
|---------------|-------------------|---------------------------------------------------------------------------------------|
| **ROOT**      | const char[4]     | Indicator for a ROOT structure. Always contains `"ROOT"`.                             |
| **size**      | int               | Size of the ROOT structure in bytes (stored in Big-Endian format).                    |
| **2**         | int               | A constant value; always `2`.                                                         |
| **parent_iid**| int               | Identifier of the parent entity; always zero for the ROOT element.                    |
| **name**      | const char*       | Null-terminated string containing the entity's name.                                  |
| **alignment** | const char*       | Padding using `'\0'` characters to align the structure on a 4-byte boundary.          |
| **data**      | const char[41*4]  | Fixed-length binary data (164 bytes); purpose is currently unknown.                   |

---

## NMF LOCA Structure

The LOCA structure represents a location or node element within the file.

| Field         | Size            | Description                                                                          |
|---------------|-----------------|--------------------------------------------------------------------------------------|
| **LOCA**      | const char[4]   | Indicator for a LOCA structure. Always contains `"LOCA"`.                            |
| **size**      | int             | Size of the LOCA structure in bytes (stored in Big-Endian format).                   |
| **0**         | int             | A constant value, always `0`.                                                        |
| **parent_iid**| int             | Identifier of the parent entity.                                                     |
| **name**      | const char*     | Null-terminated string containing the entity's name.                                 |
| **alignment** | const char*     | Padding with `'\0'` characters for 4-byte alignment.                                 |

---

## NMF FRAM Structure

The FRAM structure holds frame-specific data including transformation information and optionally animation.

| Field                      | Size              | Description                                                                                              |
|----------------------------|-------------------|----------------------------------------------------------------------------------------------------------|
| **FRAM**                   | const char[4]     | Indicator for a FRAM structure. Always contains `"FRAM"`.                                                |
| **size**                   | int               | Size of the FRAM structure in bytes (stored in Big-Endian format).                                       |
| **2**                      | int               | A constant value; always `2`.                                                                            |
| **parent_iid**             | int               | Identifier of the parent entity.                                                                         |
| **name**                   | const char*       | Null-terminated string containing the entity's name.                                                     |
| **alignment**              | const char*       | Padding with `'\0'` characters for 4-byte alignment.                                                     |
| **matrix**                 | float[16]         | 4x4 transformation matrix (16 floats).                                                                   |
| **translation**            | float[3]          | Translation vector (offsets along the x, y, and z axes).                                                 |
| **scaling**                | float[3]          | Scaling factors for the x, y, and z axes.                                                                |
| **rotation**               | float[3]          | Rotation values for the x, y, and z axes.                                                                |
| **rotate_pivot_translate** | float[3]          | Translation vector for adjusting the rotation pivot point.                                               |
| **rotate_pivot**           | float[3]          | Coordinates of the rotation pivot point.                                                                 |
| **scale_pivot_translate**  | float[3]          | Translation vector for adjusting the scaling pivot point.                                                |
| **scale_pivot**            | float[3]          | Coordinates of the scaling pivot point.                                                                  |
| **shear**                  | float[3]          | Shear factors along the x, y, and z axes.                                                                |
| **ANIM**                   | const char[4]     | Contains `"ANIM"` if animation data is present; otherwise, this field is zeroed.                         |
| **anim**                   | struct ANIM       | Embedded animation structure; included only if the `ANIM` field equals `"ANIM"`.                         |

---

## NMF JOIN Structure

The JOIN structure defines a joint element with additional transformation and rotation limits.

| Field                | Size              | Description                                                                                                 |
|----------------------|-------------------|-------------------------------------------------------------------------------------------------------------|
| **JOIN**             | const char[4]     | Indicator for a JOIN structure. Always contains `"JOIN"`.                                                   |
| **size**             | int               | Size of the JOIN structure in bytes (stored in Big-Endian format).                                          |
| **2**                | int               | A constant value; always `2`.                                                                               |
| **parent_iid**       | int               | Identifier of the parent entity.                                                                            |
| **name**             | const char*       | Null-terminated string containing the entity's name.                                                        |
| **alignment**        | const char*       | Padding with `'\0'` characters for 4-byte alignment.                                                        |
| **matrix**           | float[16]         | 4x4 transformation matrix (16 floats).                                                                      |
| **translation**      | float[3]          | Translation vector (offsets along the x, y, and z axes).                                                    |
| **scaling**          | float[3]          | Scaling factors for the x, y, and z axes.                                                                   |
| **rotation**         | float[3]          | Rotation values for the x, y, and z axes.                                                                   |
| **rotation_matrix**  | float[16]         | 4x4 rotation matrix (16 floats).                                                                            |
| **min_rot_limit**    | float[3]          | Minimum rotation limits for the x, y, and z axes.                                                           |
| **max_rot_limit**    | float[3]          | Maximum rotation limits for the x, y, and z axes.                                                           |
| **ANIM**             | const char[4]     | Contains `"ANIM"` if animation data is present; otherwise, it is zeroed.                                    |
| **anim**             | struct ANIM       | Embedded animation structure; included only if the `ANIM` field equals `"ANIM"`.                            |

---

## NMF ANIM Structure

The ANIM structure contains keyframe data for animations including translation, scaling, and rotation curves.

| Field                          | Size      | Description                                                                                             |
|--------------------------------|-----------|---------------------------------------------------------------------------------------------------------|
| **unknown**                    | boolean   | Reserved flag; purpose is not fully defined.                                                            |
| **translation_sizes**          | int[3]    | Array of keyframe counts for translation along the x, y, and z axes.                                    |
| **scaling_sizes**              | int[3]    | Array of keyframe counts for scaling along the x, y, and z axes.                                        |
| **rotation_sizes**             | int[3]    | Array of keyframe counts for rotation along the x, y, and z axes.                                       |
| **translation_curve_values_x** | float[]  | Array of x translation values; length equals translation_sizes[0].                                       |
| **translation_curve_values_y** | float[]  | Array of y translation values; length equals translation_sizes[1].                                       |
| **translation_curve_values_z** | float[]  | Array of z translation values; length equals translation_sizes[2].                                       |
| **translation_curve_keys_x**   | int[]    | Array of key indices for x translation; count equals translation_sizes[0].                               |
| **translation_curve_keys_y**   | int[]    | Array of key indices for y translation; count equals translation_sizes[1].                               |
| **translation_curve_keys_z**   | int[]    | Array of key indices for z translation; count equals translation_sizes[2].                               |
| **scaling_curve_values_x**     | float[]  | Array of x scaling values; length equals scaling_sizes[0].                                               |
| **scaling_curve_values_y**     | float[]  | Array of y scaling values; length equals scaling_sizes[1].                                               |
| **scaling_curve_values_z**     | float[]  | Array of z scaling values; length equals scaling_sizes[2].                                               |
| **scaling_curve_keys_x**       | int[]    | Array of key indices for x scaling; count equals scaling_sizes[0].                                       |
| **scaling_curve_keys_y**       | int[]    | Array of key indices for y scaling; count equals scaling_sizes[1].                                       |
| **scaling_curve_keys_z**       | int[]    | Array of key indices for z scaling; count equals scaling_sizes[2].                                       |
| **rotation_curve_values_x**    | float[]  | Array of x rotation values; length equals rotation_sizes[0].                                             |
| **rotation_curve_values_y**    | float[]  | Array of y rotation values; length equals rotation_sizes[1].                                             |
| **rotation_curve_values_z**    | float[]  | Array of z rotation values; length equals rotation_sizes[2].                                             |
| **rotation_curve_keys_x**      | int[]    | Array of key indices for x rotation; count equals rotation_sizes[0].                                     |
| **rotation_curve_keys_y**      | int[]    | Array of key indices for y rotation; count equals rotation_sizes[1].                                     |
| **rotation_curve_keys_z**      | int[]    | Array of key indices for z rotation; count equals rotation_sizes[2].                                     |

---

## NMF MESH Structure

The MESH structure stores the mesh data including vertices, indices, materials, and other attributes.

| Field                         | Size                         | Description                                                                                               |
|-------------------------------|------------------------------|-----------------------------------------------------------------------------------------------------------|
| **MESH**                      | const char[4]                | Indicator for a MESH structure. Always contains `"MESH"`.                                                 |
| **size**                      | int                          | Size of the MESH structure in bytes (stored in Big-Endian format).                                        |
| **14**                        | int                          | A constant value; always `14`.                                                                            |
| **parent_iid**                | int                          | Identifier of the parent entity.                                                                          |
| **name**                      | const char*                  | Null-terminated string containing the entity's name.                                                      |
| **alignment**                 | const char*                  | Padding with `'\0'` characters for 4-byte alignment.                                                      |
| **tnum**                      | int                          | Triangle count (number of triangles in the mesh).                                                         |
| **vnum**                      | int                          | Vertex count (number of vertices in the mesh).                                                            |
| **vbuf**                      | float[vnum * 10]             | Vertex buffer: contains 10 floats per vertex (which may include position, normals, etc.).                 |
| **uvpt**                      | float[vnum * 2]              | UV coordinates: contains 2 floats per vertex for texture mapping.                                         |
| **inum**                      | int                          | Index count (number of indices in the index buffer).                                                      |
| **ibuf**                      | int16[inum]                  | Index buffer: array of indices (16-bit integers).                                                         |
| **zero**                      | int16                        | Padding value; present if the index count is odd to ensure proper alignment.                              |
| **backface_culling**          | int                          | Flag for backface culling (typically 0 or 1).                                                             |
| **complex**                   | int                          | Mesh complexity flag; usage may be defined by the application.                                            |
| **inside**                    | int                          | Flag indicating whether the mesh is considered 'inside' (usage depends on the implementation).            |
| **smooth**                    | int                          | Flag for enabling smooth shading.                                                                         |
| **light_flare**               | int                          | Flag for light flare effects.                                                                             |
| **material_count**            | int                          | Number of materials associated with the mesh.                                                             |
| **materials**                 | struct MATERIAL[material_count] | Array of material structures defining surface properties.                                              |
| **mesh_anim_array**           | struct MESH_ANIM[]           | Array of mesh animation structures.                                                                       |
| **unknown_count_of_floats**   | int                          | Count of additional unknown float values.                                                                 |
| **unknown_floats**            | float[unknown_count_of_floats] | Array of unknown float values.                                                                          |
| **unknown_count_of_ints**     | int                          | Count of additional unknown integer values.                                                               |
| **unknown_ints**              | int[unknown_count_of_ints]   | Array of unknown integer values.                                                                          |

---

## NMF MATERIAL Structure

The MATERIAL structure holds the properties for a material applied to a mesh.

| Field                              | Size                | Description                                                                                   |
|------------------------------------|---------------------|-----------------------------------------------------------------------------------------------|
| **MTRL**                           | const char[4]       | Indicator for a MATERIAL structure. Always contains `"MTRL"`.                                 |
| **name**                           | const char*         | Null-terminated string containing the material's name.                                        |
| **alignment**                      | const char*         | Padding with `'\0'` characters for 4-byte alignment.                                          |
| **unknown_ints**                   | int[4]              | Array of 4 unknown integers; purpose is not fully defined.                                    |
| **uv_mapping_flip_horizontal**     | int                 | Flag indicating horizontal flip for UV mapping (typically 0 or 1).                            |
| **uv_mapping_flip_vertical**       | int                 | Flag indicating vertical flip for UV mapping (typically 0 or 1).                              |
| **rotate**                         | int                 | Rotation value or flag for texture rotation (exact usage is unclear).                         |
| **horizontal_stretch**             | int                 | Factor for horizontal stretching of the texture.                                              |
| **vertical_stretch**               | int                 | Factor for vertical stretching of the texture.                                                |
| **red**                            | int                 | Red color component for the material.                                                         |
| **green**                          | int                 | Green color component for the material.                                                       |
| **blue**                           | int                 | Blue color component for the material.                                                        |
| **alpha**                          | int                 | Alpha (transparency) value for the material.                                                  |
| **red2**                           | int                 | Secondary red component (possibly for effects or dual-texturing).                             |
| **green2**                         | int                 | Secondary green component.                                                                    |
| **blue2**                          | int                 | Secondary blue component.                                                                     |
| **alpha2**                         | int                 | Secondary alpha (transparency) value.                                                         |
| **unknown_zero_ints**              | int[9]              | Array of 9 unknown integers, often zeroed.                                                    |
| **TXPG/TEXT/ZERo**                 | const char[4]       | Indicator for texture page or text data; may contain `"TXPG"`, `"TEXT"`, or `"ZERo"`.         |

---

## NMF TEXTURE Structure

The TEXTURE structure defines texture resource information and coordinates within a texture atlas.

| Field                    | Size            | Description                                                                                  |
|--------------------------|-----------------|----------------------------------------------------------------------------------------------|
| **name**                 | const char*     | Null-terminated string containing the file path of the texture.                              |
| **alignment**            | const char*     | Padding with `'\0'` characters for 4-byte alignment.                                         |
| **texture_page**         | int             | Identifier for the texture page.                                                             |
| **index_texture_on_page**| int             | Index of the texture on the specified texture page.                                          |
| **x0**                   | int             | X-coordinate of the top-left corner in the texture atlas.                                    |
| **y0**                   | int             | Y-coordinate of the top-left corner in the texture atlas.                                    |
| **x2**                   | int             | X-coordinate of the bottom-right corner in the texture atlas.                                |
| **y2**                   | int             | Y-coordinate of the bottom-right corner in the texture atlas.                                |

---

## NMF TEXT Structure

The TEXT structure holds text resource information such as file paths.

| Field         | Size            | Description                                                                 |
|---------------|-----------------|-----------------------------------------------------------------------------|
| **name**      | const char*     | Null-terminated string containing the file path of the text resource.       |
| **alignment** | const char*     | Padding with `'\0'` characters for 4-byte alignment.                        |

---

## NMF Mesh ANIM Structure

This structure describes mesh-specific animation data. It contains arrays of unknown values and sizes, as well as an end marker.

| Field                           | Size                        | Description                                                                                      |
|---------------------------------|-----------------------------|--------------------------------------------------------------------------------------------------|
| **ANIM**                        | const char[4]               | Indicator for a mesh animation block. Always contains `"ANIM"`.                                  |
| **unknown_bool**                | int                         | An unknown flag; purpose is unclear.                                                             |
| **unknown_size_of_ints**        | int                         | Number of unknown integers that follow.                                                          |
| **unknown_ints**                | int[unknown_size_of_ints]   | Array of unknown integers.                                                                       |
| **unknown_floats**              | float[3]                    | Array of 3 unknown floats.                                                                       |
| **s1**                          | int                         | Count for the following unknown float array 1.                                                   |
| **s2**                          | int                         | Count for the following unknown float array 2.                                                   |
| **s3**                          | int                         | Count for the following unknown float array 3.                                                   |
| **unknown_floats1**             | float[s1]                   | Array of unknown float values (length defined by `s1`).                                          |
| **unknown_floats2**             | float[s2]                   | Array of unknown float values (length defined by `s2`).                                          |
| **unknown_floats3**             | float[s3]                   | Array of unknown float values (length defined by `s3`).                                          |
| **ANIM (end)**                  | const char[4]               | End marker for the current animation block; may be followed by another ANIM block if present.    |

---

This documentation should now serve as a comprehensive guide to the NMF file format, with clear descriptions and a corrected table layout for each structure.
---

## License
This project is licensed under the [MIT License](LICENSE).
