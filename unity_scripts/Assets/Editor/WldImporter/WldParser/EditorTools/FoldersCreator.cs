#if UNITY_EDITOR
using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using WldParser.Items;

namespace WldParser.EditorTools
{
    public static class FoldersCreator
    {
        /// <summary>
        /// Создаёт дерево папок в Project (Assets/...) по FolderPath[].
        /// baseAssetPath: например "Assets/WLD/Models"
        /// </summary>
        public static void CreateFolders(string baseAssetPath, FolderPath[] paths)
        {
            if (paths == null || paths.Length == 0) return;

            // гарантируем базовую папку
            EnsureAssetFolder(baseAssetPath);

            foreach (var p in paths)
            {
                if (string.IsNullOrWhiteSpace(p.Path))
                    continue;

                var normalized = p.Path.Replace("\\", "/").Trim('/');
                if (string.IsNullOrEmpty(normalized))
                    continue;

                var parts = normalized
                    .Split(new[] { '/' }, StringSplitOptions.RemoveEmptyEntries)
                    .Select(SanitizeFolderName)
                    .Where(s => !string.IsNullOrEmpty(s))
                    .ToArray();

                var cur = baseAssetPath;
                foreach (var part in parts)
                    cur = EnsureChild(cur, part);
            }

            AssetDatabase.Refresh();
        }

        private static void EnsureAssetFolder(string assetPath)
        {
            assetPath = assetPath.Replace("\\", "/").TrimEnd('/');
            if (AssetDatabase.IsValidFolder(assetPath))
                return;

            // Создаём по сегментам: Assets -> WLD -> Models
            var parts = assetPath.Split('/');
            if (parts.Length == 0 || parts[0] != "Assets")
                throw new Exception($"baseAssetPath must start with 'Assets', got: {assetPath}");

            var cur = "Assets";
            for (int i = 1; i < parts.Length; i++)
                cur = EnsureChild(cur, parts[i]);
        }

        private static string EnsureChild(string parent, string childName)
        {
            var full = $"{parent}/{childName}";
            if (AssetDatabase.IsValidFolder(full))
                return full;

            AssetDatabase.CreateFolder(parent, childName);
            return full;
        }

        private static string SanitizeFolderName(string name)
        {
            if (string.IsNullOrWhiteSpace(name))
                return "_";

            var invalid = Path.GetInvalidFileNameChars();
            var chars = name.Select(ch => invalid.Contains(ch) || char.IsControl(ch) ? '_' : ch).ToArray();

            var result = new string(chars).Trim();
            if (result == "." || result == "..")
                result = "_" + result.Replace('.', '_');

            return string.IsNullOrEmpty(result) ? "_" : result;
        }
    }
}
#endif
