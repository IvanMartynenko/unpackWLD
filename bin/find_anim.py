#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import glob

# Добавляем путь к родительской директории, чтобы импортировать пакет common
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from common.nmf_parser import Nmf
except ImportError:
    print("Ошибка: Не удалось импортировать common.nmf_parser.")
    print("Убедитесь, что вы запускаете скрипт из папки, где родительская директория содержит папку 'common'.")
    sys.exit(1)

def get_animated_node_types(filepath):
    """
    Парсит файл и возвращает множество типов узлов, у которых есть анимация.
    Например: {"FRAM", "MESH"}
    """
    parser = Nmf()
    try:
        raw_nodes = parser.unpack(filepath)
    except Exception as e:
        print(f"Ошибка при чтении {filepath}: {e}")
        return set()

    animated_types = set()
    for node in raw_nodes:
        payload = node.get("payload", {})
        anim = payload.get("animation")

        # Если блок анимации существует и не пуст
        if anim:
            node_type = node.get("type", "UNKNOWN")
            animated_types.add(node_type)

        vertex_animations = payload.get("vertex_animations")
        if vertex_animations:
            node_type = node.get("type", "UNKNOWN")
            animated_types.add(node_type)
            
    return animated_types

def main():
    if len(sys.argv) < 2:
        print(f"Использование: python {os.path.basename(sys.argv[0])} <путь_к_папке_с_моделями_или_файлу>")
        sys.exit(1)

    target_path = sys.argv[1]

    # Определяем, что нам передали: один файл или директорию
    if os.path.isfile(target_path) and target_path.lower().endswith('.nmf'):
        files_to_check = [target_path]
    elif os.path.isdir(target_path):
        search_pattern = os.path.join(target_path, "**", "*.nmf")
        files_to_check = glob.glob(search_pattern, recursive=True)
    else:
        print(f"Указан неверный путь: {target_path}")
        sys.exit(1)

    print(f"Обработка файлов ({len(files_to_check)} шт.). Пожалуйста, подождите...")
    
    # Словари для группировки файлов по категориям
    categories = {
        "только FRAM": [],
        "только JOIN": [],
        "только FRAM+JOIN": [],
        "только MESH": [],
        "только FRAM+MESH": [],
        "только JOIN+MESH": [],
        "только FRAM+JOIN+MESH": [],
        "другими комбинациями (включая ROOT, LOCA и т.д.)": []
    }

    for filepath in files_to_check:
        anim_types = get_animated_node_types(filepath)
        
        if not anim_types:
            continue # Пропускаем файлы без анимации
            
        rel_path = os.path.relpath(filepath, start=os.getcwd())
        
        # Оставляем только целевые типы для базовой сортировки
        core_types = {t for t in anim_types if t in ("FRAM", "JOIN", "MESH")}
        
        # Если есть анимации на других нодах (ROOT, LOCA) и мы хотим это учитывать отдельно
        has_other_anim = len(anim_types) > len(core_types)

        if has_other_anim:
            categories["другими комбинациями (включая ROOT, LOCA и т.д.)"].append(rel_path)
        elif core_types == {"FRAM"}:
            categories["только FRAM"].append(rel_path)
        elif core_types == {"JOIN"}:
            categories["только JOIN"].append(rel_path)
        elif core_types == {"FRAM", "JOIN"}:
            categories["только FRAM+JOIN"].append(rel_path)
        elif core_types == {"MESH"}:
            categories["только MESH"].append(rel_path)
        elif core_types == {"FRAM", "MESH"}:
            categories["только FRAM+MESH"].append(rel_path)
        elif core_types == {"JOIN", "MESH"}:
            categories["только JOIN+MESH"].append(rel_path)
        elif core_types == {"FRAM", "JOIN", "MESH"}:
            categories["только FRAM+JOIN+MESH"].append(rel_path)

    # Вывод результатов
    print("\n" + "="*60)
    print("РЕЗУЛЬТАТЫ ПОИСКА АНИМАЦИИ (СГРУППИРОВАНО)")
    print("="*60 + "\n")
    
    # Порядок вывода, как вы просили
    order = [
        "только FRAM",
        "только JOIN",
        "только FRAM+JOIN",
        "только MESH",
        "только FRAM+MESH",
        "только JOIN+MESH",
        "только FRAM+JOIN+MESH",
        "другими комбинациями (включая ROOT, LOCA и т.д.)"
    ]
    
    for cat in order:
        files = categories[cat]
        if files:
            print(f"Файлы с {cat} animation ({len(files)} шт.):")
            for f in files:
                print(f"  - {f}")
            print()

if __name__ == "__main__":
    main()
