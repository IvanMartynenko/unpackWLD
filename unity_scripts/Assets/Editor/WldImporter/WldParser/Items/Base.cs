using System;
using System.Collections.Generic;

namespace WldParser.Items
{
    public class TokenError : Exception
    {
        public string ErrorMessage { get; }

        public TokenError(string token, string expectedMarker)
            : base(
                $"Unexpected token encountered in the game file. " +
                $"Received '{token}', but expected '{expectedMarker}'. " +
                "Please check the file's format and token sequence for any discrepancies.")
        {
            ErrorMessage = Message;
        }
    }

    public abstract class WldSectionBase<TNode>
    {
        protected readonly string Marker;
        protected readonly string Separator;
        protected readonly List<TNode> _nodes = new List<TNode>();

        public IReadOnlyList<TNode> Nodes => _nodes;

        protected WldSectionBase(WldParser.Helpers.BinaryFileReader file, string marker, string separator)
        {
            Marker = marker;
            Separator = separator;
            Unpack(file);
        }

        protected void Unpack(WldParser.Helpers.BinaryFileReader file)
        {
            // 1) основной маркер секции (WRLD уже проверен снаружи)
            string token = file.Token();
            if (token != Marker)
                RaiseToken(token, Marker);

            // 2) первый entry: token + big-endian size
            (string entryToken, uint entrySize) = file.TokenWithSize();

            if (entryToken == "END ")
                return;

            int index = 0;

            // 3) читаем все ноды пока token == Separator
            while (entryToken == Separator)
            {
                _nodes.Add(UnpackNode(file, index, (int)entrySize));
                index++;

                (entryToken, entrySize) = file.TokenWithSize();
            }

            if (entryToken != "END ")
                RaiseToken(entryToken, "END ");
        }

        protected abstract TNode UnpackNode(WldParser.Helpers.BinaryFileReader file, int index, int entrySize);

        protected void RaiseToken(string token, string expectedMarker)
        {
            throw new TokenError(token, expectedMarker);
        }
    }
}
