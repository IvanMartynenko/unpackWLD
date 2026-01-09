using System;
using System.IO;
using System.Text;

namespace WldParser.Helpers
{
    public class BinaryFileReader
    {
        private readonly byte[] _buffer;
        private int _offset;
        private readonly Encoding _encoding1252;

        public BinaryFileReader(string filepath)
        {
            if (!File.Exists(filepath))
                throw new FileNotFoundException("Can not open file", filepath);

            _buffer = File.ReadAllBytes(filepath);
            _offset = 0;

            _encoding1252 = Encoding.GetEncoding(1252);
        }

        public int Current => _offset;
        public bool Eof => _offset >= _buffer.Length;

        public void SetPosition(int offset)
        {
            if (offset < 0 || offset > _buffer.Length)
                throw new ArgumentOutOfRangeException(nameof(offset));
            _offset = offset;
        }

        public string Name()
        {
            int start = _offset;
            int end = start;

            while (end < _buffer.Length && _buffer[end] != 0)
                end++;

            if (end >= _buffer.Length)
                throw new Exception("Null terminator not found");

            int length = end - start;
            var nameBytes = new byte[length];
            Buffer.BlockCopy(_buffer, start, nameBytes, 0, length);

            _offset = end + 1;

            int remainder = _offset % 4;
            if (remainder != 0)
                _offset += (4 - remainder);

            return _encoding1252.GetString(nameBytes);
        }

        public string Filename() => Name();

        public string Word()
        {
            byte[] bytes = ReadRawBytes(4);
            return Encoding.ASCII.GetString(bytes);
        }

        public float[] Floats(int count)
        {
            float[] result = new float[count];
            for (int i = 0; i < count; i++)
                result[i] = Float();
            return result;
        }

        public int[] Ints(int count)
        {
            int[] result = new int[count];
            for (int i = 0; i < count; i++)
                result[i] = Int();
            return result;
        }

        public ushort[] Ints16(int count)
        {
            ushort[] result = new ushort[count];
            for (int i = 0; i < count; i++)
                result[i] = Int16();
            return result;
        }

        public uint[] BigEndianInts(int count)
        {
            uint[] result = new uint[count];
            for (int i = 0; i < count; i++)
                result[i] = BigEndianInt();
            return result;
        }

        public string Hex(int size)
        {
            byte[] bytes = ReadRawBytes(size);
            return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant();
        }

        public byte[] Raw(int size)
        {
            return ReadRawBytes(size);
        }

        public float Float()
        {
            byte[] bytes = ReadRawBytes(4);
            if (!BitConverter.IsLittleEndian)
                Array.Reverse(bytes);
            return BitConverter.ToSingle(bytes, 0);
        }

        public int Int()
        {
            byte[] bytes = ReadRawBytes(4);
            if (!BitConverter.IsLittleEndian)
                Array.Reverse(bytes);
            return BitConverter.ToInt32(bytes, 0);
        }

        public ushort Int16()
        {
            byte[] bytes = ReadRawBytes(2);
            if (!BitConverter.IsLittleEndian)
                Array.Reverse(bytes);
            return BitConverter.ToUInt16(bytes, 0);
        }

        public uint BigEndianInt()
        {
            byte[] bytes = ReadRawBytes(4);
            if (BitConverter.IsLittleEndian)
                Array.Reverse(bytes);
            return BitConverter.ToUInt32(bytes, 0);
        }

        public bool Bool()
        {
            return !(Int() == 0);
        }

        public string Token()
        {
            string val = Word();
            Skip();
            return val;
        }

        public (string token, uint size) TokenWithSize()
        {
            string t = Word();
            uint s = BigEndianInt();
            return (t, s);
        }

        public void Skip()
        {
            _offset += 4;
        }

        public void Back()
        {
            _offset -= 4;
            if (_offset < 0) _offset = 0;
        }

        public void Next(int size)
        {
            _offset += size;
            if (_offset < 0) _offset = 0;
            if (_offset > _buffer.Length) _offset = _buffer.Length;
        }

        public int CurrentSize()
        {
            return (_buffer.Length - _offset) / 4;
        }

        private byte[] ReadRawBytes(int size)
        {
            if (_offset + size > _buffer.Length)
                throw new EndOfStreamException("Unexpected EOF");

            var result = new byte[size];
            Buffer.BlockCopy(_buffer, _offset, result, 0, size);
            _offset += size;
            return result;
        }
    }
}