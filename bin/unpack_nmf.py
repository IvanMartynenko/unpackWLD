import struct
import sys
from pprint import pprint

MATRIX_SIZE = 16

def read_aligned_string(f):
    # читаем байты по одному, пока не встретим \x00
    bytes_list = []
    while True:
        b = f.read(1)
        if not b:
            break  # конец файла
        if b == b'\x00':
            break
        bytes_list.append(b)

    # собираем строку
    raw = b''.join(bytes_list)
    name = raw.decode('windows-1252', errors='ignore')

    # вычисляем длину с нулём
    total_len = len(raw) + 1

    # считаем выравнивание до 4 байт
    padding = (4 - (total_len % 4)) % 4
    if padding:
        f.read(padding)

    return name

class Nmf:
    def unpack(self, path):
        model = []
        index = 1

        with open(path, "rb") as f:
            # ---- Заголовок (token 'NMF ')
            token = f.read(4).decode("ascii", errors="ignore")
            if token != "NMF ":
                raise RuntimeError(f"Bad start of ModelList. Expected 'NMF ' but got '{token}'")
            f.read(4) # пропуск int32 == 0

            # Основной цикл по блокам до 'END '
            while True:
                token_bytes = f.read(4)
                if len(token_bytes) == 0:
                    # неожиданное завершение файла
                    raise EOFError("Unexpected end of file while reading token")
                token = token_bytes.decode("ascii", errors="ignore")

                # размер (int BE), но используется только для пропуска/отладки
                _size = struct.unpack(">I", f.read(4))[0]

                if token == "END ":
                    break

                # метаданные узла
                _skip = struct.unpack("<i", f.read(4))[0]  # 0 для LOCA, 2 для FRAM, JOIN, ROOT, 14 для MESH
                parent_id = struct.unpack("<i", f.read(4))[0]

                name = read_aligned_string(f)

                # Разбор по типу токена
                if token == "ROOT":
                    data = self._parse_fram(f)
                elif token == "LOCA":
                    data = {}  # в исходнике пусто
                elif token == "FRAM":
                    data = self._parse_fram(f)
                elif token == "JOIN":
                    data = self._parse_join(f)
                elif token == "MESH":
                    data = self._parse_mesh(f)
                else:
                    raise RuntimeError(f"Unexpected token in MODEL: {token}")

                model.append(
                    {"word": token, "name": name, "parent_id": parent_id, "data": data, "index": index}
                )
                index += 1

        return model

    # -------------------- парсеры секций --------------------

    def _parse_fram(self, f):
        res = {}

        # matrix (4x4)
        vals = list(struct.unpack(f"<{MATRIX_SIZE}f", f.read(4 * MATRIX_SIZE)))
        res["matrix"] = [vals[i : i + 4] for i in range(0, MATRIX_SIZE, 4)]

        # векторные поля по 3 float
        for key in [
            "translation",
            "scaling",
            "rotation",
            "rotate_pivot_translate",
            "rotate_pivot",
            "scale_pivot_translate",
            "scale_pivot",
            "shear",
        ]:
            res[key] = list(struct.unpack("<3f", f.read(12)))

        # возможный блок ANIM
        peek = f.read(4)
        if len(peek) != 4:
            return res
        word = peek.decode("ascii", errors="ignore")
        if word == "ANIM":
            res["anim"] = self._parse_anim(f)
        return res

    def _parse_join(self, f):
        res = {}

        # matrix (4x4)
        vals = list(struct.unpack(f"<{MATRIX_SIZE}f", f.read(4 * MATRIX_SIZE)))
        res["matrix"] = [vals[i : i + 4] for i in range(0, MATRIX_SIZE, 4)]

        for key in ["translation", "scaling", "rotation"]:
            res[key] = list(struct.unpack("<3f", f.read(12)))

        # rotation_matrix (4x4)
        vals = list(struct.unpack(f"<{MATRIX_SIZE}f", f.read(4 * MATRIX_SIZE)))
        res["rotation_matrix"] = [vals[i : i + 4] for i in range(0, MATRIX_SIZE, 4)]

        res["min_rot_limit"] = list(struct.unpack("<3f", f.read(12)))
        res["max_rot_limit"] = list(struct.unpack("<3f", f.read(12)))

        # возможный блок ANIM
        peek = f.read(4)
        if len(peek) != 4:
            return res
        word = peek.decode("ascii", errors="ignore")
        if word == "ANIM":
            res["anim"] = self._parse_anim(f)
        else:
            # ничего не делаем
            pass
        return res

    def _parse_anim(self, f):
        res = {}
        sizes = {}

        res["unknown"] = struct.unpack("<i", f.read(4))[0]

        keys = ["translation", "rotation", "scaling"]
        for key in keys:
            res[key] = {}
            sizes[key] = {}

        # для каждого ключа три размера по осям x,y,z
        for key in keys:
            sizes[key]["sizes"] = list(struct.unpack("<3i", f.read(12)))

        # значения/ключи кривых
        for key in keys:
            axis_sizes = sizes[key]["sizes"]
            cur = {"values": {}, "keys": {}}

            # x
            n = axis_sizes[0]
            if n > 0:
                cur["keys"]["x"] = list(struct.unpack(f"<{n}f", f.read(4 * n)))
                cur["values"]["x"] = list(struct.unpack(f"<{n}f", f.read(4 * n)))

            # y
            n = axis_sizes[1]
            if n > 0:
                cur["keys"]["y"] = list(struct.unpack(f"<{n}f", f.read(4 * n)))
                cur["values"]["y"] = list(struct.unpack(f"<{n}f", f.read(4 * n)))

            # z
            n = axis_sizes[2]
            if n > 0:
                cur["keys"]["z"] = list(struct.unpack(f"<{n}f", f.read(4 * n)))
                cur["values"]["z"] = list(struct.unpack(f"<{n}f", f.read(4 * n)))

            res[key] = cur

        return res

    def _parse_mesh(self, f):
        res = {}

        res["tnum"] = struct.unpack("<i", f.read(4))[0]
        res["vnum"] = struct.unpack("<i", f.read(4))[0]

        vbuf_count = 10
        uvbuf_count = 2
        vbuf_count_float = res["vnum"] * vbuf_count
        uvbuf_count_float = res["vnum"] * uvbuf_count

        vbuf_flat = list(struct.unpack(f"<{vbuf_count_float}f", f.read(4 * vbuf_count_float)))
        res["vbuf"] = [vbuf_flat[i : i + vbuf_count] for i in range(0, len(vbuf_flat), vbuf_count)]

        uv_flat = list(struct.unpack(f"<{uvbuf_count_float}f", f.read(4 * uvbuf_count_float)))
        res["uvpt"] = [uv_flat[i : i + uvbuf_count] for i in range(0, len(uv_flat), uvbuf_count)]

        res["inum"] = struct.unpack("<i", f.read(4))[0]
        ibuf_flat = list(struct.unpack(f"<{res['inum']}h", f.read(2 * res["inum"])))
        res["ibuf"] = [ibuf_flat[i : i + 3] for i in range(0, len(ibuf_flat), 3)]

        if res["inum"] % 2 == 1:
            _pad = struct.unpack("<h", f.read(2))[0]

        res["backface_culling"] = struct.unpack("<i", f.read(4))[0]
        res["complex"] = struct.unpack("<i", f.read(4))[0]
        res["inside"] = struct.unpack("<i", f.read(4))[0]
        res["smooth"] = struct.unpack("<i", f.read(4))[0]
        res["light_flare"] = struct.unpack("<i", f.read(4))[0]

        material_count = struct.unpack("<i", f.read(4))[0]
        if material_count > 0:
            res["materials"] = []
            for _ in range(material_count):
                res["materials"].append(self._parse_mtrl(f))

        # возможный блок ANIM для меша
        peek = f.read(4)
        if len(peek) == 4 and peek.decode("ascii", errors="ignore") == "ANIM":
            res["mesh_anim"] = self._parse_anim_mesh(f)
        else:
            # ничего не делаем
            pass

        # anti-ground
        raw = f.read(4)
        unknown_count_of_floats = struct.unpack("<i", raw)[0]

        if unknown_count_of_floats > 0:
            cnt = unknown_count_of_floats * 3
            res["unknown_floats"] = list(struct.unpack(f"<{cnt}f", f.read(4 * cnt)))
        
        # индексы стрипов/сабмешей?
        unknown_count_of_ints = struct.unpack("<i", f.read(4))[0]
        if unknown_count_of_ints > 0:
            res["unknown_ints"] = list(struct.unpack(f"<{unknown_count_of_ints}i", f.read(4 * unknown_count_of_ints)))

        return res

    def _parse_mtrl(self, f):
        res = {}

        token = f.read(4).decode("ascii", errors="ignore")
        if token != "MTRL":
            raise RuntimeError(f"Expected 'MTRL' but got '{token}'")

        name = read_aligned_string(f)

        res["name"] = name
        res["blend_mode"] = struct.unpack("<i", f.read(4))[0]
        res["unknown_ints"] = list(struct.unpack("<4i", f.read(16)))
        res["uv_mapping_flip_horizontal"] = struct.unpack("<i", f.read(4))[0]
        res["uv_mapping_flip_vertical"] = struct.unpack("<i", f.read(4))[0]
        res["rotate"] = struct.unpack("<i", f.read(4))[0]
        res["horizontal_stretch"] = struct.unpack("<f", f.read(4))[0]
        res["vertical_stretch"] = struct.unpack("<f", f.read(4))[0]
        res["red"] = struct.unpack("<f", f.read(4))[0]
        res["green"] = struct.unpack("<f", f.read(4))[0]
        res["blue"] = struct.unpack("<f", f.read(4))[0]
        res["alpha"] = struct.unpack("<f", f.read(4))[0]
        res["red2"] = struct.unpack("<f", f.read(4))[0]
        res["green2"] = struct.unpack("<f", f.read(4))[0]
        res["blue2"] = struct.unpack("<f", f.read(4))[0]
        res["alpha2"] = struct.unpack("<f", f.read(4))[0]
        res["unknown_zero_ints"] = list(struct.unpack("<9i", f.read(36)))

        next_token_bytes = f.read(4)
        if len(next_token_bytes) == 4:
            next_token = next_token_bytes.decode("ascii", errors="ignore")
            if next_token == "TXPG":
                # filename 
                name = read_aligned_string(f)
                res["texture"] = {
                    "name": name,
                    "texture_page": struct.unpack("<i", f.read(4))[0],
                    "index_texture_on_page": struct.unpack("<i", f.read(4))[0],
                    "x0": struct.unpack("<i", f.read(4))[0],
                    "y0": struct.unpack("<i", f.read(4))[0],
                    "x2": struct.unpack("<i", f.read(4))[0],
                    "y2": struct.unpack("<i", f.read(4))[0],
                }
            elif next_token == "TEXT":
                name = read_aligned_string(f)
                res["text"] = {"name": name}
            else:
                # ничего не делаем
                pass
        return res

    def _parse_anim_mesh(self, f):
        anim_meshes = []
        anim_meshes.append(self._parse_single_anim_mesh(f))

        # цикл, пока следующий токен снова 'ANIM'
        while True:
            peek = f.read(4)
            if len(peek) != 4:
                break
            word = peek.decode("ascii", errors="ignore")
            if word == "ANIM":
                anim_meshes.append(self._parse_single_anim_mesh(f))
            else:
                # остановка, назад не нужно возвращаться
                break

        # flatten, хотя тут и так словари
        return anim_meshes

    def _parse_single_anim_mesh(self, f):
        unknown_bool = struct.unpack("<i", f.read(4))[0]
        size = struct.unpack("<i", f.read(4))[0]
        unknown_ints = list(struct.unpack(f"<{size}i", f.read(4 * size)))
        unknown_floats = list(struct.unpack("<3f", f.read(12)))
        s1 = struct.unpack("<i", f.read(4))[0]
        s2 = struct.unpack("<i", f.read(4))[0]
        s3 = struct.unpack("<i", f.read(4))[0]
        unknown_floats1 = list(struct.unpack(f"<{s1*2}f", f.read(4 * (s1 * 2))))
        unknown_floats2 = list(struct.unpack(f"<{s2*2}f", f.read(4 * (s2 * 2))))
        unknown_floats3 = list(struct.unpack(f"<{s3*2}f", f.read(4 * (s3 * 2))))

        return {
            "unknown_bool": unknown_bool,
            "unknown_size_of_ints": size,
            "unknown_ints": unknown_ints,
            "unknown_floats": unknown_floats,
            "unknown_size1": s1,
            "unknown_size2": s2,
            "unknown_size3": s3,
            "unknown_floats1": unknown_floats1,
            "unknown_floats2": unknown_floats2,
            "unknown_floats3": unknown_floats3,
        }


def main():
    if len(sys.argv) < 2:
        print("Usage: python nmf_parser.py <path_to_nmf_file>")
        sys.exit(1)

    path = sys.argv[1]
    try:
        parser = Nmf()
        result = parser.unpack(path)
        print("Parsed NMF structure successfully:")
        pprint(result, width=120)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
