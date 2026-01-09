using System;
using System.Collections.Generic;

namespace WldParser.Items
{
    public class ModelCameraValues
    {
        public float X, Y, Z, Pitch, Yaw;
    }

    public class ModelCamera
    {
        public ModelCameraValues Camera;
        public ModelCameraValues Item;
    }

    public class AttackPoint
    {
        public float X, Y, Z, Radius;
    }

    public class ModelInfo
    {
        public int Index;
        public string Name;
        public bool InfluencesCamera;
        public bool NoCameraCheck;
        public bool AntiGround;
        public int DefaultSkeleton;
        public int UseSkeleton;

        public ModelCamera Camera;
        public int ParentFolderIid;
        public List<AttackPoint> AttackPoints = new();
        public NmfModel Nmf;
    }

    /// <summary>
    /// Models section: marker = "LIST", separator = "MODL".
    /// </summary>
    public class ModelsSection : WldSectionBase<ModelInfo>
    {
        public ModelsSection(WldParser.Helpers.BinaryFileReader f, string m = "LIST", string m2 = "MODL")
            : base(f, m, m2)
        {
        }

        protected override ModelInfo UnpackNode(WldParser.Helpers.BinaryFileReader file, int index, int entrySize)
        {
            // Мы сидим сразу после token_with_size (т.е. в начале payload этого MODL)
            int startOffset = file.Current;

            // file.skip # always 9, skip
            file.Skip(); // 4 байта
            // file.skip # always 1, skip
            file.Skip(); // 4 байта

            var model = new ModelInfo();

            // MODEL_FIELDS[:base]
            model.Name = file.Name();
            model.InfluencesCamera = file.Bool();
            model.NoCameraCheck = file.Bool();
            model.AntiGround = file.Bool();
            model.DefaultSkeleton = file.Int();
            model.UseSkeleton = file.Int();

            // camera (RMAC или 0)
            string cameraToken = file.Word();
            if (cameraToken == "RMAC")
            {
                var cam = new ModelCamera
                {
                    Camera = new ModelCameraValues
                    {
                        X = file.Float(),
                        Y = file.Float(),
                        Z = file.Float(),
                        Pitch = file.Float(),
                        Yaw = file.Float(),
                    },
                    Item = new ModelCameraValues
                    {
                        X = file.Float(),
                        Y = file.Float(),
                        Z = file.Float(),
                        Pitch = file.Float(),
                        Yaw = file.Float(),
                    }
                };
                model.Camera = cam;
            }
            else
            {
                // Камеры нет, в Ruby сюда писали просто 0 (4 байта),
                // мы уже их съели как "слово" != "RMAC".
            }

            // parent_folder_iid
            model.ParentFolderIid = file.Int();

            // attack_points
            int countAttackPoints = file.Int();
            for (int i = 0; i < countAttackPoints; i++)
            {
                var ap = new AttackPoint
                {
                    X = file.Float(),
                    Y = file.Float(),
                    Z = file.Float(),
                    Radius = file.Float()
                };
                model.AttackPoints.Add(ap);
            }

            model.Nmf = new WldParser.Items.NmfReader().Unpack(file);

            model.Index = index + 2;
            return model;
        }
    }
}
