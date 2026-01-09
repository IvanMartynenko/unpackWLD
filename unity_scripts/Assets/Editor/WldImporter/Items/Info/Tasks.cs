using WldParser.Helpers;

namespace WldParser.Items.Info
{
    // --- TALI (Task List) ---
    public class TaskListParser
    {
        private readonly BinaryFileReader _file;
        public TaskListParser(BinaryFileReader file) => _file = file;

        public TaskListData Parse()
        {
            (string token, uint size) = _file.TokenWithSize();
            if (token != "TALI") throw new TokenError(token, "TALI");

            _file.Skip(); // skip zero (Ruby: file.skip # skip zero)
            
            var list = new TaskListData();
            UnpackTasksRecursive(_file, list);

            string end = _file.Token();
            if (end != "END ") throw new TokenError(end, "END ");

            return list;
        }

        private void UnpackTasksRecursive(BinaryFileReader file, TaskListData list)
        {
            string type = file.Word();
            file.Back(); // Peek logic

            if (type == "END ") return;

            var node = new TaskNode();
            if (type == "TASK")
            {
                node.IsDependence = false;
                node.task = new TaskParser(file).Parse();
            }
            else if (type == "DPND")
            {
                node.IsDependence = true;
                node.dependence = new DependenceParser(file).Parse();
            }
            else
            {
                throw new System.Exception($"Unknown task type: {type}");
            }
            
            list.nodes.Add(node);
            UnpackTasksRecursive(file, list); // Continue recursion
        }
    }

    // --- TASK ---
    public class TaskParser
    {
        private readonly BinaryFileReader _file;
        public TaskParser(BinaryFileReader file) => _file = file;

        public TaskData Parse()
        {
            (string token, uint size) = _file.TokenWithSize();
            if (token != "TASK") throw new TokenError(token, "TASK");

            var t = new TaskData();
            t.unknown1 = _file.Int();
            t.unknown2 = _file.Int();
            t.task_id = _file.Int();
            t.is_default = _file.Bool();
            t.critical = _file.Bool();

            int paramsCount = _file.Int();
            for (int i = 0; i < paramsCount; i++)
            {
                int pType = _file.Int();
                var p = new TaskParam { type = pType };
                
                switch (pType)
                {
                    case 2: p.val_floats = _file.Floats(3); break;
                    case 3: p.val_float = _file.Float(); break;
                    case 4: case 5: case 8: case 9: case 10: 
                        p.val_int = _file.Int(); break;
                    case 6: case 12: case 16: 
                        p.val_string = _file.Name(); break;
                    case 7: 
                        p.val_acod = new AcodParser(_file).Parse(); break;
                    case 15: 
                        p.val_hex = _file.Hex(9 * 4); break;
                    default: 
                        throw new System.Exception($"Unknown task param type: {pType} in Task {t.task_id}");
                }
                t.params_list.Add(p);
            }
            return t;
        }
    }

    // --- DPND (Dependence) ---
    public class DependenceParser
    {
        private readonly BinaryFileReader _file;
        public DependenceParser(BinaryFileReader file) => _file = file;

        public DependenceData Parse()
        {
            (string token, uint size) = _file.TokenWithSize();
            if (token != "DPND") throw new TokenError(token, "DPND");

            var d = new DependenceData();
            d.unknown1 = _file.Int();
            d.acod = new AcodParser(_file).Parse();
            d.unknown2 = _file.Ints(4);
            
            // Nested TALI
            d.tali = new TaskListParser(_file).Parse();

            d.unknown3 = _file.Ints(9);
            d.type = _file.Int();
            if (d.type == 1) d.unknown4 = _file.Ints(2);
            if (d.type == 2) d.unknown4 = _file.Ints(4);

            return d;
        }
    }

    // --- ACOD ---
    public class AcodParser
    {
        private readonly BinaryFileReader _file;
        public AcodParser(BinaryFileReader file) => _file = file;

        public AcodData Parse()
        {
            (string token, uint size) = _file.TokenWithSize();
            if (token != "ACOD") throw new TokenError(token, "ACOD");

            return new AcodData { nodes = _file.Ints(4) };
        }
    }
}