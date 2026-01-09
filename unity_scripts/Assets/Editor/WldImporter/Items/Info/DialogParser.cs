using WldParser.Helpers;

namespace WldParser.Items.Info
{
    public class DialogParser
    {
        private readonly BinaryFileReader _file;
        public DialogParser(BinaryFileReader file) => _file = file;

        public DialogData Parse()
        {
            (string token, uint size) = _file.TokenWithSize();
            if (token != "COND") throw new TokenError(token, "COND");

            _file.Skip(); // skip 6 values (int type)
            
            var data = new DialogData();

            if (size == 4) return data;

            if (size == 8)
            {
                data.bad_size = true;
                data.unknown_value = _file.Int();
                return data;
            }

            int count = _file.Int();
            for (int i = 0; i < count; i++)
            {
                var item = new DialogItem();
                item.active = _file.Int();
                item.Q = _file.Name();
                item.A = _file.Name();
                item.DlgMinus = _file.Name();
                item.DlgPlus = _file.Name();
                item.AlwaysMinus = _file.Name();
                item.AlwaysPlus = _file.Name();
                item.Always = _file.Int();
                item.Story = _file.Int();
                item.Coohess = _file.Int();
                item.DialogEvent = _file.Int();
                data.items.Add(item);
            }
            return data;
        }
    }
}