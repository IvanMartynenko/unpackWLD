using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;

namespace WldParser.FbxWriter
{
    public static class FbxDebugWriter
    {
        public static void Write(string filePath, FbxNode root)
        {
            if (File.Exists(filePath)) File.Delete(filePath);

            var sb = new StringBuilder();
            
            // В Python скрипте корневой элемент - это список нод верхнего уровня.
            // У нас root - это виртуальная нода, поэтому мы пишем её детей.
            
            sb.Append("[\n");
            for (int i = 0; i < root.Children.Count; i++)
            {
                WriteNode(sb, root.Children[i], 1);
                if (i < root.Children.Count - 1) sb.Append(",\n");
            }
            sb.Append("\n]");

            File.WriteAllText(filePath, sb.ToString());
            Debug.Log($"[FbxDebugWriter] Saved JSON to {filePath}");
        }

        private static void WriteNode(StringBuilder sb, FbxNode node, int indent)
        {
            string pad = new string(' ', indent * 2);
            sb.Append(pad);
            sb.Append("[\n");

            // 1. Name
            sb.Append(pad + "  ");
            WriteValue(sb, node.Name);
            sb.Append(",\n");

            // 2. Properties List
            sb.Append(pad + "  [");
            for (int i = 0; i < node.Properties.Count; i++)
            {
                WriteValue(sb, node.Properties[i]);
                if (i < node.Properties.Count - 1) sb.Append(", ");
            }
            sb.Append("],\n");

            // 3. Types String (Construct from enum chars)
            sb.Append(pad + "  \"");
            foreach (var t in node.PropertyTypes)
            {
                sb.Append((char)t);
            }
            sb.Append("\",\n");

            // 4. Children List
            sb.Append(pad + "  [\n");
            for (int i = 0; i < node.Children.Count; i++)
            {
                WriteNode(sb, node.Children[i], indent + 2);
                if (i < node.Children.Count - 1) sb.Append(",\n");
            }
            sb.Append("\n" + pad + "  ]\n");

            sb.Append(pad + "]");
        }

        private static void WriteValue(StringBuilder sb, object val)
        {
            if (val == null)
            {
                sb.Append("null");
                return;
            }

            var t = val.GetType();

            if (t == typeof(string))
            {
                string s = (string)val;
                // Экранирование для JSON
                s = s.Replace("\\", "\\\\").Replace("\"", "\\\""); 
                sb.Append($"\"{s}\"");
            }
            else if (t == typeof(bool))
            {
                sb.Append(((bool)val) ? "true" : "false"); // В Python может быть 0/1, но для JSON true/false валиднее
            }
            else if (IsNumeric(t))
            {
                // Используем InvariantCulture чтобы точки оставались точками (1.5, а не 1,5)
                sb.Append(string.Format(CultureInfo.InvariantCulture, "{0}", val));
            }
            else if (val is Array arr)
            {
                sb.Append("[");
                int len = arr.Length;
                // Ограничиваем вывод больших массивов для отладки, иначе файл будет гигантским
                // Если нужно записать ВСЁ, уберите ограничение
                int limit = 50; 
                bool truncated = len > limit;
                int loopLen = truncated ? limit : len;

                for (int i = 0; i < loopLen; i++)
                {
                    WriteValue(sb, arr.GetValue(i));
                    if (i < loopLen - 1) sb.Append(", ");
                }
                
                if (truncated) sb.Append(", \"...truncated...\"");
                
                sb.Append("]");
            }
            else
            {
                sb.Append($"\"{val}\"");
            }
        }

        private static bool IsNumeric(Type type)
        {
            return type == typeof(int) || type == typeof(long) || 
                   type == typeof(float) || type == typeof(double) || 
                   type == typeof(short) || type == typeof(byte);
        }
    }
}