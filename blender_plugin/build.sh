#!/bin/sh

cd "$(dirname "$0")" || exit
cat ../common/nmf_parser.py nmf_convertor.py import_nmf.py register.py > blender.py