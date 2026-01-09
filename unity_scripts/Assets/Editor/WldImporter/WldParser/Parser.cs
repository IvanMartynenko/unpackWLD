using System;
using UnityEngine;

namespace WldParser
{
    /// <summary>
    /// WRLD parser. Debug output goes to Unity Console only.
    /// </summary>
    public class Parser
    {
        public void Parse(string filepath, bool withJsonModels = false)
        {
            Debug.Log($"[WldParser] Parse start: {filepath}");

            var file = new WldParser.Helpers.BinaryFileReader(filepath);

            string token = file.Token();
            if (token != "WRLD")
            {
                Debug.LogError(
                    $"[WldParser] Invalid file header. Expected 'WRLD', got '{token}'"
                );

                throw new Exception(
                    $"Opened file is not a 'The Sting!' game file. Expected 'WRLD', got '{token}'"
                );
            }

            Debug.Log("[WldParser] Reading sections...");

            ReadSection(file, "TEXP", "PAGE");
            var ModelPaths = WldParser.Items.FolderPathBuilder.BuildPaths(new WldParser.Items.RawFolders(file, "GROU", "ENTR"));
            var ObjectPaths = WldParser.Items.FolderPathBuilder.BuildPaths(new WldParser.Items.RawFolders(file, "OBGR", "ENTR"));
            WldParser.EditorTools.FoldersCreator.CreateFolders("Assets/WLD/Models", ModelPaths);
            WldParser.EditorTools.FoldersCreator.CreateFolders("Assets/WLD/Objects", ObjectPaths);
            Debug.Log($"[WldParser] Created folders. Models={ModelPaths.Length}, Objects={ObjectPaths.Length}");

            Debug.Log("[WldParser] Reading models...");
            new WldParser.Items.ModelsSection(file, "LIST", "MODL");

            ReadSection(file, "OBJS", "OBJ ");
            ReadSection(file, "MAKL", "OBJ ");
            ReadSection(file, "TREE", "NODE");

            Debug.Log("[WldParser] Parse completed successfully.");
        }

        private static void ReadSection(
            WldParser.Helpers.BinaryFileReader file,
            string container,
            string entry)
        {
            Debug.Log($"[WldParser] Section {container}/{entry}");
            new WldParser.Items.Empty(file, container, entry);
        }
    }
}
