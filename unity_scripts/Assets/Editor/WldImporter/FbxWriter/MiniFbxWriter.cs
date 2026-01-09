using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Linq;

namespace WldParser.FbxWriter
{
    // Соответствует типам из data_types.py / скрипта
    public enum FbxPropType : byte
    {
        Bool = (byte)'B',
        Char = (byte)'C',       // В Python это Byte
        Byte = (byte)'C',       // Алиас для удобства
        Short = (byte)'Y',      // Int16
        Int = (byte)'I',        // Int32
        Long = (byte)'L',       // Int64
        Float = (byte)'F',      // Float32
        Double = (byte)'D',     // Float64
        Bytes = (byte)'R',      // Raw binary data
        String = (byte)'S',     // String
        
        // Arrays
        IntArray = (byte)'i',
        LongArray = (byte)'l',
        FloatArray = (byte)'f',
        DoubleArray = (byte)'d',
        BoolArray = (byte)'b',
        ByteArray = (byte)'c'
    }

    public class FbxNode
    {
        public string Name;
        public List<object> Properties = new List<object>();
        public List<FbxPropType> PropertyTypes = new List<FbxPropType>();
        public List<FbxNode> Children = new List<FbxNode>();

        public FbxNode(string name) { Name = name; }

        public void AddProperty(object val, FbxPropType type)
        {
            Properties.Add(val);
            PropertyTypes.Add(type);
        }
    }

    public static class MiniFbxWriter
    {
        // Константы из Python версии
        private static readonly byte[] HeaderMagic = Encoding.ASCII.GetBytes("Kaydara FBX Binary  \0\x1a\0");
        private const int Version = 7500;

        // Данные для хака даты/времени (Workaround)
        private static readonly byte[] _TIME_ID = Encoding.ASCII.GetBytes("1970-01-01 10:00:00:000");
        private static readonly byte[] _FILE_ID = { 0x28, 0xb3, 0x2a, 0xeb, 0xb6, 0x24, 0xcc, 0xc2, 0xbf, 0xc8, 0xb0, 0x2a, 0xa9, 0x2b, 0xfc, 0xf1 };
        private static readonly byte[] _FOOT_ID = { 0xfa, 0xbc, 0xab, 0x09, 0xd0, 0xc8, 0xd4, 0x66, 0xb1, 0x76, 0xfb, 0x83, 0x1c, 0xf7, 0x26, 0x7e };
        private static readonly byte[] _LAST_MAGIC = { 0xf8, 0x5a, 0x8c, 0x6a, 0xde, 0xf5, 0xd9, 0x7e, 0xec, 0xe9, 0x0c, 0xe3, 0x75, 0x8f, 0x29, 0x0b };

        // Исключения, которые всегда требуют Sentinel (из скрипта _ELEMS_ID_ALWAYS_BLOCK_SENTINEL)
        private static readonly HashSet<string> ElemsIdAlwaysBlockSentinel = new HashSet<string>
        {
            "AnimationStack", "AnimationLayer"
        };

        public static void Write(string filePath, FbxNode root)
        {
            // Применяем хак перед записью (как _write_timedate_hack)
            ApplyTimeDateHack(root);

            if (File.Exists(filePath)) File.Delete(filePath);

            using (var fs = new FileStream(filePath, FileMode.Create))
            using (var bw = new BinaryWriter(fs))
            {
                // 1. Header
                bw.Write(HeaderMagic);
                bw.Write((uint)Version);

                // 2. Root Children
                // Python пишет elem_root.children, сам корневой узел (пустой) не пишется как узел
                for (int i = 0; i < root.Children.Count; i++)
                {
                    bool isLast = (i == root.Children.Count - 1);
                    WriteNode(bw, root.Children[i], isLast);
                }

                // Sentinel после корневых детей не нужен в явном виде здесь, так как
                // в структуре файла FBX корневой уровень просто заканчивается Null Record перед футером.
                // В Python версии это делается внутри _write_children, но для root вызывается отдельно.
                // В 7500+ sentinel = 25 нулевых байт.
                WriteNullRecord(bw);

                // 3. Footer
                WriteFooter(bw);
            }
        }

        // Аналог _write_timedate_hack
        private static void ApplyTimeDateHack(FbxNode root)
        {
            int ok = 0;
            foreach (var elem in root.Children)
            {
                if (elem.Name == "FileId")
                {
                    elem.Properties.Clear();
                    elem.PropertyTypes.Clear();
                    elem.AddProperty(_FILE_ID, FbxPropType.Bytes);
                    ok++;
                }
                else if (elem.Name == "CreationTime")
                {
                    elem.Properties.Clear();
                    elem.PropertyTypes.Clear();
                    elem.AddProperty(Encoding.ASCII.GetString(_TIME_ID), FbxPropType.String);
                    ok++;
                }
                if (ok == 2) break;
            }
        }

        private static void WriteNode(BinaryWriter bw, FbxNode node, bool isLast)
        {
            long startPos = bw.BaseStream.Position;

            // Metadata: EndOffset (8), NumProps (8), PropListLen (8) -> 24 bytes (Ver 7500+)
            bw.Write((long)0);
            bw.Write((long)0);
            bw.Write((long)0);

            // ID
            byte[] nameBytes = Encoding.UTF8.GetBytes(node.Name ?? "");
            bw.Write((byte)nameBytes.Length);
            if (nameBytes.Length > 0) bw.Write(nameBytes);

            // Properties
            long propsStartPos = bw.BaseStream.Position;
            for (int i = 0; i < node.Properties.Count; i++)
            {
                WriteProperty(bw, node.Properties[i], node.PropertyTypes[i]);
            }
            long propsEndPos = bw.BaseStream.Position;

            // Children
            // Рекурсивная запись
            if (node.Children.Count > 0)
            {
                for (int i = 0; i < node.Children.Count; i++)
                {
                    bool childIsLast = (i == node.Children.Count - 1);
                    WriteNode(bw, node.Children[i], childIsLast);
                }
                
                // Если есть дети, всегда пишем Sentinel
                WriteNullRecord(bw);
            }
            else
            {
                // Логика из Python:
                // elif (not self.props and not is_last) or self.id in _ELEMS_ID_ALWAYS_BLOCK_SENTINEL:
                bool hasProps = node.Properties.Count > 0;
                bool needsSentinel = (!hasProps && !isLast) || ElemsIdAlwaysBlockSentinel.Contains(node.Name);

                if (needsSentinel)
                {
                    WriteNullRecord(bw);
                }
            }

            long endPos = bw.BaseStream.Position;

            // Back-patch header
            long currentPos = endPos;
            bw.BaseStream.Seek(startPos, SeekOrigin.Begin);

            bw.Write((long)currentPos); // EndOffset
            bw.Write((long)node.Properties.Count); // NumProperties
            bw.Write((long)(propsEndPos - propsStartPos)); // PropertyListLen

            bw.BaseStream.Seek(currentPos, SeekOrigin.Begin);
        }

        private static void WriteProperty(BinaryWriter bw, object val, FbxPropType type)
        {
            bw.Write((byte)type);
            switch (type)
            {
                case FbxPropType.Bool: bw.Write((byte)((bool)val ? 1 : 0)); break;
                case FbxPropType.Byte: bw.Write((byte)val); break; // C / Char / Byte
                case FbxPropType.Short: bw.Write((short)val); break;
                case FbxPropType.Int: bw.Write((int)val); break;
                case FbxPropType.Float: bw.Write((float)val); break;
                case FbxPropType.Double: bw.Write((double)val); break;
                case FbxPropType.Long: bw.Write((long)val); break;
                
                case FbxPropType.String:
                    var str = (string)val;
                    var strBytes = Encoding.UTF8.GetBytes(str);
                    bw.Write((int)strBytes.Length);
                    bw.Write(strBytes);
                    break;

                // case FbxPropType.RawData:
                //     var raw = (byte[])val;
                //     bw.Write((byte)'R'); // Тип свойства 'R' (Raw)
                //     bw.Write((int)raw.Length); // Длина массива
                //     bw.Write(raw); // Сам массив
                //     break;
                
                case FbxPropType.Bytes: // 'R' Raw Data
                    var raw = (byte[])val;
                    bw.Write((int)raw.Length);
                    bw.Write(raw);
                    break;
                
                // Arrays
                case FbxPropType.IntArray: WriteArray(bw, (int[])val, 4); break;
                case FbxPropType.LongArray: WriteArray(bw, (long[])val, 8); break;
                case FbxPropType.FloatArray: WriteArray(bw, (float[])val, 4); break;
                case FbxPropType.DoubleArray: WriteArray(bw, (double[])val, 8); break;
                case FbxPropType.BoolArray: WriteArray(bw, (bool[])val, 1); break;
                case FbxPropType.ByteArray: WriteArray(bw, (byte[])val, 1); break;
            }
        }

        private static void WriteArray<T>(BinaryWriter bw, T[] array, int itemSize) where T : struct
        {
            int length = array.Length; // Количество элементов
            int encoding = 0; // 0 = raw (без сжатия, так как мы убрали zlib)
            int compLen = length * itemSize; // Размер в байтах

            bw.Write((int)length);
            bw.Write((int)encoding);
            bw.Write((int)compLen);

            // Копируем данные в массив байт
            byte[] bytes = new byte[compLen];
            Buffer.BlockCopy(array, 0, bytes, 0, compLen);
            bw.Write(bytes);
        }
        
        // Перегрузка для bool[], так как bool в C# может быть не 1 байт в struct,
        // но Buffer.BlockCopy работает с примитивами. Для надежности с bool[] лучше так:
        private static void WriteArray(BinaryWriter bw, bool[] array, int itemSize)
        {
             // FBX bool array expects 1 byte per bool
             int length = array.Length;
             int encoding = 0;
             int compLen = length * 1;

             bw.Write((int)length);
             bw.Write((int)encoding);
             bw.Write((int)compLen);
             
             // Конвертация
             byte[] bytes = new byte[length];
             for(int i=0; i<length; i++) bytes[i] = array[i] ? (byte)1 : (byte)0;
             bw.Write(bytes);
        }

        private static void WriteNullRecord(BinaryWriter bw)
        {
            // Для версии >= 7500: Sentinel Length = 25 байт (все нули)
            bw.Write(new byte[25]);
        }

        private static void WriteFooter(BinaryWriter bw)
        {
            bw.Write(_FOOT_ID);

            // Padding (4 bytes always zero)
            bw.Write(new byte[4]);

            // Alignment Padding to 16 bytes
            long pos = bw.BaseStream.Position;
            long pad = ((pos + 15) & ~15) - pos;
            if (pad == 0) pad = 16;
            
            bw.Write(new byte[pad]);

            // Version again
            bw.Write((int)Version);

            // 120 bytes of zeros
            bw.Write(new byte[120]);

            // Magic footer constant
            bw.Write(_LAST_MAGIC);
        }
    }
}