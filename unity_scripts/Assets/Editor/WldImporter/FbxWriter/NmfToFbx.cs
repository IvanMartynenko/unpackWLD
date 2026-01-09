using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEngine;
using WldParser.Items;

namespace WldParser.FbxWriter
{
    public class NmfToFbx
    {
        // -----------------------------------------------------------------------------
        // CONSTANTS & CONFIG (Matching Python)
        // -----------------------------------------------------------------------------
        private const double FPS = 24.0;
        private const double RAD2DEG = 180.0 / Math.PI;
        private const long KTIME_SEC = 46186158000;
        private const long KTIME_PER_FRAME = 1924423250; // int(KTIME_SEC / FPS)

        // ID GENERATOR
        private long _idCounter = 100000;
        private long NextId() => ++_idCounter;

        private System.Random _rnd = new System.Random();
        private long GenerateRndId() => (long)((DateTime.UtcNow.Ticks / 10000) + _rnd.Next(0, 100000));

        // -----------------------------------------------------------------------------
        // MAIN ENTRY POINT
        // -----------------------------------------------------------------------------
        public FbxNode CreateFbxDocument(NmfModel model, string fileName)
        {
            // Reset ID for consistency if needed, strictly mimicking main()
            // _idCounter = 1776339759000; 

            // 1. Process Nodes (Pre-calculation)
            var sceneNodes = ProcessSceneNodes(model, fileName);

            // 2. Generate FBX Structure
            var root = new FbxNode(""); // Virtual Root wrapper

            // Header & GlobalSettings
            root.Children.AddRange(GenerateFbxHeaderJson());
            
            // Definitions
            root.Children.AddRange(GenerateFbxDefinitions(sceneNodes));

            // Objects
            var objectsNode = new FbxNode("Objects");
            var connectionsNode = new FbxNode("Connections");
            
            AssembleFbx(sceneNodes, objectsNode, connectionsNode);
            
            // Takes (Animation Metadata)
            var takesNode = new FbxNode("Takes");
            var currentTake = new FbxNode("Current"); currentTake.AddProperty("Take 001", FbxPropType.String);
            var takeNode = new FbxNode("Take"); takeNode.AddProperty("Take 001", FbxPropType.String);
            var takeFileName = new FbxNode("FileName"); takeFileName.AddProperty("Take_001.tak", FbxPropType.String);
            takeNode.Children.Add(takeFileName);
            takesNode.Children.Add(currentTake);
            takesNode.Children.Add(takeNode);

            root.Children.Add(objectsNode);
            root.Children.Add(connectionsNode);
            root.Children.Add(takesNode);

            return root;
        }

        // -----------------------------------------------------------------------------
        // MATH & VECTOR UTILS (Exact Python Ports)
        // -----------------------------------------------------------------------------
        
        private double Dot(double[] a, double[] b) => (a[0] * b[0]) + (a[1] * b[1]) + (a[2] * b[2]);

        private double[] Sub(double[] a, double[] b) => new double[] { a[0] - b[0], a[1] - b[1], a[2] - b[2] };

        private double[] Cross(double[] a, double[] b)
        {
            return new double[] {
                a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0]
            };
        }

        private double[] Normalize(double[] v)
        {
            double l = Math.Sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
            if (l == 0.0) return new double[] { 0, 0, 0 };
            return new double[] { v[0] / l, v[1] / l, v[2] / l };
        }

        private double Len3(double[] v) => Math.Sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);

        private double[] Extract3x3(float[][] m4)
        {
            if (m4 == null) return null;
            // Flatten logic implied in Python logic
            // Python: a = [c for row in m4 for c in row] -> returns [[a0,a1,a2]...]
            // We just return the 9 elements needed for logic
            return new double[] 
            { 
                m4[0][0], m4[0][1], m4[0][2],
                m4[1][0], m4[1][1], m4[1][2],
                m4[2][0], m4[2][1], m4[2][2]
            };
        }

        private double[] MatrixRowMajorToEulerXyzStandard(double[] m)
        {
            if (m == null) return new double[] { 0, 0, 0 };

            // Python reads as Row-Major
            double m00 = m[0], m01 = m[1], m02 = m[2];
            double m10 = m[3], m11 = m[4], m12 = m[5];
            double m20 = m[6], m21 = m[7], m22 = m[8];

            // TRANSPOSE (Logic from Python script)
            double r00 = m00, r01 = m10, r02 = m20;
            double r10 = m01, r11 = m11, r12 = m21;
            double r20 = m02, r21 = m12, r22 = m22;

            double x, y, z;

            if (Math.Abs(r20) < 0.999999)
            {
                y = Math.Asin(-r20);
                x = Math.Atan2(r21, r22);
                z = Math.Atan2(r10, r00);
            }
            else
            {
                y = Math.Asin(-r20);
                x = Math.Atan2(-r12, r11);
                z = 0.0;
            }

            return new double[] { x * RAD2DEG, y * RAD2DEG, z * RAD2DEG };
        }

private void DecomposeDirectXRowMajor(float[][] m, out double[] t, out double[] s, out double[] r)
        {
            // 1. Translation (В Row-Major матрице DirectX это последняя строка)
            // Python: tx, ty, tz = m[0][3], m[1][3], m[2][3] (из транспонированной матрицы)
            // Это соответствует m[3][0], m[3][1], m[3][2] в исходной
            double tx = m[3][0];
            double ty = m[3][1];
            double tz = m[3][2];

            // 2. Extract Rows (Basis vectors: X, Y, Z axes)
            // Python: r0 = [m[0][0], m[1][0], m[2][0]] (из транспонированной) -> Row 0 исходной
            double[] r0 = { m[0][0], m[0][1], m[0][2] };
            double[] r1 = { m[1][0], m[1][1], m[1][2] };
            double[] r2 = { m[2][0], m[2][1], m[2][2] };

            // 3. Calculate Scale
            double sx = Len3(r0);
            double sy = Len3(r1);
            double sz = Len3(r2);

            // 4. Determinant Check (Mirroring logic)
            // Смешанное произведение (Triple Product): (r0 x r1) . r2
            // Это определяет, вывернута ли система координат наизнанку
            double det = r0[0] * (r1[1] * r2[2] - r1[2] * r2[1])
                       - r0[1] * (r1[0] * r2[2] - r1[2] * r2[0])
                       + r0[2] * (r1[0] * r2[1] - r1[1] * r2[0]);

            if (det < 0)
            {
                sz = -sz; // Инвертируем Z scale
            }

            // Защита от деления на ноль
            sx = (sx != 0) ? sx : 1.0;
            sy = (sy != 0) ? sy : 1.0;
            sz = (sz != 0) ? sz : 1.0;

            // 5. Normalize Rows (Получаем чистую матрицу вращения)
            // Важно: если sz отрицательный, деление здесь инвертирует вектор r2, 
            // исправляя матрицу вращения (убирая из неё scale -1).
            
            // Python naming convention mapping:
            // r00, r10, r20 = r0[0]/sx, r0[1]/sx, r0[2]/sx
            double r00 = r0[0] / sx, r10 = r0[1] / sx, r20 = r0[2] / sx;
            double r01 = r1[0] / sy, r11 = r1[1] / sy, r21 = r1[2] / sy;
            double r02 = r2[0] / sz, r12 = r2[1] / sz, r22 = r2[2] / sz;

            // 6. Extract Euler Angles (XYZ)
            double rx, ry, rz;
            
            // Python: ry = math.asin(-r20) if abs(r20) <= 1.0 else ...
            // r20 здесь соответствует компоненту Z первого базисного вектора (m[0][2])
            
            if (Math.Abs(r20) <= 1.0)
                ry = Math.Asin(-r20);
            else
                ry = Math.Asin(r20 > 0 ? -1.0 : 1.0);

            if (Math.Abs(Math.Cos(ry)) > 1e-6)
            {
                // ry уже посчитан
                rx = Math.Atan2(r21, r22);
                rz = Math.Atan2(r10, r00);
            }
            else
            {
                // Gimbal lock
                ry = Math.Asin(r20 > 0 ? -1.0 : 1.0);
                rx = Math.Atan2(-r12, r11);
                rz = 0.0;
            }

            // Output results
            t = new double[] { tx, ty, tz };
            s = new double[] { sx, sy, sz };
            r = new double[] { rx, ry, rz }; // Возвращаем радианы, как в Python функции
        }
        private bool IsMeshRightHanded(int[][] ibuf, float[][] vbuf)
        {
            // vbuf layout: [x,y,z, nx,ny,nz, u,v]
            if (vbuf == null || vbuf.Length == 0) return true;
            if (vbuf[0].Length <= 5) return true; // No normals -> assume true

            int pos_cnt = 0;
            int neg_cnt = 0;

            // Pre-convert to double arrays for helper functions
            var pos = new double[vbuf.Length][];
            var nrm = new double[vbuf.Length][];
            for(int i=0; i<vbuf.Length; i++)
            {
                pos[i] = new double[] { vbuf[i][0], vbuf[i][1], vbuf[i][2] };
                nrm[i] = new double[] { vbuf[i][3], vbuf[i][4], vbuf[i][5] };
            }

            foreach (var tri in ibuf)
            {
                int i0 = tri[0], i1 = tri[1], i2 = tri[2];
                var p0 = pos[i0]; var p1 = pos[i1]; var p2 = pos[i2];
                
                var n_geom = Normalize(Cross(Sub(p1, p0), Sub(p2, p0)));
                
                var n_avg = Normalize(new double[] {
                    nrm[i0][0] + nrm[i1][0] + nrm[i2][0],
                    nrm[i0][1] + nrm[i1][1] + nrm[i2][1],
                    nrm[i0][2] + nrm[i1][2] + nrm[i2][2]
                });

                double s = Dot(n_geom, n_avg);
                if (s >= 0) pos_cnt++; else neg_cnt++;
            }
            return pos_cnt >= neg_cnt;
        }

        // -----------------------------------------------------------------------------
        // DATA STRUCTURES
        // -----------------------------------------------------------------------------
        class ProcessedNode
        {
            public long Id;
            public long ParentId;
            public string Name;
            public string NodeType; // fram, joint, locator, mesh
            public bool IsMeshContainer; // logic: fram with mesh child
            public bool WithAnimation;

            // Transforms
            public double[] T = { 0, 0, 0 };
            public double[] R = { 0, 0, 0 };
            public double[] S = { 1, 1, 1 };

            // Fram/Joint specific
            public double[] RotatePivotTranslate;
            public double[] RotatePivot;
            public double[] ScalePivotTranslate;
            public double[] ScalePivot;
            public double[] JointOrient;

            // Mesh Specific
            public List<double[]> Verts;
            public List<int> PVI; // PolygonVertexIndex
            public List<int> Edges;
            public List<double> UV;
            public List<int> UVIndex;
            public List<double> Normals;
            public List<double> NormalsW;

            // Materials
            public List<MatInfo> MaterialsData = new List<MatInfo>();

            // Animations
            public Dictionary<string, Dictionary<string, AnimCurveData>> Animations;
        }

        class MatInfo
        {
            public string MatName;
            public double R, G, B, Opacity;
            public bool HasTex;
            public string TexPath;
            public double RepeatU, RepeatV;
            public double RotateUV;
        }

        class AnimCurveData
        {
            public List<float> Frames;
            public List<float> Values;
        }

        // -----------------------------------------------------------------------------
        // NODE PROCESSING
        // -----------------------------------------------------------------------------
// -----------------------------------------------------------------------------
        // NODE PROCESSING
        // -----------------------------------------------------------------------------
        private List<ProcessedNode> ProcessSceneNodes(NmfModel model, string fileName)
        {
            var result = new List<ProcessedNode>();
            var indexMap = new Dictionary<int, ProcessedNode>();

            // 1. Assign IDs and basic map
            foreach (var raw in model.Nodes)
            {
                var p = new ProcessedNode { Id = NextId(), Name = raw.Name };
                indexMap[raw.Index] = p;
                result.Add(p);
            }

            // 2. Process data
            for (int i = 0; i < model.Nodes.Count; i++)
            {
                var raw = model.Nodes[i];
                var p = result[i];

                // Parent
                if (raw.ParentIid != 0 && indexMap.TryGetValue(raw.ParentIid, out var parentNode))
                {
                    p.ParentId = parentNode.Id;
                }
                else
                {
                    p.ParentId = 0;
                }

                string w = raw.Token; // "FRAM", "ROOT", "JOIN", "LOCA", "MESH"

                if (w == "ROOT" || w == "FRAM")
                {
                    p.NodeType = "fram";
                    var d = raw.Data as FramData;
                    if (d != null)
                    {
                        // Считываем пивоты
                        p.RotatePivotTranslate = ToDouble3(d.RotatePivotTranslate);
                        p.RotatePivot = ToDouble3(d.RotatePivot);
                        p.ScalePivotTranslate = ToDouble3(d.ScalePivotTranslate);
                        p.ScalePivot = ToDouble3(d.ScalePivot);
                        p.Animations = AnimationBuildTracksByAxis(d.Anim);

                        if (w == "ROOT")
                        {
                            // Python Logic:
                            // S = [[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
                            // M2 = S * Matrix (Row-Major mult). 
                            // Эффект: Инверсия первой строки (или столбца в зависимости от интерпретации, здесь Row 0).
                            
                            // 1. Клонируем матрицу, чтобы не ломать исходные данные
                            float[][] m2 = new float[4][];
                            for(int r=0; r<4; r++) m2[r] = (float[])d.Matrix[r].Clone();

                            // 2. Применяем Scale (-1, 1, 1, 1) -> Инвертируем Row 0
                            m2[0][0] *= -1f;
                            m2[0][1] *= -1f;
                            m2[0][2] *= -1f;
                            m2[0][3] *= -1f;

                            // 3. Decompose
                            DecomposeDirectXRowMajor(m2, out p.T, out p.S, out double[] rads);
                            p.R = new double[] { rads[0] * RAD2DEG, rads[1] * RAD2DEG, rads[2] * RAD2DEG };

                            // 4. Scale Translation and Scaling by 100
                            p.T[0] *= 100.0;
                            p.T[1] *= 100.0;
                            p.T[2] *= 100.0; // В Python инверсия Z (* -1) закомментирована, убираем и здесь.

                            p.S[0] *= 100.0;
                            p.S[1] *= 100.0;
                            p.S[2] *= 100.0;

                            p.R[0] += 90.0;

                            if(fileName == "Alarmanlage")
                            {
                                string tStr = string.Join(", ", p.T);
                                string rStr = string.Join(", ", p.R);
                                string sStr = string.Join(", ", p.S);
                                Debug.LogWarning($"[Alarmanlage DEBUG]\nPosition (T): {tStr}\nRotation (R): {rStr}\nScale (S): {sStr}"); 
                            }

                            p.Animations = null; 
                            p.WithAnimation = false;
                        }
                        else // FRAM
                        {
                            // Python Logic: 
                            // if rotate_pivot_translate == [0,0,0] and rotate_pivot == [0,0,0] ...
                            
                            bool pivotsZero = IsZero(p.RotatePivotTranslate) && 
                                              IsZero(p.RotatePivot) && 
                                              IsZero(p.ScalePivotTranslate) && 
                                              IsZero(p.ScalePivot);

                            if (pivotsZero)
                            {
                                // Если пивотов нет, считаем через матрицу
                                DecomposeDirectXRowMajor(d.Matrix, out p.T, out p.S, out double[] rads);
                                p.R = new double[] { rads[0] * RAD2DEG, rads[1] * RAD2DEG, rads[2] * RAD2DEG };
                            }
                            else
                            {
                                // Если пивоты есть, берем прямые значения
                                p.T = ToDouble3(d.Translation);
                                p.S = ToDouble3(d.Scaling);
                                p.R = new double[] { d.Rotation[0] * RAD2DEG, d.Rotation[1] * RAD2DEG, d.Rotation[2] * RAD2DEG };
                            }
                        }
                    }
                }
                else if (w == "JOIN")
                {
                    p.NodeType = "joint";
                    var d = raw.Data as JoinData;
                    if (d != null)
                    {
                        p.T = ToDouble3(d.Translation);
                        p.S = ToDouble3(d.Scaling);
                        p.R = new double[] { d.Rotation[0] * RAD2DEG, d.Rotation[1] * RAD2DEG, d.Rotation[2] * RAD2DEG };
                        
                        var m3 = Extract3x3(d.RotationMatrix);
                        p.JointOrient = MatrixRowMajorToEulerXyzStandard(m3);
                        p.Animations = AnimationBuildTracksByAxis(d.Anim);
                    }
                }
                else if (w == "LOCA")
                {
                    p.NodeType = "locator";
                    var d = raw.Data as LocaData;
                    if (d != null)
                    {
                        // Python использует get с дефолтными значениями, здесь аналогично
                        // p.T = ToDouble3(d.Translation); 
                        // p.S = ToDouble3(d.Scaling);
                        // Если d.Scaling пустой (вдруг), ToDouble3 вернет 0,0,0, но для Scale лучше 1,1,1
                        // if (d.Scaling == null) p.S = new double[] { 1, 1, 1 }; 

                        // p.R = d.Rotation != null 
                        //     ? new double[] { d.Rotation[0] * RAD2DEG, d.Rotation[1] * RAD2DEG, d.Rotation[2] * RAD2DEG }
                        //     : new double[] { 0, 0, 0 };

                        // p.Animations = AnimationBuildTracksByAxis(d.Anim);
                    }
                }
                else if (w == "MESH")
                {
                    p.NodeType = "mesh";
                    var d = raw.Data as MeshData;
                    if (d != null)
                    {
                        // Winding order check
                        var rawIbuf = d.IBuf;
                        if (!IsMeshRightHanded(rawIbuf, d.VBuf))
                        {
                            // Flip logic: [0, 2, 1]
                            var fixedIbuf = new int[rawIbuf.Length][];
                            for(int k=0; k<rawIbuf.Length; k++)
                                fixedIbuf[k] = new int[] { rawIbuf[k][0], rawIbuf[k][2], rawIbuf[k][1] };
                            rawIbuf = fixedIbuf;
                        }

                        // Verts
                        p.Verts = new List<double[]>();
                        foreach(var v in d.VBuf) p.Verts.Add(new double[] { v[0], v[1], v[2] });

                        // PVI
                        p.PVI = new List<int>();
                        foreach (var tri in rawIbuf)
                        {
                            p.PVI.Add(tri[0]);
                            p.PVI.Add(tri[1]);
                            p.PVI.Add(-(tri[2] + 1));
                        }

                        p.Edges = BuildFbxEdgesFromPvi(p.PVI);

                        // UVs
                        p.UV = new List<double>();
                        p.UVIndex = new List<int>();
                        foreach (var v in d.VBuf)
                        {
                            p.UV.Add(v.Length > 6 ? v[6] : 0.0);
                            p.UV.Add(v.Length > 7 ? v[7] : 0.0);
                        }
                        foreach(var tri in rawIbuf)
                        {
                            p.UVIndex.Add(tri[0]); p.UVIndex.Add(tri[1]); p.UVIndex.Add(tri[2]);
                        }

                        // Normals
                        p.Normals = new List<double>();
                        p.NormalsW = new List<double>();
                        for(int k=0; k<rawIbuf.Length; k++)
                        {
                            var tri = rawIbuf[k];
                            var v0 = p.Verts[tri[0]];
                            var v1 = p.Verts[tri[1]];
                            var v2 = p.Verts[tri[2]];
                            var n = Normalize(Cross(Sub(v1, v0), Sub(v2, v0)));
                            for(int z=0; z<3; z++)
                            {
                                p.Normals.AddRange(n);
                                p.NormalsW.Add(1.0);
                            }
                        }

                        // Materials
                        if (d.Materials == null || d.Materials.Count == 0)
                        {
                            p.MaterialsData.Add(new MatInfo {
                                MatName = $"lambert_{p.Name}",
                                R=0.8, G=0.8, B=0.8, Opacity=1.0, HasTex=false
                            });
                        }
                        else
                        {
                            foreach (var m in d.Materials)
                            {
                                string matName = (string.IsNullOrEmpty(m.Name) ? "lambert" : m.Name) + $"_{p.Name}";
                                double a = m.Alpha; 
                                
                                string texPath = null;
                                if (m.Texture != null && !string.IsNullOrEmpty(m.Texture.Name))
                                {
                                    string tPath = m.Texture.Name.Replace('\\', '/');
                                    string filenameRaw = Path.GetFileNameWithoutExtension(tPath);
                                    string textureName = $"{filenameRaw}_{m.Texture.TexturePage}.png";
                                    texPath = $"Assets/WLD_Export/Textures/png/{textureName}";
                                }

                                p.MaterialsData.Add(new MatInfo
                                {
                                    MatName = matName,
                                    R = m.Red, G = m.Green, B = m.Blue,
                                    Opacity = a,
                                    HasTex = texPath != null,
                                    TexPath = texPath,
                                    RepeatU = m.HorizontalStretch,
                                    RepeatV = m.VerticalStretch,
                                    RotateUV = m.Rotate
                                });
                            }
                        }
                    }
                }

                p.WithAnimation = (p.Animations != null && p.Animations.Count > 0);
            }

            // Post-process: Mark FRAMs as meshes if they have MESH children
            var idToNode = result.ToDictionary(n => n.Id);
            foreach (var node in result)
            {
                if (node.NodeType == "mesh")
                {
                    if (idToNode.ContainsKey(node.ParentId))
                    {
                        var parentNode = idToNode[node.ParentId];
                        if (parentNode.NodeType == "fram")
                        {
                            parentNode.IsMeshContainer = true;
                        }
                    }
                }
            }

            return result;
        }

        // Вспомогательный метод для проверки нулевых векторов
        private bool IsZero(double[] v)
        {
            if (v == null) return true;
            return Math.Abs(v[0]) < 1e-6 && Math.Abs(v[1]) < 1e-6 && Math.Abs(v[2]) < 1e-6;
        }
        private List<int> BuildFbxEdgesFromPvi(List<int> pvi)
        {
            var edges = new List<int>();
            var seen = new HashSet<string>();
            int polyStart = 0;
            int n = pvi.Count;
            
            for(int i=0; i<n; i++)
            {
                if (pvi[i] < 0)
                {
                    int polyEnd = i;
                    for(int j=polyStart; j <= polyEnd; j++)
                    {
                        int vA = (pvi[j] < 0) ? (-pvi[j] - 1) : pvi[j];
                        int nextIdx = (j < polyEnd) ? j + 1 : polyStart;
                        int vB_val = pvi[nextIdx];
                        int vB = (vB_val < 0) ? (-vB_val - 1) : vB_val;

                        int k1 = vA < vB ? vA : vB;
                        int k2 = vA < vB ? vB : vA;
                        string key = $"{k1}_{k2}";
                        
                        if (!seen.Contains(key))
                        {
                            seen.Add(key);
                            edges.Add(j);
                        }
                    }
                    polyStart = i + 1;
                }
            }
            return edges;
        }

        // -----------------------------------------------------------------------------
        // ANIMATION HELPER
        // -----------------------------------------------------------------------------
        private Dictionary<string, Dictionary<string, AnimCurveData>> AnimationBuildTracksByAxis(NmfAnim anim)
        {
            if (anim == null) return null;
            var result = new Dictionary<string, Dictionary<string, AnimCurveData>>();
            string[] axes = { "x", "y", "z" };

            void ProcessTrack(string name, NmfCurve curve)
            {
                if (curve == null) return;
                var trackHash = new Dictionary<string, AnimCurveData>();
                
                foreach(var ax in axes)
                {
                    if (!curve.Keys.ContainsKey(ax)) continue;
                    float[] tlist = curve.Keys[ax];
                    float[] vlist = curve.Values[ax];
                    if (tlist == null || vlist == null) continue;

                    var frames = new List<float>();
                    foreach(var t in tlist) frames.Add(t * (float)FPS);

                    var vals = new List<float>();
                    foreach(var v in vlist) vals.Add(name == "rotation" ? v * (float)RAD2DEG : v);

                    trackHash[ax] = new AnimCurveData { Frames = frames, Values = vals };
                }
                if (trackHash.Count > 0) result[name] = trackHash;
            }

            ProcessTrack("translation", anim.Translation);
            ProcessTrack("rotation", anim.Rotation);
            ProcessTrack("scaling", anim.Scaling);

            return result.Count > 0 ? result : null;
        }

        // -----------------------------------------------------------------------------
        // FBX GENERATION LOGIC
        // -----------------------------------------------------------------------------
        private List<FbxNode> GenerateFbxHeaderJson()
        {
            var now = DateTime.Now;
            int ms = now.Millisecond;
            
            var nodes = new List<FbxNode>();

            var ext = new FbxNode("FBXHeaderExtension");
            var v = new FbxNode("FBXHeaderVersion"); v.AddProperty(1003, FbxPropType.Int); ext.Children.Add(v);
            var fbxV = new FbxNode("FBXVersion"); fbxV.AddProperty(7500, FbxPropType.Int); ext.Children.Add(fbxV);
            var enc = new FbxNode("EncryptionType"); enc.AddProperty(0, FbxPropType.Int); ext.Children.Add(enc);

            var timeStamp = new FbxNode("CreationTimeStamp");
            timeStamp.Children.Add(CreatePropNode("Version", 1000));
            timeStamp.Children.Add(CreatePropNode("Year", now.Year));
            timeStamp.Children.Add(CreatePropNode("Month", now.Month));
            timeStamp.Children.Add(CreatePropNode("Day", now.Day));
            timeStamp.Children.Add(CreatePropNode("Hour", now.Hour));
            timeStamp.Children.Add(CreatePropNode("Minute", now.Minute));
            timeStamp.Children.Add(CreatePropNode("Second", now.Second));
            timeStamp.Children.Add(CreatePropNode("Millisecond", ms));
            ext.Children.Add(timeStamp);

            var creator = new FbxNode("Creator"); creator.AddProperty("FBX SDK/FBX Plugins version 2020.3.6", FbxPropType.String);
            ext.Children.Add(creator);
            
            // SceneInfo
            var sceneInfo = new FbxNode("SceneInfo");
            sceneInfo.AddProperty("GlobalInfo::SceneInfo", FbxPropType.String);
            sceneInfo.AddProperty("UserData", FbxPropType.String);
            sceneInfo.Children.Add(CreateStringNode("Type", "UserData"));
            sceneInfo.Children.Add(CreatePropNode("Version", 100));
            var meta = new FbxNode("MetaData");
            meta.Children.Add(CreatePropNode("Version", 100));
            meta.Children.Add(CreateStringNode("Title", ""));
            meta.Children.Add(CreateStringNode("Subject", ""));
            meta.Children.Add(CreateStringNode("Author", ""));
            meta.Children.Add(CreateStringNode("Keywords", ""));
            meta.Children.Add(CreateStringNode("Revision", ""));
            meta.Children.Add(CreateStringNode("Comment", ""));
            sceneInfo.Children.Add(meta);
            
            var props = new FbxNode("Properties70");
            AddProp(props, "DocumentUrl", "KString", "Url", "", "D:\\export.fbx");
            AddProp(props, "SrcDocumentUrl", "KString", "Url", "", "D:\\export.fbx");
            AddProp(props, "Original|ApplicationVendor", "KString", "", "", "Autodesk");
            AddProp(props, "Original|ApplicationName", "KString", "", "", "Maya");
            AddProp(props, "Original|ApplicationVersion", "KString", "", "", "2025");
            sceneInfo.Children.Add(props);
            
            ext.Children.Add(sceneInfo);
            nodes.Add(ext);

            // FileId (Raw binary data string simulation)
            var fileId = new FbxNode("FileId");
            byte[] guidBytes = Guid.NewGuid().ToByteArray();
            fileId.AddProperty(guidBytes, FbxPropType.Bytes);
            // fileId.AddProperty(",\\xb0(\\xea\\xb7%\\xcd\\xc0\\xbd\\xc8\\xb3 \\xa6!\\xf6\\xff", FbxPropType.String); // Using String to represent raw
            nodes.Add(fileId);

            var cTime = new FbxNode("CreationTime");
            cTime.AddProperty($"{now:yyyy-MM-dd} {now:HH}:{now:mm}:{now:ss}:{ms:000}", FbxPropType.String);
            nodes.Add(cTime);
            
            var footerCreator = new FbxNode("Creator");
            footerCreator.AddProperty("FBX SDK/FBX Plugins version 2020.3.6 build=0", FbxPropType.String);
            nodes.Add(footerCreator);

            // GlobalSettings
            var glob = new FbxNode("GlobalSettings");
            glob.Children.Add(CreatePropNode("Version", 1000));
            var globProps = new FbxNode("Properties70");
            AddProp(globProps, "UpAxis", "int", "Integer", "", 1);
            AddProp(globProps, "UpAxisSign", "int", "Integer", "", 1);
            AddProp(globProps, "FrontAxis", "int", "Integer", "", 2);
            AddProp(globProps, "FrontAxisSign", "int", "Integer", "", 1);
            AddProp(globProps, "CoordAxis", "int", "Integer", "", 0);
            AddProp(globProps, "CoordAxisSign", "int", "Integer", "", 1);
            AddProp(globProps, "UnitScaleFactor", "double", "Number", "", 1.0);
            AddProp(globProps, "OriginalUnitScaleFactor", "double", "Number", "", 1.0);
            AddProp(globProps, "TimeMode", "enum", "", "", 11);
            AddProp(globProps, "TimeProtocol", "enum", "", "", 2);
            AddProp(globProps, "SnapOnFrameMode", "enum", "", "", 0);
            glob.Children.Add(globProps);
            nodes.Add(glob);

            // Documents
            var docs = new FbxNode("Documents");
            docs.Children.Add(CreatePropNode("Count", 1));
            var doc = new FbxNode("Document");
            doc.AddProperty(1780765614704L, FbxPropType.Long);
            doc.AddProperty("", FbxPropType.String);
            doc.AddProperty("Scene", FbxPropType.String);
            var docProps = new FbxNode("Properties70");
            AddProp(docProps, "SourceObject", "object", "", "");
            AddProp(docProps, "ActiveAnimStackName", "KString", "", "", "Take 001");
            doc.Children.Add(docProps);
            var rootNodeId = new FbxNode("RootNode");
            rootNodeId.AddProperty(0L, FbxPropType.Long);
            doc.Children.Add(rootNodeId);
            docs.Children.Add(doc);
            nodes.Add(docs);

            nodes.Add(new FbxNode("References"));

            return nodes;
        }

        private List<FbxNode> GenerateFbxDefinitions(List<ProcessedNode> nodes)
        {
            var defs = new List<FbxNode>();
            var defNode = new FbxNode("Definitions");

            int modelCount = nodes.Count(n => n.NodeType == "fram" || n.NodeType == "joint" || n.NodeType == "locator");
            int meshCount = nodes.Count(n => n.NodeType == "mesh");
            int total = modelCount + meshCount + 1; // +1 GlobalSettings

            defNode.Children.Add(CreatePropNode("Version", 100));
            defNode.Children.Add(CreatePropNode("Count", total));
            
            defNode.Children.Add(CreateDefType("GlobalSettings", 1));
            defNode.Children.Add(CreateDefType("Model", modelCount, "FbxNode"));
            defNode.Children.Add(CreateDefType("Geometry", meshCount, "Geometry"));
            defNode.Children.Add(CreateDefType("AnimationStack", 1, "FbxAnimStack"));
            defNode.Children.Add(CreateDefType("AnimationLayer", 1, "FbxAnimLayer"));
            defNode.Children.Add(CreateDefType("AnimationCurve", 0));
            defNode.Children.Add(CreateDefType("AnimationCurveNode", 0, "FbxAnimCurveNode"));

            defs.Add(defNode);
            return defs;
        }

        private FbxNode CreateDefType(string name, int count, string templ = null)
        {
            var n = new FbxNode("ObjectType");
            n.AddProperty(name, FbxPropType.String);
            if (templ != null)
            {
                var cnt = new FbxNode("Count"); cnt.AddProperty(count, FbxPropType.Int); n.Children.Add(cnt);
                var pt = new FbxNode("PropertyTemplate");
                pt.AddProperty(templ, FbxPropType.String);
                pt.Children.Add(new FbxNode("Properties70"));
                n.Children.Add(pt);
            }
            else
            {
                var cnt = new FbxNode("Count"); cnt.AddProperty(count, FbxPropType.Int); n.Children.Add(cnt);
            }
            return n;
        }

        private void AssembleFbx(List<ProcessedNode> nodes, FbxNode objects, FbxNode connections)
        {
            long animLayerId = NextId();
            long animStackId = NextId();

            var animLayer = CreateObjectNode("AnimationLayer", animLayerId, "BaseLayer::AnimLayer", "");
            objects.Children.Add(animLayer);

            foreach (var node in nodes)
            {
                string nt = node.NodeType;
                
                // MODELS
                if (nt == "fram" || nt == "joint" || nt == "locator" || nt == "mesh")
                {
                    string modelType = "Null";
                    if (nt == "fram") modelType = node.IsMeshContainer ? "Mesh" : "Null";
                    else if (nt == "joint") modelType = "LimbNode";
                    else if (nt == "mesh") modelType = "Mesh";

                    string modelName = $"{node.Name}::Model";
                    var modelObj = CreateObjectNode("Model", node.Id, modelName, modelType);

                    modelObj.Children.Add(CreatePropNode("Version", 232));
                    var props = new FbxNode("Properties70");
                    AddProp(props, "Lcl Translation", "Lcl Translation", "", "A+", node.T);
                    AddProp(props, "Lcl Rotation", "Lcl Rotation", "", "A+", node.R);
                    AddProp(props, "Lcl Scaling", "Lcl Scaling", "", "A+", node.S);

                    if (nt == "fram")
                    {
                        if (Check(node.RotatePivotTranslate)) AddProp(props, "RotationOffset", "Vector3D", "Vector", "", node.RotatePivotTranslate);
                        if (Check(node.RotatePivot)) AddProp(props, "RotationPivot", "Vector3D", "Vector", "", node.RotatePivot);
                        if (Check(node.ScalePivotTranslate)) AddProp(props, "ScalingOffset", "Vector3D", "Vector", "", node.ScalePivotTranslate);
                        if (Check(node.ScalePivot)) AddProp(props, "ScalingPivot", "Vector3D", "Vector", "", node.ScalePivot);
                        AddProp(props, "RotationActive", "bool", "", "", 1);
                        AddProp(props, "InheritType", "enum", "", "", 1);
                    }
                    else if (nt == "joint")
                    {
                        if (Check(node.JointOrient)) AddProp(props, "PreRotation", "Vector3D", "Vector", "", node.JointOrient);
                        AddProp(props, "RotationActive", "bool", "", "", 1);
                        AddProp(props, "InheritType", "enum", "", "", 1);
                    }

                    modelObj.Children.Add(props);
                    modelObj.Children.Add(CreateStringNode("Shading", "Y"));
                    modelObj.Children.Add(CreateStringNode("Culling", "CullingOff"));

                    objects.Children.Add(modelObj);

                    // Parent
                    Connect(connections, "OO", node.Id, node.ParentId);

                    // GEOMETRY & MATERIALS
                    if (nt == "mesh")
                    {
                        long geomId = NextId();

                        // Materials (Logic from Python: only uses index 0 if multi-mat logic not fully impl in `Geometry`)
                        // Python script loops materials but for FBX `Geometry` uses `Materials: [[0]]`
                        // So we connect all materials but geometry refers to index 0.

                        for (int i = 0; i < node.MaterialsData.Count; i++)
                        {
                            var md = node.MaterialsData[i];
                            long matId = NextId();
                            double trans = 1.0 - md.Opacity;

                            var matObj = CreateObjectNode("Material", matId, $"{md.MatName}::Material", "");
                            matObj.Children.Add(CreatePropNode("Version", 102));
                            matObj.Children.Add(CreateStringNode("ShadingModel", "lambert"));
                            matObj.Children.Add(CreatePropNode("MultiLayer", 0));
                            var matProps = new FbxNode("Properties70");
                            AddProp(matProps, "ShadingModel", "KString", "", "", "Lambert");
                            AddProp(matProps, "MultiLayer", "bool", "", "", 0);
                            AddProp(matProps, "EmissiveColor", "Color", "", "A", 0.0, 0.0, 0.0);
                            AddProp(matProps, "AmbientColor", "Color", "", "A", 0.0, 0.0, 0.0);
                            AddProp(matProps, "DiffuseColor", "Color", "", "A", md.R, md.G, md.B);
                            AddProp(matProps, "TransparencyFactor", "Number", "", "A", trans);
                            AddProp(matProps, "Opacity", "double", "Number", "", md.Opacity);
                            matObj.Children.Add(matProps);
                            objects.Children.Add(matObj);
                            
                            Connect(connections, "OO", matId, node.Id);

                            if (md.HasTex)
                            {

                                long texId = NextId();
                                long vidId = NextId();
                                
                                // md.TexPath у нас вида "Assets/WLD_Export/Textures/png/name_0.png"
                                string unityPath = md.TexPath; 
                                string filenameOnly = Path.GetFileName(unityPath);

                                // ЧИТАЕМ БАЙТЫ КАРТИНКИ С ДИСКА
                                byte[] textureBytes = null;
                                try
                                {
                                    // File.ReadAllBytes отлично понимает пути начинающиеся с "Assets/..." в контексте Unity Editor
                                    if (File.Exists(unityPath))
                                    {
                                        textureBytes = File.ReadAllBytes(unityPath);
                                    }
                                    else
                                    {
                                        Debug.LogWarning($"[NmfToFbx] Texture file not found for embedding: {unityPath}");
                                    }
                                }
                                catch (Exception ex)
                                {
                                    Debug.LogError($"[NmfToFbx] Failed to read texture for embedding: {ex.Message}");
                                }

                                string vidObjName = $"{filenameOnly}::Video";
                                string texObjName = $"{filenameOnly}::Texture";

                                // --- 1. VIDEO OBJECT (С контентом) ---
                                var vidObj = CreateObjectNode("Video", vidId, vidObjName, "Clip");
                                vidObj.Children.Add(CreateStringNode("Type", "Clip"));
                                
                                var vidProps = new FbxNode("Properties70");
                                // Path оставляем для совместимости, но для embeded он не так важен
                                AddProp(vidProps, "Path", "KString", "XRefUrl", "", filenameOnly); 
                                vidObj.Children.Add(vidProps);
                                
                                vidObj.Children.Add(CreatePropNode("UseMipMap", 0));
                                
                                // Для Embedded текстур важно, чтобы Filename был просто именем файла (без путей)
                                vidObj.Children.Add(CreateStringNode("Filename", filenameOnly));
                                vidObj.Children.Add(CreateStringNode("RelativeFilename", filenameOnly));
                                
                                // === ГЛАВНОЕ: ВСТРАИВАЕМ БАЙТЫ ===
                                if (textureBytes != null && textureBytes.Length > 0)
                                {
                                    var contentNode = new FbxNode("Content");
                                    // Используем RawData (тип 'R'), который мы добавили в MiniFbxWriter
                                    contentNode.AddProperty(textureBytes, FbxPropType.Bytes);
                                    vidObj.Children.Add(contentNode);
                                }
                                // =================================
                                
                                objects.Children.Add(vidObj);

                                // --- 2. TEXTURE OBJECT ---
                                var texObj = CreateObjectNode("Texture", texId, texObjName, "TextureVideoClip");
                                texObj.Children.Add(CreateStringNode("Type", "TextureVideoClip"));
                                texObj.Children.Add(CreatePropNode("Version", 202));
                                texObj.Children.Add(CreateStringNode("TextureName", texObjName));
                                
                                var texProps = new FbxNode("Properties70");
                                AddProp(texProps, "CurrentTextureBlendMode", "enum", "", "", 0);
                                AddProp(texProps, "UVSet", "KString", "", "", "map1");
                                AddProp(texProps, "UseMaterial", "bool", "", "", 1);
                                
                                AddProp(texProps, "Translation", "Vector", "", "A", 0.0, 0.0, 0.0);
                                AddProp(texProps, "Rotation", "Vector", "", "A", 0.0, 0.0, md.RotateUV);
                                AddProp(texProps, "Scaling", "Vector", "", "A", md.RepeatU, md.RepeatV, 1.0);
                                
                                texObj.Children.Add(texProps);
                                
                                texObj.Children.Add(CreateStringNode("Media", vidObjName));
                                texObj.Children.Add(CreateStringNode("FileName", filenameOnly)); // Короткое имя
                                texObj.Children.Add(CreateStringNode("RelativeFilename", filenameOnly));

                                texObj.Children.Add(CreatePropNode("ModelUVTranslation", new double[]{0,0}));
                                texObj.Children.Add(CreatePropNode("ModelUVScaling", new double[]{md.RepeatU, md.RepeatV}));
                                texObj.Children.Add(CreateStringNode("Texture_Alpha_Source", "None"));
                                
                                objects.Children.Add(texObj);

                                Connect(connections, "OO", vidId, texId);
                                Connect(connections, "OP", texId, matId, "DiffuseColor");
                            }
                        }

                        // Geometry Object
                        var geomObj = CreateObjectNode("Geometry", geomId, $"{node.Name}::Geometry", "Mesh");
                        geomObj.Children.Add(CreateArrayNode("Vertices", node.Verts.SelectMany(x=>x).ToArray(), 'd'));
                        geomObj.Children.Add(CreateArrayNode("PolygonVertexIndex", node.PVI.ToArray(), 'i'));
                        geomObj.Children.Add(CreateArrayNode("Edges", node.Edges.ToArray(), 'i'));
                        geomObj.Children.Add(CreatePropNode("GeometryVersion", 124));
                        
                        var layerNorm = new FbxNode("LayerElementNormal");
                        layerNorm.AddProperty(0, FbxPropType.Int);
                        layerNorm.Children.Add(CreatePropNode("Version", 102));
                        layerNorm.Children.Add(CreateStringNode("Name", ""));
                        layerNorm.Children.Add(CreateStringNode("MappingInformationType", "ByPolygonVertex"));
                        layerNorm.Children.Add(CreateStringNode("ReferenceInformationType", "Direct"));
                        layerNorm.Children.Add(CreateArrayNode("Normals", node.Normals.ToArray(), 'd'));
                        layerNorm.Children.Add(CreateArrayNode("NormalsW", node.NormalsW.ToArray(), 'd')); // Added
                        geomObj.Children.Add(layerNorm);

                        var layerUV = new FbxNode("LayerElementUV");
                        layerUV.AddProperty(0, FbxPropType.Int);
                        layerUV.Children.Add(CreatePropNode("Version", 101));
                        layerUV.Children.Add(CreateStringNode("Name", "map1"));
                        layerUV.Children.Add(CreateStringNode("MappingInformationType", "ByPolygonVertex"));
                        layerUV.Children.Add(CreateStringNode("ReferenceInformationType", "IndexToDirect"));
                        layerUV.Children.Add(CreateArrayNode("UV", node.UV.ToArray(), 'd'));
                        layerUV.Children.Add(CreateArrayNode("UVIndex", node.UVIndex.ToArray(), 'i'));
                        geomObj.Children.Add(layerUV);

                        var layerMat = new FbxNode("LayerElementMaterial");
                        layerMat.AddProperty(0, FbxPropType.Int);
                        layerMat.Children.Add(CreatePropNode("Version", 101));
                        layerMat.Children.Add(CreateStringNode("Name", ""));
                        layerMat.Children.Add(CreateStringNode("MappingInformationType", "AllSame"));
                        layerMat.Children.Add(CreateStringNode("ReferenceInformationType", "IndexToDirect"));
                        layerMat.Children.Add(CreateArrayNode("Materials", new int[]{0}, 'i'));
                        geomObj.Children.Add(layerMat);

                        var layer0 = new FbxNode("Layer");
                        layer0.AddProperty(0, FbxPropType.Int);
                        layer0.Children.Add(CreatePropNode("Version", 100));
                        AddLayerElement(layer0, "LayerElementNormal", 0);
                        AddLayerElement(layer0, "LayerElementMaterial", 0);
                        AddLayerElement(layer0, "LayerElementUV", 0);
                        geomObj.Children.Add(layer0);

                        objects.Children.Add(geomObj);
                        Connect(connections, "OO", geomId, node.Id);
                    }

                    // Animations
                    if (node.WithAnimation)
                    {
                        CreateFbxAnimationData(node, node.Id, animLayerId, objects, connections);
                    }
                }
            }

            // Global Anim Stacks
            objects.Children.Add(animLayer);
            var stack = CreateObjectNode("AnimationStack", animStackId, "Take 001::AnimStack", "");
            var stackProps = new FbxNode("Properties70");
            AddProp(stackProps, "LocalStart", "KTime", "Time", "", 0L);
            AddProp(stackProps, "LocalStop", "KTime", "Time", "", (long)(100 * KTIME_PER_FRAME));
            stack.Children.Add(stackProps);
            objects.Children.Add(stack);
            
            Connect(connections, "OO", animLayerId, animStackId);
        }

        private void AddLayerElement(FbxNode layer, string type, int idx)
        {
            var el = new FbxNode("LayerElement");
            el.Children.Add(CreateStringNode("Type", type));
            el.Children.Add(CreatePropNode("TypedIndex", idx));
            layer.Children.Add(el);
        }

        private void CreateFbxAnimationData(ProcessedNode node, long modelId, long layerId, FbxNode objects, FbxNode connections)
        {
            string[] axes = { "x", "y", "z" };
            string[] axisLabels = { "d|X", "d|Y", "d|Z" };
            
            // Defines
            var map = new Dictionary<string, (string prop, string prefix, double[] def)> {
                {"translation", ("Lcl Translation", "T", new double[]{0,0,0})},
                {"rotation", ("Lcl Rotation", "R", new double[]{0,0,0})},
                {"scaling", ("Lcl Scaling", "S", new double[]{1,1,1})}
            };

            foreach (var kvp in map)
            {
                string track = kvp.Key;
                var spec = kvp.Value;
                if (!node.Animations.ContainsKey(track)) continue;
                var trackData = node.Animations[track];

                bool hasKeys = false;
                foreach(var ax in axes) if(trackData.ContainsKey(ax) && trackData[ax].Frames.Count > 0) hasKeys = true;
                if (!hasKeys) continue;

                long curveNodeId = GenerateRndId();
                string curveNodeName = $"{spec.prefix}::AnimCurveNode";
                var curveNode = CreateObjectNode("AnimationCurveNode", curveNodeId, curveNodeName, "");
                var props = new FbxNode("Properties70");
                for(int i=0; i<3; i++) AddProp(props, axisLabels[i], "Number", "", "A", spec.def[i]);
                curveNode.Children.Add(props);
                objects.Children.Add(curveNode);

                Connect(connections, "OP", curveNodeId, modelId, spec.prop);
                Connect(connections, "OO", curveNodeId, layerId);

                for(int i=0; i<3; i++)
                {
                    string ax = axes[i];
                    if (!trackData.ContainsKey(ax)) continue;
                    var axData = trackData[ax];
                    if (axData.Frames.Count == 0) continue;

                    long curveId = GenerateRndId();
                    int nKeys = axData.Frames.Count;
                    long[] times = axData.Frames.Select(f => (long)(f * KTIME_PER_FRAME)).ToArray();
                    float[] vals = axData.Values.ToArray();
                    int[] flags = Enumerable.Repeat(8456, nKeys).ToArray();
                    int[] refs = Enumerable.Repeat(1, nKeys).ToArray();

                    var curve = CreateObjectNode("AnimationCurve", curveId, "::AnimCurve", "");
                    curve.Children.Add(CreatePropNode("Default", 0.0));
                    curve.Children.Add(CreatePropNode("KeyVer", 4009));
                    curve.Children.Add(CreateArrayNode("KeyTime", times, 'l'));
                    curve.Children.Add(CreateArrayNode("KeyValueFloat", vals, 'f'));
                    curve.Children.Add(CreateArrayNode("KeyAttrFlags", flags, 'i'));
                    curve.Children.Add(CreateArrayNode("KeyAttrRefCount", refs, 'i')); // Added
                    
                    objects.Children.Add(curve);
                    Connect(connections, "OP", curveId, curveNodeId, axisLabels[i]);
                }
            }
        }

        // -----------------------------------------------------------------------------
        // NODE HELPERS
        // -----------------------------------------------------------------------------
        private FbxNode CreateObjectNode(string type, long id, string name, string sub)
        {
            var n = new FbxNode(type);
            n.AddProperty(id, FbxPropType.Long);
            n.AddProperty(name + "\0\x01" + sub, FbxPropType.String);
            n.AddProperty(sub, FbxPropType.String);
            return n;
        }

        private FbxNode CreatePropNode<T>(string name, T val)
        {
            var n = new FbxNode(name);
            if (val is int i) n.AddProperty(i, FbxPropType.Int);
            else if (val is long l) n.AddProperty(l, FbxPropType.Long);
            else if (val is float f) n.AddProperty(f, FbxPropType.Float);
            else if (val is double d) n.AddProperty(d, FbxPropType.Double);
            else if (val is double[] arr) { n.AddProperty(arr[0], FbxPropType.Double); n.AddProperty(arr[1], FbxPropType.Double); } // special case for UV props
            return n;
        }

        private FbxNode CreateStringNode(string name, string val)
        {
            var n = new FbxNode(name); n.AddProperty(val, FbxPropType.String); return n;
        }

        private FbxNode CreateArrayNode(string name, Array data, char type)
        {
            var n = new FbxNode(name);
            if (type == 'd') n.AddProperty(data, FbxPropType.DoubleArray);
            if (type == 'i') n.AddProperty(data, FbxPropType.IntArray);
            if (type == 'l') n.AddProperty(data, FbxPropType.LongArray);
            if (type == 'f') n.AddProperty(data, FbxPropType.FloatArray);
            return n;
        }

        private void Connect(FbxNode conns, string type, long child, long parent, string prop = null)
        {
            var c = new FbxNode("C");
            c.AddProperty(type, FbxPropType.String);
            c.AddProperty(child, FbxPropType.Long);
            c.AddProperty(parent, FbxPropType.Long);
            if (prop != null) c.AddProperty(prop, FbxPropType.String);
            conns.Children.Add(c);
        }

        private void AddProp(FbxNode props, string n, string t1, string t2, string t3, params object[] vals)
        {
            var p = new FbxNode("P");
            p.AddProperty(n, FbxPropType.String);
            p.AddProperty(t1, FbxPropType.String);
            p.AddProperty(t2, FbxPropType.String);
            p.AddProperty(t3, FbxPropType.String);
            foreach(var v in vals)
            {
                if(v is int i) p.AddProperty(i, FbxPropType.Int);
                else if(v is double d) p.AddProperty(d, FbxPropType.Double);
                else if(v is long l) p.AddProperty(l, FbxPropType.Long);
                else if(v is string s) p.AddProperty(s, FbxPropType.String);
                else if(v is double[] arr) { p.AddProperty(arr[0], FbxPropType.Double); p.AddProperty(arr[1], FbxPropType.Double); p.AddProperty(arr[2], FbxPropType.Double); }
            }
            props.Children.Add(p);
        }

        private double[] ToDouble3(float[] f)
        {
            if (f == null || f.Length < 3) return new double[] { 0, 0, 0 };
            return new double[] { f[0], f[1], f[2] };
        }
        
        private bool Check(double[] v) => v != null && (Math.Abs(v[0]) > 1e-6 || Math.Abs(v[1]) > 1e-6 || Math.Abs(v[2]) > 1e-6);
    }
}