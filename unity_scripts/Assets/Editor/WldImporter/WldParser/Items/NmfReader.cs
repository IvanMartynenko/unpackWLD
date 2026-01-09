using System;
using System.Collections.Generic;
using System.Linq;

namespace WldParser.Items
{
    public static class NmfConstants
    {
        public const int MatrixSize = 16;
    }

    // -------------------- MODEL --------------------

    public class NmfModel
    {
        public List<NmfNode> Nodes { get; } = new();
    }

    public class NmfNode
    {
        public int Index;          // index starts from 1 in Ruby
        public string Token;       // ROOT/LOCA/FRAM/JOIN/MESH
        public int ParentIid;      // 0 for ROOT
        public string Name;

        public INmfNodeData Data;  // FramData, JoinData, MeshData, or LocaData
    }

    public interface INmfNodeData { }

    // -------------------- FRAM / ROOT --------------------

    public class FramData : INmfNodeData
    {
        public float[][] Matrix; // 4x4

        public float[] Translation;
        public float[] Scaling;
        public float[] Rotation;

        public float[] RotatePivotTranslate;
        public float[] RotatePivot;
        public float[] ScalePivotTranslate;
        public float[] ScalePivot;
        public float[] Shear;

        public NmfAnim Anim; // optional
    }

    // ROOT in Ruby == FRAM
    public class RootData : FramData { }

    // -------------------- LOCA --------------------

    public class LocaData : INmfNodeData
    {
        public NmfAnim Anim;
        // Ruby returns {} (empty)
    }

    // -------------------- JOIN --------------------

    public class JoinData : INmfNodeData
    {
        public float[][] Matrix; // 4x4

        public float[] Translation;
        public float[] Scaling;
        public float[] Rotation;

        public float[][] RotationMatrix; // 4x4
        public float[] MinRotLimit;      // 3 floats
        public float[] MaxRotLimit;      // 3 floats

        public NmfAnim Anim; // optional
    }

    // -------------------- ANIM --------------------

    public class NmfAnim
    {
        public int Reserved;

        public NmfCurve Translation;
        public NmfCurve Rotation;
        public NmfCurve Scaling;
    }

    public class NmfCurve
    {
        // keys/values by coordinate: x/y/z
        public Dictionary<string, float[]> Keys { get; } = new();
        public Dictionary<string, float[]> Values { get; } = new();
    }

    // -------------------- MESH --------------------

    public class MeshData : INmfNodeData
    {
        public int TNum;
        public int VNum;

        // vbuf: vnum rows, each row has 10 floats
        public float[][] VBuf;

        // uvpt: vnum rows, each row has 2 floats
        public float[][] UvPt;

        public int INum;
        public int[][] IBuf; // triangles (each 3 indices)

        public int BackfaceCulling;
        public int Complex;
        public int Inside;
        public int Smooth;
        public int LightFlare;

        public List<NmfMaterial> Materials;

        public List<NmfAnimMesh> MeshAnim; // optional

        // anti-ground / unknown blocks
        public float[] UnknownFloats; // count * 3
        public int[] UnknownInts;     // count
    }

    public class NmfMaterial
    {
        public string Name;
        public int BlendMode;
        public int[] UnknownInts4; // 4 ints

        public int UvMappingFlipHorizontal;
        public int UvMappingFlipVertical;
        public int Rotate; // 0..3
        public float HorizontalStretch;
        public float VerticalStretch;

        public float Red, Green, Blue, Alpha;
        public float Red2, Green2, Blue2, Alpha2;

        public int[] UnknownZeroInts9; // 9 ints

        public NmfMaterialTexture Texture; // TXPG
        public NmfMaterialText Text;       // TEXT
    }

    public class NmfMaterialTexture
    {
        public string Name; // filename
        public int TexturePage;
        public int IndexTextureOnPage;
        public int X0, Y0, X2, Y2;
    }

    public class NmfMaterialText
    {
        public string Name; // filename
    }

    public class NmfAnimMesh
    {
        public int UnknownBool;
        public int UnknownSizeOfInts;
        public int[] UnknownInts;

        public float[] UnknownFloats3; // 3 floats

        public int UnknownSize1;
        public int UnknownSize2;
        public int UnknownSize3;

        public float[] UnknownFloats1; // s1 * 2
        public float[] UnknownFloats2; // s2 * 2
        public float[] UnknownFloats3b; // s3 * 2
    }

    // -------------------- PARSER --------------------


    public class NmfReader
    {
        public NmfModel Unpack(WldParser.Helpers.BinaryFileReader file)
        {
            // Ruby: token = file.token (читает 4 байта + int32==0)
            string header = file.Token();
            if (header != "NMF ")
                throw new StandardException($"Bad start of ModelList. Expected 'NMF ' but got '{header}'");

            var model = new NmfModel();

            int index = 1;
            while (true)
            {
                var (token, _size) = ReadTokenWithSizeLE(file);

                if (token == "END ")
                    break;

                // Ruby: file.int (0 from LOCA, 14 from MESH, other 2) — просто пропускаем
                file.Int();

                int parentIid = file.Int();
                string name = file.Name();

                INmfNodeData data = token switch
                {
                    "ROOT" => ParseRoot(file),
                    "LOCA" => ParseLoca(file),
                    "FRAM" => ParseFram(file),
                    "JOIN" => ParseJoin(file),
                    "MESH" => ParseMesh(file),
                    _ => throw new StandardException($"Unexpected token in MODEL: {token}")
                };

                model.Nodes.Add(new NmfNode
                {
                    Index = index,
                    Token = token,
                    ParentIid = parentIid,
                    Name = name,
                    Data = data
                });

                index++;
            }

            return model;
        }

        /// <summary>
        /// NMF token_with_size: 4 bytes token + int32 size (LE)
        /// (не используем file.TokenWithSize(), потому что он читает size как BE).
        /// </summary>
        private static (string token, int size) ReadTokenWithSizeLE(WldParser.Helpers.BinaryFileReader file)
        {
            string token = file.Word();
            int size = file.Int(); // LE
            return (token, size);
        }

        private static RootData ParseRoot(WldParser.Helpers.BinaryFileReader file)
        {
            var fram = ParseFram(file);
            return new RootData
            {
                Matrix = fram.Matrix,
                Translation = fram.Translation,
                Scaling = fram.Scaling,
                Rotation = fram.Rotation,
                RotatePivotTranslate = fram.RotatePivotTranslate,
                RotatePivot = fram.RotatePivot,
                ScalePivotTranslate = fram.ScalePivotTranslate,
                ScalePivot = fram.ScalePivot,
                Shear = fram.Shear,
                Anim = fram.Anim
            };
        }

        private static LocaData ParseLoca(WldParser.Helpers.BinaryFileReader file) => new();

        private static FramData ParseFram(WldParser.Helpers.BinaryFileReader file)
        {
            var res = new FramData
            {
                Matrix = ReadMatrix4x4(file),

                Translation = ReadFloat3(file),
                Scaling = ReadFloat3(file),
                Rotation = ReadFloat3(file),

                RotatePivotTranslate = ReadFloat3(file),
                RotatePivot = ReadFloat3(file),
                ScalePivotTranslate = ReadFloat3(file),
                ScalePivot = ReadFloat3(file),
                Shear = ReadFloat3(file),
            };

            string maybeAnim = file.Word(); // "ANIM" или "0\0\0\0"
            if (maybeAnim == "ANIM")
                res.Anim = ParseAnim(file);

            return res;
        }

        private static JoinData ParseJoin(WldParser.Helpers.BinaryFileReader file)
        {
            var res = new JoinData
            {
                Matrix = ReadMatrix4x4(file),

                Translation = ReadFloat3(file),
                Scaling = ReadFloat3(file),
                Rotation = ReadFloat3(file),

                RotationMatrix = ReadMatrix4x4(file),
                MinRotLimit = ReadFloat3(file),
                MaxRotLimit = ReadFloat3(file),
            };

            string maybeAnim = file.Word(); // "ANIM" или "0\0\0\0"
            if (maybeAnim == "ANIM")
                res.Anim = ParseAnim(file);

            return res;
        }

        private static NmfAnim ParseAnim(WldParser.Helpers.BinaryFileReader file)
        {
            var res = new NmfAnim
            {
                Reserved = file.Int()
            };

            int[] tSizes = file.Ints(3);
            int[] rSizes = file.Ints(3);
            int[] sSizes = file.Ints(3);

            res.Translation = ParseCurve(file, tSizes);
            res.Rotation = ParseCurve(file, rSizes);
            res.Scaling = ParseCurve(file, sSizes);

            return res;
        }

        private static NmfCurve ParseCurve(WldParser.Helpers.BinaryFileReader file, int[] sizes)
        {
            var res = new NmfCurve();
            string[] coords = { "x", "y", "z" };

            for (int i = 0; i < 3; i++)
            {
                int n = sizes[i];
                if (n <= 0) continue;

                res.Keys[coords[i]] = file.Floats(n);
                res.Values[coords[i]] = file.Floats(n);
            }

            return res;
        }

        private static MeshData ParseMesh(WldParser.Helpers.BinaryFileReader file)
        {
            var res = new MeshData
            {
                TNum = file.Int(),
                VNum = file.Int(),
            };

            const int vbufCount = 10;
            const int uvbufCount = 2;

            res.VBuf = SplitFloats(file.Floats(res.VNum * vbufCount), vbufCount);

            res.UvPt = SplitFloats(file.Floats(res.VNum * uvbufCount), uvbufCount);

            res.INum = file.Int();

            // Ruby: ints16(inum), each_slice(3); padding if odd
            int[] ibuf = ReadInts16AsInt(file, res.INum);
            res.IBuf = SplitInts(ibuf, 3);

            if ((res.INum & 1) == 1)
                file.Int16(); // padding (ushort), значение не важно

            res.BackfaceCulling = file.Int();
            res.Complex = file.Int();
            res.Inside = file.Int();
            res.Smooth = file.Int();
            res.LightFlare = file.Int();

            int materialCount = file.Int();
            if (materialCount > 0)
            {
                res.Materials = new List<NmfMaterial>(materialCount);
                for (int i = 0; i < materialCount; i++)
                    res.Materials.Add(ParseMtrl(file));
            }

            string maybeAnim = file.Word();
            if (maybeAnim == "ANIM")
                res.MeshAnim = ParseAnimMesh(file);

            int unknownCountFloats = file.Int();
            if (unknownCountFloats > 0)
                res.UnknownFloats = file.Floats(unknownCountFloats * 3);

            int unknownCountInts = file.Int();
            if (unknownCountInts > 0)
                res.UnknownInts = file.Ints(unknownCountInts);

            return res;
        }

        private static NmfMaterial ParseMtrl(WldParser.Helpers.BinaryFileReader file)
        {
            string token = file.Word();
            if (token != "MTRL")
                throw new StandardException($"Expected 'MTRL' but got '{token}'");

            var res = new NmfMaterial
            {
                Name = file.Name(),
                BlendMode = file.Int(),
                UnknownInts4 = file.Ints(4),

                UvMappingFlipHorizontal = file.Int(),
                UvMappingFlipVertical = file.Int(),
                Rotate = file.Int(),

                HorizontalStretch = file.Float(),
                VerticalStretch = file.Float(),

                Red = file.Float(),
                Green = file.Float(),
                Blue = file.Float(),
                Alpha = file.Float(),

                Red2 = file.Float(),
                Green2 = file.Float(),
                Blue2 = file.Float(),
                Alpha2 = file.Float(),

                UnknownZeroInts9 = file.Ints(9),
            };

            string next = file.Word();
            if (next == "TXPG")
            {
                res.Texture = new NmfMaterialTexture
                {
                    Name = file.Filename(),
                    TexturePage = file.Int(),
                    IndexTextureOnPage = file.Int(),
                    X0 = file.Int(),
                    Y0 = file.Int(),
                    X2 = file.Int(),
                    Y2 = file.Int(),
                };
            }
            else if (next == "TEXT")
            {
                res.Text = new NmfMaterialText
                {
                    Name = file.Filename()
                };
            }

            return res;
        }

        private static List<NmfAnimMesh> ParseAnimMesh(WldParser.Helpers.BinaryFileReader file)
        {
            var res = new List<NmfAnimMesh> { ParseSingleAnimMesh(file) };

            while (true)
            {
                string t = file.Word();
                if (t != "ANIM")
                    break;

                res.Add(ParseSingleAnimMesh(file));
            }

            return res;
        }

        private static NmfAnimMesh ParseSingleAnimMesh(WldParser.Helpers.BinaryFileReader file)
        {
            var m = new NmfAnimMesh
            {
                UnknownBool = file.Int(),
                UnknownSizeOfInts = file.Int(),
            };

            m.UnknownInts = file.Ints(m.UnknownSizeOfInts);
            m.UnknownFloats3 = file.Floats(3);

            m.UnknownSize1 = file.Int();
            m.UnknownSize2 = file.Int();
            m.UnknownSize3 = file.Int();

            m.UnknownFloats1 = file.Floats(m.UnknownSize1 * 2);
            m.UnknownFloats2 = file.Floats(m.UnknownSize2 * 2);
            m.UnknownFloats3b = file.Floats(m.UnknownSize3 * 2);

            return m;
        }

        // -------------------- READ HELPERS --------------------

        private static float[][] ReadMatrix4x4(WldParser.Helpers.BinaryFileReader file)
            => SplitFloats(file.Floats(NmfConstants.MatrixSize), 4);

        private static float[] ReadFloat3(WldParser.Helpers.BinaryFileReader file)
            => file.Floats(3);

        private static int[] ReadInts16AsInt(WldParser.Helpers.BinaryFileReader file, int count)
            => file.Ints16(count).Select(x => (int)x).ToArray();

        private static float[][] SplitFloats(float[] src, int stride)
        {
            int count = src.Length / stride;
            var result = new float[count][];

            for (int i = 0; i < count; i++)
            {
                result[i] = new float[stride];
                Array.Copy(src, i * stride, result[i], 0, stride);
            }

            return result;
        }

        private static int[][] SplitInts(int[] src, int stride)
        {
            int count = src.Length / stride;
            var result = new int[count][];

            for (int i = 0; i < count; i++)
            {
                result[i] = new int[stride];
                Array.Copy(src, i * stride, result[i], 0, stride);
            }

            return result;
        }

    }

    // Просто чтобы не тянуть System.Exception везде, можно и обычный Exception оставить.
    public class StandardException : Exception
    {
        public StandardException(string message) : base(message) { }
    }
}
