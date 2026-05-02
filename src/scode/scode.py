import sys
import os
import fnmatch
import argparse
from pathlib import Path

# src 디렉토리를 sys.path에 추가 (run_scode와 관련 모듈들을 찾을 수 있도록)
_src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import run_scode
import _s2
from scode import __version__


def _parse_defines(dlist):
    result = {}
    for item in dlist:
        if '=' not in item:
            raise SystemExit(f'error: -D {item!r} must be NAME=VALUE')
        name, _, raw = item.partition('=')
        if raw.lower() in ('true', 'false'):
            value = raw.lower() == 'true'
        else:
            try:
                value = int(raw)
            except ValueError:
                try:
                    value = float(raw)
                except ValueError:
                    value = raw
        result[name.strip()] = value
    return result


def _find_sc_files(root_dir, ignore_file=None):
    '''Recursively find .sc files under root_dir, respecting an ignore file.'''
    root = Path(root_dir)
    patterns = []
    if ignore_file is not None:
        ignore_path = Path(ignore_file)
    else:
        ignore_path = root / '.scodeignore'
    if ignore_path.exists():
        for line in ignore_path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                patterns.append(line)

    sc_files = []
    for sc in sorted(root.rglob('*.sc')):
        rel = sc.relative_to(root).as_posix()
        if _is_ignored(rel, sc.name, patterns):
            continue
        sc_files.append(str(sc))
    return sc_files


def _is_ignored(rel_path, filename, patterns):
    for pat in patterns:
        if pat.endswith('/'):
            # directory pattern: skip if any path component matches
            if rel_path.startswith(pat) or ('/' + pat) in ('/' + rel_path):
                return True
        else:
            if fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(filename, pat):
                return True
    return False


def main():
    try:
        _main()
    except _s2.SCSourceError as e:
        e.display()
        sys.exit(1)
    except (FileNotFoundError, OSError) as e:
        print('FileNotFoundError: %s' % e)
        sys.exit(1)


def _main():
    parser = argparse.ArgumentParser(
        prog='scode',
        description='HDL (VHDL/Verilog) generator from .sc files',
    )

    parser.add_argument('--version', action='version', version=f'scode {__version__}')
    parser.add_argument('file', nargs='?', help='source .sc file')
    parser.add_argument('-r', action='store_true',
                        help='recursively convert all .sc files from current directory')
    parser.add_argument('-o', metavar='outdir', default=None,
                        help='output directory (default: current directory or config.ini)')

    out_group = parser.add_mutually_exclusive_group()
    out_group.add_argument('-v', action='store_true',
                           help='generate Verilog output (default is VHDL)')
    out_group.add_argument('-a', action='store_true',
                           help='generate both VHDL and Verilog output')

    parser.add_argument('-D', metavar='NAME=VALUE', action='append', default=[],
                        help='define a constant passed to .sc files; may be repeated (e.g. -D PROJNAME=p50 -D VERSION=2)')
    parser.add_argument('-c', action='store_true',
                        help='print imodule template for use as a component')
    parser.add_argument('-j', action='store_true',
                        help='Debuggin purpose : also write JSON module info (<module>.json)')
    parser.add_argument('--ignore-file', metavar='FILE', default=None,
                        help='ignore file to use with -r (default: .scodeignore)')

    args = parser.parse_args()

    _s2.set_defines(_parse_defines(args.D))

    if args.r and args.file:
        parser.error('-r and file argument are mutually exclusive')

    if not args.r and args.file is None:
        parser.print_help()
        return

    if args.r:
        _run_recursive(args)
    else:
        _run_single(args)


def _run_single(args):
    fname = args.file
    root_dir = os.path.abspath('.')

    if args.c:
        print(run_scode.get_imodule_template(fname))
        return

    if args.a:
        run_scode.exec_slab([fname], root_dir=root_dir, outdir=args.o, plugin_run=True,
                            verilog=False, save_json=args.j)
        run_scode.exec_slab([fname], root_dir=root_dir, outdir=args.o, plugin_run=True,
                            verilog=True,  save_json=False)
    else:
        verilog = args.v or _s2.get_verilog_output()
        _s2.admin = True
        run_scode.exec_slab([fname], root_dir=root_dir, outdir=args.o, plugin_run=True,
                            verilog=verilog, save_json=args.j)


def _run_recursive(args):
    root_dir = os.path.abspath('.')
    sc_files = _find_sc_files(root_dir, ignore_file=args.ignore_file)

    if not sc_files:
        print('No .sc files found.')
        return

    print(f'Found {len(sc_files)} .sc file(s) under {root_dir}')

    if args.a:
        run_scode.exec_slab(sc_files, root_dir=root_dir, outdir=args.o, plugin_run=True,
                            verilog=False, save_json=args.j)
        run_scode.exec_slab(sc_files, root_dir=root_dir, outdir=args.o, plugin_run=True,
                            verilog=True,  save_json=False)
    else:
        verilog = args.v or _s2.get_verilog_output()
        _s2.admin = True
        run_scode.exec_slab(sc_files, root_dir=root_dir, outdir=args.o, plugin_run=True,
                            verilog=verilog, save_json=args.j)
