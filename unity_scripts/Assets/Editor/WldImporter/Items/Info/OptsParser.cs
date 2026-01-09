using WldParser.Helpers;

namespace WldParser.Items.Info
{
    public class OptsParser
    {
        private readonly BinaryFileReader _file;
        public OptsParser(BinaryFileReader file) => _file = file;

        public OptsData Parse()
        {
            (string token, uint size) = _file.TokenWithSize();
            if (token != "OPTS") throw new TokenError(token, "OPTS");

            var opts = new OptsData();
            opts.unknown1 = _file.Int();
            opts.id = _file.Name();
            opts.type = _file.Int();
            opts.story = _file.Int();
            opts.clickable = _file.Bool();
            opts.process_when_visible = _file.Bool();
            opts.process_always = _file.Bool();

            opts.item_info = UnpackItem(_file, opts.type);
            return opts;
        }

        private ItemDataBase UnpackItem(BinaryFileReader file, int type)
        {
            switch (type)
            {
                case 0:
                    return new ItemSimple { weight = file.Float() };
                case 1:
                    return new ItemLoot { weight = file.Float(), value = file.Float() };
                case 2:
                    var tool = new ItemTool();
                    tool.weight = file.Float(); tool.value = file.Float();
                    tool.strength = file.Float(); tool.pick_locks = file.Float();
                    tool.pick_safes = file.Float(); tool.alarm_systems = file.Float();
                    tool.volume = file.Float(); tool.damaging = file.Float(); // damaging is float in ruby struct (-1.0 or 1.0 likely)
                    
                    tool.applicability = new ItemAttr 
                    { 
                        glass = file.Float(), wood = file.Float(), 
                        steel = file.Float(), high_tech = file.Float() 
                    };
                    tool.noise = new ItemAttr 
                    { 
                        glass = file.Float(), wood = file.Float(), 
                        steel = file.Float(), high_tech = file.Float() 
                    };
                    return tool;
                case 3: case 7: case 8:
                    return new ItemPassage { working_time = file.Float(), material = file.Int(), crack_type = file.Int() };
                case 4:
                    return new ItemCharA { speed = file.Float(), occupation = file.Name() };
                case 5: case 6:
                    return new ItemCharB { speed = file.Float() };
                case 9:
                    return new ItemCar 
                    { 
                        transp_space = file.Float(), max_speed = file.Float(), 
                        acceleration = file.Float(), value = file.Float(), driving = file.Float() 
                    };
                default:
                    throw new System.Exception($"Unknown item type: {type}");
            }
        }
    }
}