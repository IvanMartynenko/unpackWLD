namespace WldParser.Items
{
    public class Empty : WldSectionBase<object>
    {
        public Empty(WldParser.Helpers.BinaryFileReader f, string m, string m2) : base(f, m, m2)
        {
        }

        protected override object UnpackNode(WldParser.Helpers.BinaryFileReader file, int index, int entrySize)
        {
            // Просто пропускаем всю ноду:
            file.Next(entrySize);
            return null;
        }
    }
}
