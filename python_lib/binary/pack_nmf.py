import sys
from typing import Any, Dict, List, Iterable, Union
import struct

class NMFWriter:
    """
    Сборщик бинарного NMF в стиле вашего Ruby-кода, но на Python и как класс.

    Публичный метод:
      - pack(model_file: List[Dict[str, Any]]) -> bytes

    Формат:
      - word (маркер) — 4 ASCII байта
      - size          — 32-бит BE (big-endian, >I)
      - int           — 32-бит LE (little-endian, <i)
      - float         — 32-бит LE (little-endian, <f)
      - int16         — 16-бит LE (little-endian, <h)
      - name          — Windows-1252 + '\\0' + паддинг до кратности 4
    """

    # ---------- Публичный API ----------
    def pack(self, model_file: List[Dict[str, Any]]) -> bytes:
        self._buf = bytearray()

        # Заголовок контейнера
        self._push_word('NMF ')
        self._push_int(0)

        # Тело — элементы в порядке index
        for value in sorted(model_file, key=lambda t: t['index']):
            word = value['word']
            inner = bytearray()  # локальный буфер для содержимого чанка

            d = value.get('data') or {}

            if word == 'LOCA':
                self._i_push_int(inner, 0)
                self._i_push_int(inner, value['parent_id'])
                self._i_push_name(inner, value['name'])

            elif word in ('FRAM', 'ROOT'):
                self._i_push_int(inner, 2)
                self._i_push_int(inner, value['parent_id'])
                self._i_push_name(inner, value['name'])
                self._i_push_floats(inner, self._flatten(d['matrix']))

                for k in (
                    'translation', 'scaling', 'rotation',
                    'rotate_pivot_translate', 'rotate_pivot',
                    'scale_pivot_translate', 'scale_pivot',
                    'shear'
                ):
                    self._i_push_floats(inner, d[k])

                if d.get('anim'):
                    self._pack_anim_into(inner, d['anim'])
                else:
                    self._i_push_int(inner, 0)

            elif word == 'JOIN':
                self._i_push_int(inner, 2)
                self._i_push_int(inner, value['parent_id'])
                self._i_push_name(inner, value['name'])
                self._i_push_floats(inner, self._flatten(d['matrix']))

                for k in ('translation', 'scaling', 'rotation'):
                    self._i_push_floats(inner, d[k])

                self._i_push_floats(inner, self._flatten(d['rotation_matrix']))
                self._i_push_floats(inner, d['min_rot_limit'])
                self._i_push_floats(inner, d['max_rot_limit'])

                if d.get('anim'):
                    self._pack_anim_into(inner, d['anim'])
                else:
                    self._i_push_int(inner, 0)

            elif word == 'MESH':
                self._i_push_int(inner, 14)
                self._i_push_int(inner, value['parent_id'])
                self._i_push_name(inner, value['name'])

                self._i_push_int(inner, d['tnum'])
                self._i_push_int(inner, d['vnum'])
                self._i_push_floats(inner, self._flatten(d['vbuf']))
                self._i_push_floats(inner, self._flatten(d['uvpt']))
                self._i_push_int(inner, d['inum'])
                self._i_push_ints16(inner, self._flatten(d['ibuf']))
                if d['inum'] % 2 == 1:
                    self._i_push_int16(inner, 0)

                self._i_push_int(inner, d['backface_culling'])
                self._i_push_int(inner, d['complex'])
                self._i_push_int(inner, d['inside'])
                self._i_push_int(inner, d['smooth'])
                self._i_push_int(inner, d['light_flare'])

                mats = d.get('materials')
                if mats:
                    self._i_push_int(inner, len(mats))
                    for mt in mats:
                        self._i_push_word(inner, 'MTRL')
                        self._i_push_name(inner, mt['name'])
                        self._i_push_int(inner, mt['blend_mode'])
                        self._i_push_ints(inner, mt['unknown_ints'])
                        self._i_push_int(inner, mt['uv_mapping_flip_horizontal'])
                        self._i_push_int(inner, mt['uv_mapping_flip_vertical'])
                        self._i_push_int(inner, mt['rotate'])
                        self._i_push_float(inner, mt['horizontal_stretch'])
                        self._i_push_float(inner, mt['vertical_stretch'])
                        self._i_push_float(inner, mt['red'])
                        self._i_push_float(inner, mt['green'])
                        self._i_push_float(inner, mt['blue'])
                        self._i_push_float(inner, mt['alpha'])
                        self._i_push_float(inner, mt['red2'])
                        self._i_push_float(inner, mt['green2'])
                        self._i_push_float(inner, mt['blue2'])
                        self._i_push_float(inner, mt['alpha2'])
                        self._i_push_ints(inner, mt['unknown_zero_ints'])

                        tex = mt.get('texture')
                        txt = mt.get('text')
                        if tex:
                            self._i_push_word(inner, 'TXPG')
                            self._i_push_name(inner, tex['name'])
                            self._i_push_int(inner, tex['texture_page'])
                            self._i_push_int(inner, tex['index_texture_on_page'])
                            self._i_push_int(inner, tex['x0'])
                            self._i_push_int(inner, tex['y0'])
                            self._i_push_int(inner, tex['x2'])
                            self._i_push_int(inner, tex['y2'])
                        elif txt:
                            self._i_push_word(inner, 'TEXT')
                            self._i_push_name(inner, txt['name'])
                        else:
                            self._i_push_int(inner, 0)
                else:
                    self._i_push_int(inner, 0)

                # mesh_anim
                mesh_anim = d.get('mesh_anim') or []
                if mesh_anim:
                    for anim in mesh_anim:
                        self._i_push_word(inner, 'ANIM')
                        self._i_push_int(inner, anim['unknown_bool'])
                        self._i_push_int(inner, len(anim['unknown_ints']))
                        self._i_push_ints(inner, anim['unknown_ints'])
                        self._i_push_floats(inner, anim['unknown_floats'])
                        self._i_push_int(inner, anim['unknown_size1'])
                        self._i_push_int(inner, anim['unknown_size2'])
                        self._i_push_int(inner, anim['unknown_size3'])
                        self._i_push_floats(inner, anim['unknown_floats1'])
                        self._i_push_floats(inner, anim['unknown_floats2'])
                        self._i_push_floats(inner, anim['unknown_floats3'])
                self._i_push_int(inner, 0)  # терминатор блока mesh_anim

                # unknown_floats / unknown_ints
                if d.get('unknown_floats'):
                    self._i_push_int(inner, len(d['unknown_floats']) // 3)
                    self._i_push_floats(inner, d['unknown_floats'])
                else:
                    self._i_push_int(inner, 0)

                if d.get('unknown_ints'):
                    self._i_push_int(inner, len(d['unknown_ints']))
                    self._i_push_ints(inner, d['unknown_ints'])
                else:
                    self._i_push_int(inner, 0)

            else:
                raise ValueError(f"Unsupported word type: {word}")

            # записываем заголовок чанка + размер (BE) + содержимое
            self._push_word(word)
            self._push_size(len(inner))
            self._buf.extend(inner)

        # Хвостовой END 0
        self._push_word('END ')
        self._push_int(0)

        return bytes(self._buf)

    # ---------- Приватные helpers: запись в главный буфер ----------
    def _push_word(self, w: str) -> None:
        if len(w) != 4:
            raise ValueError(f"word must be 4 chars, got {w!r}")
        self._buf.extend(w.encode('ascii'))

    def _push_int(self, v: int) -> None:
        self._buf.extend(struct.pack('<i', int(v)))

    def _push_size(self, n: int) -> None:
        # big-endian размер как в Ruby .pack('N')
        self._buf.extend(struct.pack('>I', int(n)))

    def _push_float(self, x: Union[float, str]) -> None:
        if isinstance(x, str):
            raw = bytes.fromhex(x)
            if len(raw) != 4:
                raise ValueError("hex float must be exactly 4 bytes")
            self._buf.extend(raw)
        else:
            self._buf.extend(struct.pack('<f', float(x)))

    def _push_int16(self, v: int) -> None:
        self._buf.extend(struct.pack('<h', int(v)))

    def _push_name(self, s: str) -> None:
        name = s.encode('windows-1252', errors='replace') + b'\x00'
        pad = (-len(name)) % 4
        if pad:
            name += b'\x00' * pad
        self._buf.extend(name)

    # ---------- Приватные helpers: запись во «внутренние» буферы чанков ----------
    def _i_push_word(self, inner: bytearray, w: str) -> None:
        if len(w) != 4:
            raise ValueError
        inner.extend(w.encode('ascii'))

    def _i_push_int(self, inner: bytearray, v: int) -> None:
        inner.extend(struct.pack('<i', int(v)))

    def _i_push_float(self, inner: bytearray, x: Union[float, str]) -> None:
        if isinstance(x, str):
            raw = bytes.fromhex(x)
            if len(raw) != 4:
                raise ValueError
            inner.extend(raw)
        else:
            inner.extend(struct.pack('<f', float(x)))

    def _i_push_floats(self, inner: bytearray, arr: Iterable[Union[float, str]]) -> None:
        for v in arr:
            self._i_push_float(inner, v)

    def _i_push_int16(self, inner: bytearray, v: int) -> None:
        inner.extend(struct.pack('<h', int(v)))

    def _i_push_ints16(self, inner: bytearray, arr: Iterable[int]) -> None:
        for v in arr:
            self._i_push_int16(inner, v)

    def _i_push_ints(self, inner: bytearray, arr: Iterable[int]) -> None:
        for v in arr:
            self._i_push_int(inner, v)

    def _i_push_name(self, inner: bytearray, s: str) -> None:
        name = s.encode('windows-1252', errors='replace') + b'\x00'
        pad = (-len(name)) % 4
        if pad:
            name += b'\x00' * pad
        inner.extend(name)

    # ---------- Вложенные помощники ----------
    @staticmethod
    def _flatten(seq: Iterable[Any]) -> List[Any]:
        out: List[Any] = []
        for v in seq:
            if isinstance(v, (list, tuple)):
                out.extend(v)
            else:
                out.append(v)
        return out

    def _pack_anim_into(self, inner: bytearray, item: Dict[str, Any]) -> None:
        # пишем «ANIM» блок прямо во внутренний буфер чанка
        self._i_push_word(inner, 'ANIM')
        self._i_push_int(inner, 1)

        keys = ('translation', 'rotation', 'scaling')

        # размеры по осям x/y/z
        for key in keys:
          for coord in ('x', 'y', 'z'):
              vals = (item.get(key) or {}).get(coord) or {}
              arr = vals.get('values')
              self._i_push_int(inner, len(arr) if arr is not None else 0)

        # сами ключи и значения
        for key in keys:
          for coord in ('x', 'y', 'z'):
            kvdict = (item.get(key) or {}).get(coord) or {}
            # vdict = (item.get(key) or {}).get('values') or {}

            keys_arr = kvdict.get('keys')
            # if keys_arr is None:
            #     continue
            vals_arr = kvdict.get('values') or []
            self._i_push_floats(inner, keys_arr)
            self._i_push_floats(inner, vals_arr)
