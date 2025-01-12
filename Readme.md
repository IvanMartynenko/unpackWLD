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

| MARKER Value | Description         | Array Item Separator |
|--------------|---------------------|----------------------|
| TEXP         | Texture Pages       | PAGE                 |
| GROU         | Model List Tree     | ENTR                 |
| OBGR         | Object List Tree    | ENTR                 |
| LIST         | Model List          | MODL                 |
| OBJS         | Object List         | OBJ                  |
| MAKL         | Macro List          | OBJ                  |
| TREE         | World Tree          | NODE                 |

---

### Texture Page Structure

| Field               | Size              | Description                                                                      |
|---------------------|-------------------|----------------------------------------------------------------------------------|
| PAGE                | `const char[4]`   | Texture page identifier.                                                         |
| size                | `int`             | Binary size of the texture page, stored in Big-Endian format.                    |
| 2                   | `int`             | Texture page identifier in integer format.                                       |
| width               | `int`             | Width of the texture page.                                                       |
| height              | `int`             | Height of the texture page.                                                      |
| index               | `int`             | Index of the texture page.                                                       |
| texture count       | `int`             | Number of textures contained on the texture page.                                |
| texture info array  |                   | Array containing information about textures stored on the texture page.          |
| TXPG                | `const char[4]`   | End-of-texture-info array marker.                                                |
| is_alpha            | `int`             | Alpha channel indicator: 0 if none, -1 if present.                               |
| PIXELS              |                   | Pixel data of the texture page, stored in uncompressed DDS file format.          |

---

### Texture Info Structure

| Field       | Size              | Description                                                             |
|-------------|-------------------|-------------------------------------------------------------------------|
| Filepath    | `const char*`     | File name with its path, null-terminated (`'\0'`).                      |
| alignment   | `const char*`     | Padding array of `'\0'` to align `filepath` to a 4-byte boundary.       |
| x0          | `int`             | Top-left X coordinate of the texture on the texture page.               |
| y0          | `int`             | Top-left Y coordinate of the texture on the texture page.               |
| x2          | `int`             | Bottom-right X coordinate of the texture on the texture page.           |
| y2          | `int`             | Bottom-right Y coordinate of the texture on the texture page.           |
| source_x0   | `int`             | Top-left X coordinate of the cropped texture from the original file.    |
| source_y0   | `int`             | Top-left Y coordinate of the cropped texture from the original file.    |
| source_x2   | `int`             | Bottom-right X coordinate of the cropped texture from the original file.|
| source_y2   | `int`             | Bottom-right Y coordinate of the cropped texture from the original file.|

---

## License
This project is licensed under the [MIT License](LICENSE).
