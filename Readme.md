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
| NMF                     | struct NMF          | 3D model data (NMF format).                                                |


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

### Struct of NMF file

| Field                         | Size                           | Description                                                             |
|------------------------------|---------------------------------|-------------------------------------------------------------------------|
| NMF                          | const char[4]                   | Model List identifier. Always `NMF `.                                   |
| zero                         | int                             | A zero value.                                                           |
| ROOT                         | struct ROOT                     | The root of 3D model file.                                              |
| LOCA or FRAM or JOIN or MESH | struct LOCA, FRAM, JOIN, MESH[] | Array of structs.                                                       |
| END                          | const char[4]                   | `"END "`. End-of-data marker. Note: includes a space.                   |
| zero                         | int                             | A zero value.                                                           |

### Struct NMF ROOT

| Fiel                         | Size                           | Description                                                             |
|------------------------------|---------------------------------|-------------------------------------------------------------------------|
| ROOT                         | const char[4]                   | Root struct indicator. Always `ROOT`.                                   |
| size                    | int                        | Binary size of struct, stored in Big-Endian format.                |
| 2                        | int |  Constant value. Always `2`.  |
| parent_iid | int            | Identifier of the parent entity. Always zero for ROOT |
| name                    | const char*                | Entity name                               |
| alignment               | const char*                | Padding array of `'\0'` to align to a 4-byte boundary.                     |
| data                         | const char[41 * 4]                    | unknow binary data                                            |

### Struct NMF LOCA

| Fiel                         | Size                           | Description                                                             |
|------------------------------|---------------------------------|-------------------------------------------------------------------------|
| LOCA                         | const char[4]                   | Root struct indicator. Always `LOCA`.                                   |
| size                    | int                        | Binary size of struct, stored in Big-Endian format.                |
| 0                        | int |  Constant value. Always `0`.  |
| parent_iid | int            | Identifier of the parent entity. |
| name                    | const char*                | Entity name                               |
| alignment               | const char*                | Padding array of `'\0'` to align to a 4-byte boundary.                     |



---

## License
This project is licensed under the [MIT License](LICENSE).


Ids:
Model List Tree, Object List Tree : 0
Model List second id: 1
Textures Page: 2
Model List first id: 9


NMF_LOCA: 0
NMF_ROOT: 2
NMF_FRAM: 2
NMF_JOIN: 2
NMF_MESH: 14