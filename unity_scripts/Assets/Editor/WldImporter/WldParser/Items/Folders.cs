using System;
using System.Collections.Generic;
using System.Linq;

namespace WldParser.Items
{
    public class RawFolderEntry
    {
        public int Index;             // index + 2
        public string Name;
        public int ParentFolderId;
    }

    public class RawFolders : WldSectionBase<RawFolderEntry>
    {
        public RawFolders(WldParser.Helpers.BinaryFileReader f, string m, string m2) : base(f, m, m2)
        {
        }

        protected override RawFolderEntry UnpackNode(WldParser.Helpers.BinaryFileReader file, int index, int entrySize)
        {
            var folder = new RawFolderEntry
            {
                Index = index + 2
            };

            file.Skip(); // always 0, skip

            folder.Name = file.Name();
            folder.ParentFolderId = file.Int();

            return folder;
        }
    }

    public readonly struct FolderPath
    {
        public FolderPath(int index, string path)
        {
            Index = index;
            Path = path;
        }

        public int Index { get; }
        public string Path { get; }
    }

    public static class FolderPathBuilder
    {
        public static FolderPath[] BuildPaths(WldSectionBase<RawFolderEntry> section, int parentRootId = 0, string separator = "/")
        {
            // поменяй "Nodes" на то поле/свойство, где WldSectionBase хранит распарсенные записи
            return BuildPaths(section.Nodes, parentRootId, separator);
        }
        /// <summary>
        /// folders: результат парсинга (Index уже должен быть index+2)
        /// parentRootId: если у тебя корень кодируется как 0 или -1 — укажи тут (по умолчанию 0)
        /// </summary>
        public static FolderPath[] BuildPaths(IEnumerable<RawFolderEntry> folders, int parentRootId = 0, string separator = "/")
        {
            var list = folders.ToList();
            var byId = list.ToDictionary(f => f.Index);

            // кеш, чтобы не пересобирать путь по 100 раз
            var cache = new Dictionary<int, string>();

            string BuildFor(int id)
            {
                if (cache.TryGetValue(id, out var cached))
                    return cached;

                if (!byId.TryGetValue(id, out var node))
                {
                    // если внезапно parent указывает на несуществующую папку
                    cache[id] = separator;
                    return cache[id];
                }

                var parts = new List<string>();
                var seen = new HashSet<int>();

                var cur = node;
                while (true)
                {
                    if (!seen.Add(cur.Index))
                    {
                        // защита от циклов в данных
                        parts.Add($"<cycle:{cur.Index}>");
                        break;
                    }

                    parts.Add(cur.Name ?? $"<noname:{cur.Index}>");

                    var parentId = cur.ParentFolderId;
                    if (parentId == parentRootId)
                        break;

                    if (!byId.TryGetValue(parentId, out cur))
                    {
                        parts.Add(separator);
                        break;
                    }
                }

                parts.Reverse();
                var path = string.Join(separator, parts);

                cache[id] = path;
                return path;
            }

            return list
                .Select(f => new FolderPath(f.Index, BuildFor(f.Index)))
                .ToArray();
        }
    }
}
