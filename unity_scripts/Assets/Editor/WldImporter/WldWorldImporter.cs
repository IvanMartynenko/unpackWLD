// Assets/Editor/WldImporter/WldWorldImporter.cs
#if UNITY_EDITOR
using UnityEditor;
using UnityEngine;
using System.IO;
using System.Linq;
using System.Collections.Generic; // Важно для Dictionary и List
using WldParser;
using WldParser.Items;
using WldParser.FbxWriter;

public static class WldWorldImporter
{
    [MenuItem("Tools/TheSting/Import WRLD to FBX Structure")]
    public static void ImportWrldToFbx()
    {
        string path = EditorUtility.OpenFilePanel("Select WRLD file", "", "wld");
        if (string.IsNullOrEmpty(path)) return;

        try
        {
            var parser = new WldParser.Parser();
            
            Debug.Log($"[WldImporter] Reading file: {path}");
            var file = new WldParser.Helpers.BinaryFileReader(path);

            if (file.Token() != "WRLD") throw new System.Exception("Not a valid WRLD file");
            
            // --- TEXTURES ---
            Debug.Log("Parsing Texture Pages...");
            var textureSection = new WldParser.Items.TexturePages(file);
            
            foreach (var page in textureSection.Nodes)
            {
                string texOutPath = "Assets/WLD_Export/Textures";
                // WldParser.Helpers.TextureSplitter.SplitAndSave(page, texOutPath);
                Debug.Log($"Processed Page ID: {page.id}, Textures: {page.textures.Count}");
            }

            // --- FOLDERS ---
            Debug.Log("Parsing Folders...");
            var modelPaths = FolderPathBuilder.BuildPaths(new RawFolders(file, "GROU", "ENTR"));
            var objectPaths = FolderPathBuilder.BuildPaths(new RawFolders(file, "OBGR", "ENTR"));

            // --- MODELS ---
            Debug.Log("Parsing Models...");
            var modelsSection = new ModelsSection(file, "LIST", "MODL");
            
            // Создаем словарь ID -> Имя для использования в JSON позже
            Dictionary<int, string> modelIdToName = new Dictionary<int, string>();

            // --- CREATE DIRECTORIES ---
            string baseModelsPath = "Assets/WLD_Export/Models";
            WldParser.EditorTools.FoldersCreator.CreateFolders(baseModelsPath, modelPaths);
            
            // --- EXPORT FBX ---
            Debug.Log("Exporting FBX files...");
            var fbxConverter = new NmfToFbx();

            int count = 0;
            foreach (var modelInfo in modelsSection.Nodes)
            {
                // Сохраняем имя модели в словарь
                string cleanName = string.Join("_", modelInfo.Name.Split(Path.GetInvalidFileNameChars()));
                if (!modelIdToName.ContainsKey(modelInfo.Index))
                {
                    modelIdToName.Add(modelInfo.Index, cleanName);
                }

                var folderPathObj = modelPaths.FirstOrDefault(p => p.Index == modelInfo.ParentFolderIid);
                string subFolder = folderPathObj.Path ?? "Unclassified";

                subFolder = subFolder.Replace("<cycle:", "_cycle_").Replace(">", "").Replace("\\", "/").TrimEnd('/').TrimStart('/'); 
                
                string dir = Path.Combine(Application.dataPath, "WLD_Export/Models", subFolder);
                if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);

                // if (cleanName != "Alarmanlage") {
                //     continue;
                // }
                string fileName = $"{cleanName}_{modelInfo.Index}.fbx";
                string fullPath = Path.Combine(dir, fileName);

                // Конвертация в структуру FBX
                var fbxRoot = fbxConverter.CreateFbxDocument(modelInfo.Nmf, cleanName);

                // Запись бинарного файла
                MiniFbxWriter.Write(fullPath, fbxRoot);
                count++;
            }

            // --- GAME OBJECTS ---
            Debug.Log("Parsing Game Objects...");
            var objectsSection = new WldParser.Items.Objects(file);

            // Пропускаем MAKL (используем Empty или пропускаем вручную, если класс Empty есть)
            new Empty(file, "MAKL", "OBJ "); 
            
            // --- WORLD TREE (JSON) ---
            Debug.Log("Parsing World Tree...");
            
            // ИСПРАВЛЕНИЕ: Добавлено 'var'
            var worldItems = new WldParser.Items.WorldItems(file);

            if (worldItems != null && worldItems.Nodes.Count > 0)
            {
                // Обогащаем данные именами моделей (Model Mapping)
                foreach (var node in worldItems.Nodes)
                {
                    // Теперь modelIdToName существует и заполнен
                    if (node.type == 1 && modelIdToName.TryGetValue(node.model_id, out string mName))
                    {
                        node.model_name = mName;
                    }
                }

                // Создаем список явно, чтобы JsonUtility корректно его понял
                var jsonWrapper = new WorldNodeFileWrapper(worldItems.Nodes);
                
                string json = JsonUtility.ToJson(jsonWrapper, true);

                string jsonDir = Path.Combine(Application.dataPath, "WorldData");
                if (!Directory.Exists(jsonDir)) Directory.CreateDirectory(jsonDir);
                
                string jsonPath = Path.Combine(jsonDir, "world.json");
                File.WriteAllText(jsonPath, json);

                Debug.Log($"[WldImporter] JSON generated at: {jsonPath}. Nodes count: {worldItems.Nodes.Count}");
            }
            
            AssetDatabase.Refresh();
            Debug.Log($"[WldImporter] Done! Exported {count} FBX files.");
        }
        catch (System.Exception ex)
        {
            Debug.LogError($"Error: {ex.Message}\n{ex.StackTrace}");
        }
    }
}
#endif