using System;
using WldParser.Helpers;
using System.Collections.Generic;

namespace WldParser.Items
{
    [Serializable]
    public class TextureBox
    {
        public int x0, y0, x2, y2;
        public int Width => x2 - x0;
        public int Height => y2 - y0;

        public TextureBox(int x0, int y0, int x2, int y2)
        {
            this.x0 = x0; this.y0 = y0; this.x2 = x2; this.y2 = y2;
        }
    }

    [Serializable]
    public class SubTextureInfo
    {
        public string filepath;
        public TextureBox box;
        public TextureBox sourceBox;
    }

    [Serializable]
    public class TexturePageInfo
    {
        public int width;
        public int height;
        public int id;
        public List<SubTextureInfo> textures = new List<SubTextureInfo>();
        public bool isAlpha;
        public byte[] imageBinary;
    }
}

namespace WldParser.Items
{
    public class TexturePages : WldSectionBase<TexturePageInfo>
    {
        // Передаем в базовый конструктор маркер "TEXP" и разделитель "PAGE"
        public TexturePages(BinaryFileReader file) : base(file, "TEXP", "PAGE")
        {
        }

        protected override TexturePageInfo UnpackNode(BinaryFileReader file, int index, int entrySize)
        {
            var page = new TexturePageInfo();

            // 1. Ruby: file.skip # always 2
            // В Ruby скрипте pack_node делает push_int 2, значит читаем 4 байта (int).
            int unknownVersion = file.Int(); 

            // 2. Ruby: page = file.read TEXTURE_PAGE_FIELDS[:base]
            page.width = file.Int();
            page.height = file.Int();
            page.id = file.Int();

            // 3. Ruby: textures_count = file.int
            int texturesCount = file.Int();

            // 4. Ruby: page[:textures] = ... map { unpack_texture(file) }
            for (int i = 0; i < texturesCount; i++)
            {
                page.textures.Add(UnpackTexture(file));
            }

            // 5. Ruby: token = file.word; raise ... unless token == 'TXPG'
            // ВАЖНО: TXPG находится внутри блока PAGE, а не является разделителем блоков.
            string token = file.Word();
            if (token != "TXPG")
            {
                // Используем ваш класс исключения, хоть он и для внешней структуры,
                // но здесь он тоже подходит по смыслу.
                throw new TokenError(token, "TXPG");
            }

            // 6. Ruby: page[:is_alpha] = file.bool
            page.isAlpha = file.Bool();

            // 7. Ruby: page[:image_binary] = file.hex(page[:width] * page[:height] * 2)
            // Формат пикселей 16-битный (2 байта на пиксель)
            int dataSize = page.width * page.height * 2;
            page.imageBinary = file.Raw(dataSize);

            return page;
        }

        private SubTextureInfo UnpackTexture(BinaryFileReader file)
        {
            var info = new SubTextureInfo();

            // Ruby: file.filename
            info.filepath = file.Name();

            // Ruby: file.read(TEXTURE_PAGE_FIELDS[:box])
            info.box = new TextureBox(file.Int(), file.Int(), file.Int(), file.Int());

            // Ruby: file.read(TEXTURE_PAGE_FIELDS[:box]) (source_box)
            info.sourceBox = new TextureBox(file.Int(), file.Int(), file.Int(), file.Int());

            return info;
        }
    }
}