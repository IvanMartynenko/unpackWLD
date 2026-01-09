using System;
using System.Collections.Generic;

namespace WldParser.Items
{
    // --- OBJECTS ---
    [Serializable]
    public class ObjectData
    {
        public int index;
        public int type;
        public string name;
        public int parent_folder;
        public List<AnimationData> animations = new List<AnimationData>();
        public InfoData info;
    }

    [Serializable]
    public class AnimationData
    {
        public string name;
        public int model_3d_id;
        public float unknown2;
        public float unknown3;
        public int unknown4;
        public float always_negative100;
        public bool loop_animation;
        public bool default_action;
        public List<AnimationUnknown> unknown7 = new List<AnimationUnknown>();
    }

    [Serializable]
    public class AnimationUnknown
    {
        public string name;
        public float unknown1;
    }

    // --- INFO ---
    [Serializable]
    public class InfoData
    {
        public int unknown1;
        public int unknown2;
        public int unknown3;

        public OptsData opts;
        public DialogData dialog;
        public TaskListData task_list;
    }

    // --- OPTS ---
    [Serializable]
    public class OptsData
    {
        public int unknown1;
        public string id;
        public int type;
        public int story;
        public bool clickable;
        public bool process_when_visible;
        public bool process_always;
        
        // Custom fields from Info logic
        public int? custom_open;
        public int? custom_locked;
        public int? custom_active;
        public float[] custom_values;

        // Specific Item Data based on Type
        public ItemDataBase item_info; 
    }

    // Base class for item properties
    [Serializable] public class ItemDataBase { }
    
    [Serializable] public class ItemSimple : ItemDataBase { public float weight; }
    [Serializable] public class ItemLoot : ItemDataBase { public float weight; public float value; }
    [Serializable] public class ItemTool : ItemDataBase 
    {
        public float weight, value, strength, pick_locks, pick_safes, alarm_systems, volume, damaging;
        public ItemAttr applicability;
        public ItemAttr noise;
    }
    [Serializable] public class ItemAttr { public float glass, wood, steel, high_tech; }
    [Serializable] public class ItemPassage : ItemDataBase { public float working_time; public int material; public int crack_type; }
    [Serializable] public class ItemCharA : ItemDataBase { public float speed; public string occupation; }
    [Serializable] public class ItemCharB : ItemDataBase { public float speed; }
    [Serializable] public class ItemCar : ItemDataBase { public float transp_space, max_speed, acceleration, value, driving; }

    // --- DIALOG ---
    [Serializable]
    public class DialogData
    {
        public bool bad_size;
        public int unknown_value; // for bad_size
        public List<DialogItem> items = new List<DialogItem>();
    }

    [Serializable]
    public class DialogItem
    {
        public int active;
        public string Q, A, DlgMinus, DlgPlus, AlwaysMinus, AlwaysPlus;
        public int Always, Story, Coohess, DialogEvent;
    }
    
    // --- TASKS ---
    [Serializable]
    public class TaskListData
    {
        public List<TaskNode> nodes = new List<TaskNode>();
    }
    
    [Serializable]
    public class TaskNode
    {
        public bool IsDependence; // true if DPND, false if TASK
        public TaskData task;
        public DependenceData dependence;
    }

    [Serializable]
    public class TaskData
    {
        public int unknown1, unknown2, task_id;
        public bool is_default, critical;
        public List<TaskParam> params_list = new List<TaskParam>();
    }

    [Serializable]
    public class TaskParam
    {
        public int type;
        // Value container (only one is set based on type)
        public float[] val_floats;
        public float val_float;
        public int val_int;
        public string val_string;
        public AcodData val_acod;
        public string val_hex; 
    }

    [Serializable]
    public class DependenceData
    {
        public int unknown1;
        public AcodData acod;
        public int[] unknown2;
        public TaskListData tali; // Recursive!
        public int[] unknown3;
        public int type;
        public int[] unknown4;
    }

    [Serializable]
    public class AcodData
    {
        public int[] nodes;
    }

    [Serializable]
    public class WorldNodeFileWrapper
    {
        public List<WorldNodeData> nodes;

        // Конструктор, который принимает данные из парсера
        public WorldNodeFileWrapper(IReadOnlyList<WorldNodeData> source)
        {
            nodes = new List<WorldNodeData>(source);
        }
    }
}