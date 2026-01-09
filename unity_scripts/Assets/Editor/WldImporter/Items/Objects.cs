using System.Collections.Generic;
using WldParser.Helpers;

namespace WldParser.Items
{
    public class Objects : WldSectionBase<ObjectData>
    {
        public Objects(BinaryFileReader file) : base(file, "OBJS", "OBJ ") { }

        protected override ObjectData UnpackNode(BinaryFileReader file, int index, int entrySize)
        {
            var obj = new ObjectData { index = index + 1 };

            // Base
            obj.type = file.Int();
            obj.name = file.Name();
            obj.parent_folder = file.Int();

            // Animations
            obj.animations = UnpackAnimations(file);

            // Info (Nested Parser)
            obj.info = new Info.InfoParser(file).Parse();

            return obj;
        }

        private List<AnimationData> UnpackAnimations(BinaryFileReader file)
        {
            int count = file.Int();
            var list = new List<AnimationData>();
            for (int i = 0; i < count; i++)
            {
                var anim = new AnimationData();
                anim.name = file.Name();
                anim.model_3d_id = file.Int();
                anim.unknown2 = file.Float();
                anim.unknown3 = file.Float();
                anim.unknown4 = file.Int();
                anim.always_negative100 = file.Float();
                anim.loop_animation = file.Bool();
                anim.default_action = file.Bool();

                int u7Count = file.Int();
                for (int j = 0; j < u7Count; j++)
                {
                    anim.unknown7.Add(new AnimationUnknown 
                    { 
                        name = file.Name(), 
                        unknown1 = file.Float() 
                    });
                }
                list.Add(anim);
            }
            return list;
        }
    }
}