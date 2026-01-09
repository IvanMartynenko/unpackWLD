using System.IO;
using UnityEngine;
using WldParser.Items;
using WldParser.Helpers;


namespace WldParser.Helpers
{
    public static class TextureSplitter
    {
        public static void SplitAndSave(TexturePageInfo page, string outputBaseDir)
        {
            string ddsDir = Path.Combine(outputBaseDir, "dds");
            string pngDir = Path.Combine(outputBaseDir, "png"); // Для удобства в Unity

            if (!Directory.Exists(ddsDir)) Directory.CreateDirectory(ddsDir);
            if (!Directory.Exists(pngDir)) Directory.CreateDirectory(pngDir);

            int atlasWidth = page.width;
            byte[] atlasData = page.imageBinary;

            foreach (var subTex in page.textures)
            {
                // Имя файла: name_pageID.dds (как в руби скрипте)
                string fileNameRaw = Path.GetFileNameWithoutExtension(subTex.filepath);
                string finalName = $"{fileNameRaw}_{page.id}";
                
                int x0 = subTex.box.x0;
                int y0 = subTex.box.y0;
                int w = subTex.box.Width;
                int h = subTex.box.Height;

                if (w <= 0 || h <= 0) continue;

                // 1. Вырезаем байты (Slicing)
                byte[] slicedBytes = SliceBytes(atlasData, atlasWidth, x0, y0, w, h);

                // 2. Сохраняем DDS (точная копия формата игры)
                string ddsPath = Path.Combine(ddsDir, finalName + ".dds");
                WldParser.FbxWriter.DdsWriter.WriteDds(ddsPath, w, h, true, slicedBytes);

                // 3. Конвертируем в PNG (для Unity)
                // ARGB1555 -> RGBA32
                string pngPath = Path.Combine(pngDir, finalName + ".png");
                SaveAsPng(slicedBytes, w, h, pngPath);
            }
        }

        private static byte[] SliceBytes(byte[] source, int atlasWidth, int x, int y, int w, int h)
        {
            byte[] result = new byte[w * h * 2]; // 2 байта на пиксель
            int bytesPerPixel = 2;
            int atlasRowStride = atlasWidth * bytesPerPixel;
            int resultRowStride = w * bytesPerPixel;

            for (int row = 0; row < h; row++)
            {
                // Смещение в атласе: (y + row) * width + x
                int srcIndex = ((y + row) * atlasRowStride) + (x * bytesPerPixel);
                int dstIndex = row * resultRowStride;

                // Копируем строку
                System.Array.Copy(source, srcIndex, result, dstIndex, resultRowStride);
            }
            return result;
        }

        // Конвертер 16-bit ARGB1555 -> 32-bit RGBA для PNG
        private static void SaveAsPng(byte[] raw16, int w, int h, string path)
        {
            Color32[] pixels = new Color32[w * h];

            for (int i = 0; i < pixels.Length; i++)
            {
                // Читаем 2 байта (Little Endian)
                ushort pixel = (ushort)(raw16[i * 2] | (raw16[i * 2 + 1] << 8));
                
                // Формат ARGB 1555:
                // A (1 bit) = bit 15
                // R (5 bits) = bits 10-14
                // G (5 bits) = bits 5-9
                // B (5 bits) = bits 0-4

                byte a = (byte)((pixel & 0x8000) != 0 ? 255 : 0); // 1 бит альфа -> 0 или 255
                // Масштабируем 5 бит (0-31) в 8 бит (0-255) умножением на 8 (приблизительно) или (v * 255 / 31)
                byte r = (byte)(((pixel & 0x7C00) >> 10) * 255 / 31);
                byte g = (byte)(((pixel & 0x03E0) >> 5) * 255 / 31);
                byte b = (byte)(((pixel & 0x001F)) * 255 / 31);

                // В текстурах Unity координаты Y часто перевернуты относительно файловых форматов.
                // Но при обычном чтении строки за строкой, Texture2D ожидает снизу-вверх? 
                // Обычно DDS хранятся сверху-вниз. Texture2D.SetPixels ожидает снизу-вверх (0,0 - левый нижний).
                // Поэтому перевернем по Y при записи в массив.
                
                int x = i % w;
                int y = i / w;
                int invY = h - 1 - y; // Flip Y
                
                pixels[invY * w + x] = new Color32(r, g, b, a);
            }

            Texture2D tex = new Texture2D(w, h);
            tex.SetPixels32(pixels);
            tex.Apply();

            File.WriteAllBytes(path, tex.EncodeToPNG());
            Object.DestroyImmediate(tex); // Чистим память
        }
    }
}