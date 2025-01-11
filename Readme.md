# WLD File Tools

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
To extract the contents of a WLD file, run:
```
ruby unpack.rb path_to_WLD_file.wld
```

### Packing Files into a WLD File
To pack files back into a WLD file, run:
```
ruby pack.rb path_to_unpacked_files
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

### Upscaling a Texture Page
To upscale a texture page, create a file named `path_to_unpacked_files/pack_info.yml` with the following structure:
```yaml
textures:
- page_index: 347
  scale: 2
- page_index: 346
  scale: 2
```

**Note:** The maximum size for a texture page is **512x512 pixels**.

---

## License
This project is licensed under the [MIT License](LICENSE).
