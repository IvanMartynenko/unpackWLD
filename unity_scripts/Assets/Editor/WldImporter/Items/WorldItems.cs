using System;
using System.Collections.Generic;
using WldParser.Helpers;
using WldParser.Items.Info; // Подключаем пространство имен с InfoParser

namespace WldParser.Items
{
    // --- DATA CLASS ---
    [Serializable]
    public class WorldNodeData
    {
        public int index;
        public int parent_id;
        public string folder_name;
        public float x, y, z;
        public float w, n, u; // Rotation/Scale parameters
        public int unknown1;
        public int type;

        // Type 1: Model
        public int model_id;
        public string model_name; // Заполняется позже из словаря моделей
        public List<int[]> connections;
        // public ShadowData shad; // Мы договорились пропустить тени

        // Type 2: Object
        public int object_id;
        public string object_name; // Заполняется позже (если есть словарь объектов)
        public InfoData info; // Данные из INFO блока
        public int unknown_zero2;

        // Type 3: Light
        public int l_unk1;
        public float[] l_floats11;
        public int l_unk2;
        public float[] l_floats13;
        public int[] l_ints4;
    }

    // --- PARSER ---
    public class WorldItems : WldSectionBase<WorldNodeData>
    {
        // В Ruby: marker='TREE', separator='NODE'
        public WorldItems(BinaryFileReader file) : base(file, "TREE", "NODE") { }

        protected override WorldNodeData UnpackNode(BinaryFileReader file, int index, int entrySize)
        {
            file.Skip(); // Ruby: file.skip (skip value 15 - int)

            var item = new WorldNodeData();
            
            // Ruby: file.read WORLD_FIELDS[:base]
            item.parent_id = file.Int();
            item.folder_name = file.Name();
            item.x = file.Float();
            item.y = file.Float();
            item.z = file.Float();
            item.w = file.Float();
            item.n = file.Float();
            item.u = file.Float();
            item.unknown1 = file.Int();
            item.type = file.Int();

            item.index = index + 2;

            UnpackByType(file, item);

            return item;
        }

        private void UnpackByType(BinaryFileReader file, WorldNodeData item)
        {
            switch (item.type)
            {
                case 0: // Folder / Dummy
                    file.Ints(4);
                    break;

                case 1: // Model
                    UnpackModel(file, item);
                    break;

                case 2: // Object (Script/Logic)
                    UnpackObject(file, item);
                    break;

                case 3: // Light
                    UnpackLight(file, item);
                    break;
                
                default:
                    // Если встретится неизвестный тип, лучше логировать, но пока оставим как есть
                    break;
            }
        }

        private void UnpackModel(BinaryFileReader file, WorldNodeData item)
        {
            item.model_id = file.Int();
            // item.model_name = nil (в C# null по умолчанию)

            int connectionsCount = file.Int();
            if (connectionsCount > 0)
            {
                item.connections = new List<int[]>();
                for (int i = 0; i < connectionsCount; i++)
                {
                    item.connections.Add(new int[] { file.Int(), file.Int() });
                }
            }

            file.Skip(); // Ruby: file.int # skip zero

            // Проверка теней (SHAD)
            // Мы должны проверить токен. Если это SHAD, то вычисляем размер и пропускаем.
            // Если не SHAD, то нужно вернуть каретку назад? 
            // В Ruby коде: shad = file.word; item[:shad] = unpack_shadows(file) if shad == 'SHAD'
            // Это значит, что слово читается всегда. Если это не SHAD, то это начало следующей ноды (NODE)? 
            // Нет, внутри UnpackNode мы ограничены entrySize, но лучше проверить.
            
            string shadToken = file.Word();
            if (shadToken == "SHAD")
            {
                SkipShadows(file);
            }
        }

        private void SkipShadows(BinaryFileReader file)
        {
            // Ruby logic:
            // shad[:size1] = file.int
            // shad[:size2] = file.int
            int size1 = file.Int();
            int size2 = file.Int();

            // additional_offset = shad[:size1].odd? && shad[:size2].odd? ? 1 : 0
            int additionalOffset = ((size1 % 2 != 0) && (size2 % 2 != 0)) ? 1 : 0;

            // size = (shad[:size1] * shad[:size2] / 2) + additional_offset
            int floatsCount = (size1 * size2 / 2) + additionalOffset;

            // shad[:data] = file.floats(size)
            // Мы просто пропускаем байты: floatsCount * 4
            file.Next(floatsCount * 4);
        }

        private void UnpackObject(BinaryFileReader file, WorldNodeData item)
        {
            item.object_id = file.Int();
            // item.object_name = nil

            // item[:item] = {} ...
            int unknownZero = file.Int(); // item[:item][:unknown_zero]

            string token = file.Word();
            if (token == "INFO")
            {
                file.Back(); // InfoParser ожидает увидеть маркер INFO, поэтому возвращаемся
                
                // Используем InfoParser, который мы написали на прошлом шаге
                item.info = new InfoParser(file).Parse();
            }

            item.unknown_zero2 = file.Int();
        }

        private void UnpackLight(BinaryFileReader file, WorldNodeData item)
        {
            item.l_unk1 = file.Int();
            item.l_floats11 = file.Floats(11);
            item.l_unk2 = file.Int();
            item.l_floats13 = file.Floats(13);
            item.l_ints4 = file.Ints(4);
        }
    }
}