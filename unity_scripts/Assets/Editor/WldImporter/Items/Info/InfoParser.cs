using WldParser.Helpers;

namespace WldParser.Items.Info
{
    public class InfoParser
    {
        private readonly BinaryFileReader _file;

        public InfoParser(BinaryFileReader file)
        {
            _file = file;
        }

        public InfoData Parse()
        {
            (string token, uint size) = _file.TokenWithSize();
            if (token != "INFO") throw new TokenError(token, "INFO");

            var info = new InfoData();
            info.unknown1 = _file.Int();
            info.unknown2 = _file.Int();
            info.unknown3 = _file.Int();

            // OPTS
            info.opts = new OptsParser(_file).Parse();

            // DIALOG
            info.dialog = new DialogParser(_file).Parse();

            // Custom Opts Logic based on Type (из Ruby Info::unpack)
            switch (info.opts.type)
            {
                case 7:
                case 8:
                    info.opts.custom_open = _file.Int();
                    info.opts.custom_locked = _file.Int();
                    break;
                case 3:
                    info.opts.custom_open = _file.Int();
                    info.opts.custom_locked = _file.Int();
                    info.opts.custom_active = _file.Int();
                    break;
                case 4:
                    info.opts.custom_open = _file.Int();
                    info.opts.custom_locked = _file.Int();
                    info.opts.custom_values = _file.Floats(8);
                    break;
            }

            // TASK LIST
            info.task_list = new TaskListParser(_file).Parse();

            string endToken = _file.Token();
            if (endToken != "END ") throw new TokenError(endToken, "END ");

            return info;
        }
    }
}