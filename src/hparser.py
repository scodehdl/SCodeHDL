'''
    SC file parser pipeline and HDL import utilities
    Extracted from hmodule.py (Phase 5 slim-down)
'''
import os
import collections
import functools
import io

import _s2
import hsignal as hs
import htestbench as ht

import parser_vhdl
import parser_verilog
import parser_common
import ast_signal, ast_exec

# hmodule is imported lazily inside functions to avoid circular import
import hmodule as hm


core_lib_code = ''

#-------------------------------------------------------------------------
# sc file parsing pipeline
#-------------------------------------------------------------------------

def parse_scfile(fname, *, parent=None, outdir=None, debug_log=False, verilog=False):
    ' run_slab 또는 HDLModule의 include method에 의해 call 된다. '
    ' fname은 항상 *.sc의 extension을 갖게 된다.'
    _core_lib_parsed()

    if not os.path.exists(fname):
        raise FileNotFoundError('[%s] %s not found' % (os.getcwd(), fname))

    contents = _get_sc_contents(fname)
    try:
        parsed = _transformCode(contents)
    except SyntaxError as e:
        _s2.raise_sc_source_error_syntax(fname, e)

    # 1st run
    with hs.stay_signal_instancd_id():
        dummy_str = ''
        with _s2.stdout_redirected(io.StringIO(dummy_str)):
            _mod = _mk_module(fname, parent, outdir, _1st_run=True)
            with hs.module_assigned_to_target(_mod):
                ast_exec.ast_exec(_mod, parsed)

        _mod.delete_module_logic_unique()
        _mod.delete_module_statesignal()

    # 2nd run
    _s2.debug_view('2nd run started')
    module = _mk_module(fname, parent, outdir, _1st_run=False)
    module.debug_log = debug_log
    module.verilog   = verilog

    module.namespace = _mod.namespace
    module.imodules  = _mod.imodules

    with hs.module_assigned_to_target(module):
        with _s2.pythonpath(module.basepath):
            _exec_2nd_run(module, parsed, verilog)

        _s2.debug_view('2nd run :', module.hdl_objects)
        _s2.debug_view('Dependency files [%s : %s]' % (module.mod_name, module.dependent_files))

        module.parsed = parsed

    return module


def _transformCode(contents):
    '''Apply AST transformations: if-rewrite then signal-spec rewrite.'''
    parsed = ast_signal.astTransformCodeIf(contents)
    parsed = ast_signal.applyTupleAssignTransform(parsed)
    parsed = ast_signal.applySignalSpecTransform(parsed)
    return parsed


def _core_lib_parsed():
    global core_lib_code

    fname = 'core_lib.sh'
    if not os.path.exists(fname):
        fname = _s2.get_include_file(fname)

    with open(fname, 'r', encoding='latin-1') as f:
        parsed = _transformCode(f.read())
        core_lib_code = compile(parsed, '', 'exec')

    _s2.debug_view('%s included' % fname)


_pre_cmd = '''
from builtins import *
from sc_api import *

# global variables which are used in *.sc file
BASEPATH="{basepath}"
OUTDIR  ="{outdir}"
PROJNAME = "{proj_name}"


#-------------------------------------------------------------------------
# if changed to ifblock in ast
# so *.sc file should know the prototype of ifblock
def ifblock(*args,**kwargs) : return hs.get_assign_target().ifblock(*args,**kwargs)
def If(*args,**kwargs)      : return hs.get_assign_target().If(*args,**kwargs)
def Elif(*args,**kwargs)    : return hs.get_assign_target().Elif(*args,**kwargs)
def Else(*args,**kwargs)    : return hs.get_assign_target().Else(*args,**kwargs)
'''

def _exec_pre_cmd(module, outdir):
    if isinstance(outdir, str):
        outdir = outdir.replace('\\', '/')

    code = compile(
        _pre_cmd.format(basepath=module.basepath, outdir=outdir, proj_name=_s2.get_proj_name()),
        '', 'exec'
    )
    exec(code, module.namespace)
    exec(core_lib_code, module.namespace)
    module.namespace.update(_s2.get_defines())


def _mk_module(fname, parent, outdir, _1st_run=False):
    module_name = _s2.filename_only(fname)
    module = hm.HDLModule('%s' % module_name, parent=parent, outdir=outdir, fname=fname)
    module.set_1st_run(_1st_run)
    return module


def _get_sc_contents(fname):
    with open(fname, 'r', encoding='latin-1') as f:
        contents = f.read()
    return contents


def _1st_run_for_logic_definition(fname, parent, outdir=None):
    '''Run only the 1st pass to discover port/signal names.'''
    module = _mk_module(fname, parent, outdir, _1st_run=True)
    with hs.module_assigned_to_target(module):
        contents = _get_sc_contents(fname)
        ast_exec.ast_exec(module, _transformCode(contents))
    return module


def _exec_2nd_run(module, parsed, verilog=False):
    try:
        exec(compile(parsed, module.fname, 'exec'), module.namespace)
    except _s2.SCSourceError:
        raise
    except Exception as e:
        _s2.raise_sc_source_error(e, e.__traceback__)

    name_list = [
        k for k in module.namespace
        if isinstance(module.namespace[k], hs.SignalUnspecified)
    ]
    if name_list:
        _s2.debug_view('[%s] 2nd run end [%s]' % (module.mod_name, name_list))
        raise AssertionError('[%s] %s not defined' % (module.fname, name_list))


#-------------------------------------------------------------------------
# HDL import (VHDL / Verilog → HDLModule)
#-------------------------------------------------------------------------

def _mk_signal_port(p, generic_dict):
    ptype, pnames = p['type'], p['names']
    if isinstance(ptype, list):
        ptype = ptype[0] if ptype else ''
    init = float('nan')
    sig  = []

    def _vector_append(p, sig_type):
        try:
            a = int(p['range']['from'])
            b = int(p['range']['to'])
            _w = hs.slice_width(a, b)
            little_endian = p['range']['dir'] == 'downto'
            sig.append(hs.Vector(_w, name=pname, init=init, little_endian=little_endian, sig_type=sig_type))
        except:
            little_endian = p['range']['dir'] == 'downto'
            _w = parser_common.getVectorWidth(p['range'], generic_dict)
            v  = hs.Vector(_w, name=pname, init=init, little_endian=little_endian, sig_type=sig_type)
            sig.append(v)
            v.hdl_width_dict = p['range']

    for pname in pnames:
        if ptype == 'std_logic':
            sig.append(hs.BitVector(name=pname, init=init))
        elif 'std_logic_vector' in ptype:
            _vector_append(p, hs.SigType.logic)
        elif 'unsigned' in ptype:
            _vector_append(p, hs.SigType.unsigned)
        elif 'signed' in ptype:
            _vector_append(p, hs.SigType.signed)
        else:
            w, l = parser_common.getArrayWidthLength(p['type'], p['range'], {})
            sig.append(hs.Array(l, w, name=pname))

    return sig


def make_module_from_vhdl_file(fname, *, parent=None):
    with open(fname, encoding='latin-1') as f:
        contents = f.read()
    m = make_module_from_vhdl_string(contents, parent=parent)
    m.fname = fname
    return m


def make_module_from_vhdl_string(contents, *, parent=None):
    o = parser_vhdl.parseEntityDefinition(contents)

    if 'generics' in o:
        sdict = collections.OrderedDict()
        for k in o['generics']:
            sdict[k['name']] = k['value']
    else:
        sdict = {}

    port_list = []
    for p in o['ports']:
        sig = _mk_signal_port(p, sdict)
        for s in sig:
            if   p['io'] == 'in'    : s.io = hs.INP
            elif p['io'] == 'out'   : s.io = hs.OUTP
            elif p['io'] == 'inout' : s.io = hs.INOUTP
        port_list += sig

    port_in    = [p for p in port_list if p.io == hs.INP]
    port_out   = [p for p in port_list if p.io == hs.OUTP]
    port_inout = [p for p in port_list if p.io == hs.INOUTP]

    m = hm.VHDLModule(o['entity_name'], parent=parent)
    m.inport_list    = port_in
    m.outport_list   = port_out
    m.inoutport_list = port_inout

    m.generic_dict = collections.OrderedDict()
    for k, v in sdict.items():
        m.generic_dict[k] = hs.GenericVar(k, v)

    return m


def make_module_from_verilog_file(fname, *, parent=None):
    with open(fname, encoding='latin-1') as f:
        contents = f.read()
    m = make_module_from_verilog_string(contents, parent=parent)
    m.fname = fname
    return m


def make_module_from_verilog_string(contents, *, parent=None):
    o = parser_verilog.parseModuleDefinition(contents)

    port_list = []
    for p in o['ports']:
        pname = p['name']
        if 'range' in p:
            _w = abs(p['range'].start - p['range'].stop) + 1
            little_endian = p['range'].start >= p['range'].stop
            sig = hs.Vector(_w, name=pname, little_endian=little_endian)
        else:
            sig = hs.BitVector(name=pname)

        if   p['io'] == 'input'  : sig.io = hs.INP
        elif p['io'] == 'output' : sig.io = hs.OUTP
        elif p['io'] == 'inout'  : sig.io = hs.INOUTP

        port_list.append(sig)

    port_in    = [p for p in port_list if p.io == hs.INP]
    port_out   = [p for p in port_list if p.io == hs.OUTP]
    port_inout = [p for p in port_list if p.io == hs.INOUTP]

    m = hm.VerilogModule(o['module_name'], parent=parent)
    m.inport_list    = port_in
    m.outport_list   = port_out
    m.inoutport_list = port_inout
    return m


#-------------------------------------------------------------------------
# module library helpers
#-------------------------------------------------------------------------

def _mk_lib_mod(parent, name, in_list, out_list, io_list, generic_dict, lib_code=None):
    mod = _mk_lib_mod_sub(parent, name, in_list, out_list, io_list, generic_dict)
    if lib_code:
        parent.namespace[name] = functools.partial(_lib_module_func_with_lib, mod, lib_code)
    else:
        parent.namespace[name] = functools.partial(_lib_module_func, mod)
    return mod


def _mk_lib_mod_sub(parent, name, in_list, out_list, io_list, generic_dict):
    _mod = hm.HDLModule(name, parent=parent)

    if in_list  : _mod.inport(*in_list)
    if out_list : _mod.outport(*out_list)
    if io_list  : _mod.inoutport(*io_list)

    if generic_dict:
        _mod.generic_dict.update(generic_dict)

    return _mod


def _lib_module_func(mod, **kwargs):
    _lib_module_check_add(hs.get_module(), mod, kwargs)


def _lib_module_func_with_lib(mod, lib_code, **kwargs):
    parent = hs.get_module()
    if not any(isinstance(o, hs.LibraryDecl) and o.code == lib_code for o in parent.hdl_objects):
        parent.rawcode_lib(lib_code)
    _lib_module_check_add(parent, mod, kwargs)


def _lib_module_check_add(parent, mod, kwargs):
    if parent._1st_flag:
        if any(isinstance(kwargs[k], hs.SignalUnspecified) for k in kwargs):
            parent._imodule_auto_define(mod, kwargs)
        return
    parent.imodule_check_add(mod, [], kwargs)
