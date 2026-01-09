using System.IO;
using System.Text;
using System.Collections.Generic;

namespace WldParser.FbxWriter // Или WldParser.Helpers
{
    public static class DdsWriter
    {
        private const uint DDS_MAGIC = 0x20534444; // "DDS "

        public static byte[] CreateHeader(int width, int height, bool isAlpha)
        {
            using (var ms = new MemoryStream(128))
            using (var writer = new BinaryWriter(ms))
            {
                // 1. Magic
                writer.Write(DDS_MAGIC);

                // 2. DDS_HEADER
                writer.Write(124);          // dwSize
                writer.Write(0x00001007);   // dwFlags (CAPS | HEIGHT | WIDTH | PIXELFORMAT)
                writer.Write(height);       // dwHeight
                writer.Write(width);        // dwWidth
                writer.Write(width * 2);    // dwPitchOrLinearSize (16 bit = 2 bytes per pixel)
                writer.Write(0);            // dwDepth
                writer.Write(1);            // dwMipMapCount
                
                // dwReserved1[11]
                for (int i = 0; i < 11; i++) writer.Write(0);

                // 3. DDS_PIXELFORMAT (32 bytes)
                writer.Write(32);           // dwSize
                writer.Write(0x00000041);   // dwFlags (RGB | ALPHAPIXELS)
                writer.Write(0);            // dwFourCC
                writer.Write(16);           // dwRGBBitCount (16 bit)
                
                // Bit Masks (ARGB 1555 as per Ruby script)
                writer.Write(0x7C00);       // dwRBitMask (red)
                writer.Write(0x03E0);       // dwGBitMask (green)
                writer.Write(0x001F);       // dwBBitMask (blue)
                writer.Write(isAlpha ? 0x8000 : 0); // dwABitMask (alpha)

                // 4. CAPS
                writer.Write(0x00001000);   // dwCaps (TEXTURE)
                writer.Write(0);            // dwCaps2
                writer.Write(0);            // dwCaps3
                writer.Write(0);            // dwCaps4
                writer.Write(0);            // dwReserved2

                return ms.ToArray();
            }
        }

        public static void WriteDds(string path, int width, int height, bool hasAlpha, byte[] pixelData)
        {
            var header = CreateHeader(width, height, hasAlpha);
            
            using (var fs = new FileStream(path, FileMode.Create))
            using (var bw = new BinaryWriter(fs))
            {
                bw.Write(header);
                bw.Write(pixelData);
            }
        }
    }
}