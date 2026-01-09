#if UNITY_EDITOR
using System;
using System.IO;
using System.Collections.Generic;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using WldParser.Items;

public static class WorldBuilder
{
    private const string JsonPath = "Assets/WorldData/world.json";
    private static readonly string ModelsExportFolder = "Assets/WLD_Export/Models";

    // КЭШ: ID Модели -> Путь к файлу
    private static Dictionary<int, string> _modelPathsCache;
    // КЭШ: ID Модели -> Загруженный Префаб (чтобы не грузить с диска много раз)
    private static Dictionary<int, GameObject> _loadedPrefabsCache;

    [MenuItem("Tools/TheSting/2. Build World From JSON (Fast)")]
    public static void BuildWorldFromJson()
    {
        if (!File.Exists(JsonPath))
        {
            EditorUtility.DisplayDialog("Error", $"JSON file not found:\n{JsonPath}", "OK");
            return;
        }

        string jsonText = File.ReadAllText(JsonPath);
        WorldNodeFileWrapper data = null;

        try
        {
            data = JsonUtility.FromJson<WorldNodeFileWrapper>(jsonText);
        }
        catch (Exception e)
        {
            Debug.LogError(e);
            return;
        }

        if (data == null || data.nodes == null || data.nodes.Count == 0)
        {
            Debug.LogError("JSON is empty.");
            return;
        }

        // --- ЭТАП 1: ПРЕДВАРИТЕЛЬНОЕ КЭШИРОВАНИЕ ---
        BuildModelPathCache();
        _loadedPrefabsCache = new Dictionary<int, GameObject>();

        Undo.IncrementCurrentGroup();
        int undoGroup = Undo.GetCurrentGroup();

        GameObject root = new GameObject("WRLD_ROOT");
        Undo.RegisterCreatedObjectUndo(root, "Create WRLD_ROOT");

        Dictionary<int, GameObject> createdObjects = new Dictionary<int, GameObject>();

        // --- ЭТАП 2: СОЗДАНИЕ ОБЪЕКТОВ ---
        int total = data.nodes.Count;
        // Обновляем прогресс бар реже (каждые 500 объектов), это тоже ускоряет
        int progressStep = 500; 

        for (int i = 0; i < total; i++)
        {
            var node = data.nodes[i];
            
            if (i % progressStep == 0) 
                EditorUtility.DisplayProgressBar("Building World", $"Spawning {i}/{total}", (float)i / total);

            GameObject go = SpawnNode(node);

            if (go != null)
            {
                go.transform.position = new Vector3(node.x, node.y, -node.z);

                // Обработка вращения (Yaw)
             
                    float angleDeg = node.w * Mathf.Rad2Deg;
                    go.transform.rotation = Quaternion.Euler(0, -angleDeg, 0);
                
                
                // Пример обработки масштаба (раскомментируй, если нужно)
                // float s = node.u > 10 ? node.u/100f : node.u; 
                // go.transform.localScale = node.u * 100f;
                Debug.Log($"<color=green>{node.u}</color>");

                createdObjects[node.index] = go;
            }
        }

        EditorUtility.ClearProgressBar();

        // --- ЭТАП 3: ИЕРАРХИЯ ---
        // Это работает быстро, так как lookup в Dictionary очень быстрый
        foreach (var node in data.nodes)
        {
            if (!createdObjects.ContainsKey(node.index)) continue;
            GameObject go = createdObjects[node.index];

            if (node.parent_id != 0 && createdObjects.ContainsKey(node.parent_id))
            {
                // Важно: worldPositionStays = true, чтобы объект не улетел при смене родителя
                go.transform.SetParent(createdObjects[node.parent_id].transform, true);
            }
            else
            {
                go.transform.SetParent(root.transform, true);
            }
        }

        // Чистим кэши, чтобы освободить память
        _modelPathsCache = null;
        _loadedPrefabsCache = null;

        Undo.CollapseUndoOperations(undoGroup);
        EditorSceneManager.MarkSceneDirty(SceneManager.GetActiveScene());
        
        Debug.Log($"<color=green>World build complete!</color> Created {createdObjects.Count} objects.");
    }

    /// <summary>
    /// Сканирует папку один раз и запоминает, где лежит какая модель.
    /// </summary>
    private static void BuildModelPathCache()
    {
        _modelPathsCache = new Dictionary<int, string>();
        
        Debug.Log("Caching model paths...");
        // Ищем все модели один раз
        string[] guids = AssetDatabase.FindAssets("t:Model", new[] { ModelsExportFolder });
        
        foreach (var guid in guids)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            string fileName = Path.GetFileNameWithoutExtension(path);
            
            // Парсим ID из имени файла (Format: "Name_ID")
            int lastUnderscore = fileName.LastIndexOf('_');
            if (lastUnderscore != -1 && lastUnderscore < fileName.Length - 1)
            {
                string idString = fileName.Substring(lastUnderscore + 1);
                if (int.TryParse(idString, out int id))
                {
                    if (!_modelPathsCache.ContainsKey(id))
                    {
                        _modelPathsCache.Add(id, path);
                    }
                }
            }
        }
        Debug.Log($"Cached {_modelPathsCache.Count} models.");
    }

    private static GameObject SpawnNode(WorldNodeData node)
    {
        switch (node.type)
        {
            case 0: return CreateFolder(node);
            case 1: return CreateModel(node);
            case 2: return CreateObject(node);
            // case 3: return CreateLight(node);
            default: return new GameObject($"Unknown_{node.type}_{node.index}");
        }
    }

    private static GameObject CreateFolder(WorldNodeData node)
    {
        string name = string.IsNullOrEmpty(node.folder_name) ? $"Folder_{node.index}" : node.folder_name;
        name = name.Replace("\0", ""); 
        return new GameObject(name);
    }

    private static GameObject CreateModel(WorldNodeData node)
    {
        // 1. Проверяем кэш загруженных префабов (самый быстрый вариант)
        if (_loadedPrefabsCache.TryGetValue(node.model_id, out GameObject cachedPrefab))
        {
             // Инстанцируем копию из памяти
             var instance = (GameObject)PrefabUtility.InstantiatePrefab(cachedPrefab);
             instance.name = string.IsNullOrEmpty(node.model_name) ? cachedPrefab.name : node.model_name;
             return instance;
        }

        // 2. Если не загружен, проверяем путь в кэше путей
        if (_modelPathsCache.TryGetValue(node.model_id, out string assetPath))
        {
            var modelPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
            if (modelPrefab != null)
            {
                // Сохраняем в кэш префабов, чтобы в следующий раз не грузить с диска
                _loadedPrefabsCache[node.model_id] = modelPrefab;

                var instance = (GameObject)PrefabUtility.InstantiatePrefab(modelPrefab);
                instance.name = string.IsNullOrEmpty(node.model_name) ? modelPrefab.name : node.model_name;
                return instance;
            }
        }

        // 3. Если не нашли
        var errGo = GameObject.CreatePrimitive(PrimitiveType.Cube);
        errGo.name = $"MISSING_MODEL_{node.model_id}";
        // Убираем коллайдер, чтобы не мешал, или красим в красный
        var r = errGo.GetComponent<Renderer>();
        if (r) r.sharedMaterial = new Material(Shader.Find("Standard")) { color = Color.red };
        return errGo;
    }

    private static GameObject CreateObject(WorldNodeData node)
    {
        string name = !string.IsNullOrEmpty(node.object_name) ? node.object_name : $"Object_{node.object_id}";
        return new GameObject(name);
    }
    
    private static GameObject CreateLight(WorldNodeData node)
    {
        var go = new GameObject($"Light_{node.index}");
        var l = go.AddComponent<Light>();
        l.type = LightType.Point;
        l.range = 5.0f;
        l.color = Color.yellow;
        return go;
    }
}
#endif