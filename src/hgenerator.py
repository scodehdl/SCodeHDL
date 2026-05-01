'''
    slab HDL code generator : module instance를 받아 *.vhd를 만든다.

    2014-05-05 
    2014-05-15 : support generic
    2014-06-01 : testbench는 별개의 file에 만드는 것으로 변경.
    2014-07-05 : library 추가 가능하게
    2015-04-13 : logic이 destination에 사용되지 않더라도, init이 정의되어 있으면 signal 정의한다.
    2015-08-12 : logic이 output으로 정의되어 있지 않더라도 signal 변환한다. 
    2015-11-11 : VHDL에서 scode_util.vhd 사용하지 않는다.
'''
import os,sys
import math
import itertools
import collections
import io

import _s2
import hsignal as hs
import hmodule as hm

# import hobject_stimulus as ht
import htestbench as ht

import codegen.cg_vhdl
import codegen.cg_verilog

vc = None

def hdl_code_generator(mod, outdir,*,silent,verilog=False):  
    # set conversion method
    global vc, vs
    if not verilog : 
        vc = codegen.cg_vhdl
    else : 
        vc = codegen.cg_verilog

    hdl_conversion_method(vc)

    # generate
    def _gen(mod,fname, func_header, func_body) :
        ''
        with open(fname, "w") as f:
            with _s2.stdout_redirected(f):
                func_header(mod)
                func_body(mod)
        if not silent :
            cwd = os.path.abspath('.')
            try:
                src_rel = os.path.relpath(os.path.abspath(mod.fname), cwd)
            except ValueError:
                src_rel = os.path.abspath(mod.fname)
            try:
                out_rel = os.path.relpath(os.path.abspath(fname), cwd)
            except ValueError:
                out_rel = os.path.abspath(fname)
            print('%s => [%s] generated' % (src_rel.replace('\\', '/'), out_rel.replace('\\', '/')))

    header = _vhdl_header if not verilog else _verilog_header
    body   = _vhdl_body if not verilog else _verilog_body
    ext    = '.vhd' if not verilog else '.v'

    _gen(mod,'%s/%s%s' % (outdir, _s2.filename_only(mod.fname),ext),header, body)



def hdl_conversion_method(vc) : 
    ''
    # value representation
    hs.BitVector.c_value          = vc.c_logic_value
    hs.Vector.c_value             = vc.c_vector_value
    hs.MultiVector.c_value        = vc.c_mulitvector_value
    hs.Array.c_value              = vc.c_array_value
    hs.LogicSlice.c_value         = vc.c_signalslice_value

    # reset
    hs.BitVector.c_value_reset   = vc.c_logic_value_reset
    hs.Vector.c_value_reset      = vc.c_vector_value_reset
    hs.MultiVector.c_value_reset = vc.c_multivector_value_reset
    hs.Array.c_value_reset       = vc.c_array_value_reset
    hs.StateLogic.c_value_reset  = vc.c_statelogic_value_reset

    # type definition
    hs.BitVector.c_type_def       = vc.c_type_def_logic
    hs.Vector.c_type_def      = vc.c_type_def_vector
    hs.Array.c_type_def       = vc.c_type_def_array
    hs.LogicSlice.c_type_def = vc.c_type_def_slice

    # declaration
    hs.LogicBase.c_signal_decl = vc.c_signal_decl 
    hs.LogicSlice.c_signal_decl = vc.c_signal_decl 
    hs.StateLogic.c_signal_decl = vc.c_signal_decl_state_logic 

    #-------------------------------------------------------------------------
    # c_repr 
    #-------------------------------------------------------------------------
    hs.LogicBase.c_repr         = vc.c_repr
    hs.LogicSlice.c_repr        = vc.c_repr_signalslice
    hs.VectorCombine.c_repr     = vc.c_repr_vector_combine
    hs.StateItem.c_repr         = vc.c_repr
    hs.SignalConstant.c_repr    = vc.c_repr_constant
    hs.ForVariable.c_repr       = vc.c_repr_for_var
    hs.SigValueType.c_repr      = vc.c_repr_valuetype  # TODO
    hs.SignalAssignment.c_repr  = vc.c_repr_signal_assignment

    #-------------------------------------------------------------------------
    # expression 
    #-------------------------------------------------------------------------
    hs.LogicExpr.c_repr             = vc.c_op_src_repr
    hs.FunctionExpr.c_repr          = vc.c_op_src_repr_function
    hs.BooleanOperator.c_repr       = vc.c_op_src_repr_boolean
    hs.ConditionOperator.c_repr     = vc.c_op_src_repr_condition
    hs.ArithmeticOperator.c_repr    = vc.c_op_src_repr_arithmetic
    hs.InvertOperator.c_repr        = vc.c_op_src_repr_invert

    hs.GenericArithmetic.c_repr     = vc.c_op_src_repr_generic_arithmetic

    #-------------------------------------------------------------------------
    # HDLObject
    #-------------------------------------------------------------------------
    hs.CBlock.c_hdl_repr          = vc.c_cblock_repr
    hs.ForGenerate.c_hdl_repr     = vc.c_forgen_repr
    hs.SeqBlock.c_hdl_repr        = vc.c_seqblock_repr
    hs.IModule.c_hdl_repr         = vc.c_module_repr
    hs.RawCode.c_hdl_repr         = vc.c_rawcode_repr
    hs.BlankLine.c_hdl_repr         = vc.c_blankline_repr
    hs.SwitchAssignment.c_hdl_repr = vc.c_switch_assign_repr

    # stimulus
    ht.DelayedAssignment.c_hdl_repr  = vc.c_delayed_assignment_repr
    ht.ClockedAssignment.c_hdl_repr  = vc.c_clocked_assignment_repr
    # ht.StimulusObject.c_hdl_repr     = vc.c_stimulus_repr
    # ht.StimulusClock.c_hdl_repr      = vc.c_stimulus_clock_repr
    # ht.StimulusReset.c_hdl_repr      = vc.c_stimulus_reset_repr
    # ht.StimulusWave.c_hdl_repr       = vc.c_stimulus_wave_repr
    # ht.StimulusFileInput.c_hdl_repr  = vc.c_stimulus_file_input_repr
    # ht.StimulusFileOutput.c_hdl_repr = vc.c_stimulus_file_output_repr




#-------------------------------------------------------------------------
#  VHDL conversion 
#-------------------------------------------------------------------------
def _vhdl_header(mod) :
    ''
    logics = mod.post.logics_dict
    def array_exists() : 
        ''
        for k,p in logics.items() : 
            if p.isarray() : 
                return True
        return False

    def _mk_package() : 
        if array_exists():
            if 1 : 
                defined_width = []
                print("library ieee; use ieee.std_logic_1164.all;")
                print("package %s_pkg is" % mod.mod_name)
                for k,p in logics.items() : 
                    if p.isarray() and (p.width not in defined_width) : 
                        print("    type std_%sbit_array is array (natural range <>) of std_logic_vector(%s downto 0);" % (p.width,p.width-1))
                        defined_width.append(p.width)
                print("end package;")
                print("use work.%s_pkg.all;\n" % mod.mod_name)

    print(_log_msg(verilog=False))


    print(__lib_default)
    if mod.isTestbench() and mod.tb_file_used: 
        print(__lib_testbench)

    # package and library
    # if _s2.USE_VHDL_2D_PORT and array_exists() : 
    #     print("use work.scode_util.all;")

    # declaration 
    for o in mod.hdl_objects:
        if isinstance(o, hs.LibraryDecl) :
            print()
            print(o.code)

    print()

    if mod.isTestbench() : 
        print('entity %s is' % mod.mod_name)
        print('end entity;\n')
        return

    #  
    print('entity %s is' % mod.mod_name)
    if len(mod.generic_dict) > 0 : 
        print('    %s' % _generic_def(mod.generic_dict))
    if len(mod.port_list) > 0:
        print('    %s' % _port_def(mod))
    print('end entity;')
    print()


def _port_def(mod):
    ''
    def _pdef_one(p):
        if p.io == hs.IOport.INP : 
            io = 'in'
        elif p.io == hs.IOport.OUTP : 
            io = 'out'
        else : 
            io = 'inout'


        if not p.init_defined: 
            return '%-19s : %s %s' % (p.name, io, p.c_type_def())
        else : 
            return '%-19s : %s %s:=%s' % (p.name, io, p.c_type_def(),p.c_value(p.init))

    def _pdef(p) :
        return [_pdef_one(p)]

    port_list = []
    for p in mod.port_list : 
        port_list += _pdef(p)

    port_def  = 'port (\n%s%s\n    );' % (' '*8, _s2.list_to_indented_line(port_list,8,';').strip()) 
    return port_def

def _generic_def(generic_dict) : 
    ''
    result = ''
    result += 'generic (\n'
    # s = ';\n'.join(['%-19s : integer := %s' % (g, generic_dict[g]) for g in generic_dict])
    s = ';\n'.join(['%-19s : integer := %s' % (g, generic_dict[g].value) for g in generic_dict])


    result += '%s\n' % _s2.set_indentation(s,4)

    result += ');\n'

    return _s2.set_indentation(result,4).strip()



def _vhdl_body(mod) :
    ' declaration + body '
    print('architecture arch_{entity_name} of {entity_name} is'.format(entity_name=mod.mod_name))
    _vhdl_declaration(mod)
    print('\nbegin')
    _vhdl_arch_body(mod)
    print('\nend architecture;')
    
    
def _vhdl_declaration(mod) :
    ' component/type/signal definition '

    # array type definition
    # if not _s2.USE_VHDL_2D_PORT : 
    defined_width = []
    # for k,p in hm.get_module_local_logics(mod).items(): 
    for k,p in mod.post.local_logics_dict.items(): 
        if p.isarray() and (p.width not in defined_width) : 
            print("type std_%sbit_array is array (natural range <>) of std_logic_vector(%s downto 0);" % (p.width,p.width-1))
            defined_width.append(p.width)


    __comp_def = '''
component {comp_name}
    {port_def}
end component;
'''.lstrip()
    __comp_def_gen = '''
component {comp_name}
    {generic_def}
    {port_def}
end component;
'''.lstrip()
    
    # component declaration
    mo = [o for o in mod.hdl_objects if isinstance(o, hs.IModule)]
    mo_names = []
    for o in mo: 
        name = o.module.mod_name
        # if name not in mo_names : 
        if name not in mo_names and name not in mod.lib_components:
            if len(o.module.generic_dict) > 0 : 
                # vhdl로 부터 module이 만들어지고, generic이 있으면, generic define한다.
                print(__comp_def_gen.format(comp_name=name, port_def=_port_def(o.module),
                                            generic_def=_generic_def(o.module.generic_dict)))
            else : 
                print(__comp_def.format(comp_name=name, port_def=_port_def(o.module)))

            mo_names.append(name)

    # declaration (raw code)
    mo = [o for o in mod.hdl_objects if isinstance(o, hs.RawCodeDecl)]
    for o in mo : 
        print(o.code)

    # type declaration
    sig_list = _filter_signal_list(mod)

    # state type declaration
    for p in mod.state_types : 
        if isinstance(p,hs.StateType):
            s  = 'type %s is (%s);\n' % (p.name,','.join([s.name for s in p.state_items]))
            print(s)


    # signal declaration
    for s in sig_list : 
        print(s.c_signal_decl())


def _vhdl_arch_body(mod) :
    ' '
    processed_delayed_signals = set()
    for o in mod.hdl_objects : 
        if isinstance(o, (hs.RawCodeDecl, hs.LibraryDecl)):
            continue

        if isinstance(o, ht.DelayedAssignment) and not o.repeat:
            if o.signal.name in processed_delayed_signals:
                continue
            
            # Find all non-repeating assignments for this signal
            points = []
            for o2 in mod.hdl_objects:
                if isinstance(o2, ht.DelayedAssignment) and o2.signal.name == o.signal.name and not o2.repeat:
                    points.append(o2)
            
            # Sort by time
            points.sort(key=lambda p: p.delay)
            
            # Generate consolidated repr
            # vc is codegen.cg_vhdl or cg_verilog
            if hasattr(vc, 'c_consolidated_assignment_repr'):
                s = vc.c_consolidated_assignment_repr(o.signal, points)
            else:
                # Fallback to individual assignments if not supported by backend
                s = '\n'.join([p.c_hdl_repr() for p in points])
                
            print('%s' % _s2.set_indentation(s,4))
            processed_delayed_signals.add(o.signal.name)

        elif isinstance(o, ht.DelayedAssignment) and o.repeat:
            # Repeat (clock) assignments remain separate
            s = o.c_hdl_repr()
            print('%s' % _s2.set_indentation(s,4))

        elif isinstance(o, hs.BlankLine):
            s = o.c_hdl_repr()
            print(s,end='')
        elif isinstance(o, ht.ClockedAssignment):
            # Handled by consolidation below or individually if logic is changed
            continue
        else :
            s = o.c_hdl_repr()
            print('%s' % _s2.set_indentation(s,4))

    # Consolidated Clocked Stimulus
    processed_clocked = set()
    for o in mod.hdl_objects:
        if isinstance(o, ht.ClockedAssignment):
            gid = o.group_id
            key = (id(o.clk), id(gid) if gid is not None else id(o.signal))
            if key in processed_clocked:
                continue

            if gid is not None:
                # Grouped: collect all signals sharing (clk, group_id) → one process
                all_in_group = [o2 for o2 in mod.hdl_objects
                                if isinstance(o2, ht.ClockedAssignment)
                                and o2.clk is o.clk and o2.group_id is gid]
                signal_map = {}
                for o2 in all_in_group:
                    sid = id(o2.signal)
                    if sid not in signal_map:
                        signal_map[sid] = (o2.signal, [])
                    signal_map[sid][1].append(o2)
                groups = [(sig, sorted(pts, key=lambda p: p.cycle))
                          for sig, pts in signal_map.values()]

                if hasattr(vc, 'c_consolidated_group_clocked_repr'):
                    s = vc.c_consolidated_group_clocked_repr(o.clk, groups)
                else:
                    s = '\n'.join(vc.c_consolidated_clocked_assignment_repr(o.clk, sig, pts)
                                  for sig, pts in groups)
            else:
                # Individual signal: existing behaviour
                points = [o2 for o2 in mod.hdl_objects
                          if isinstance(o2, ht.ClockedAssignment)
                          and o2.clk is o.clk and o2.signal is o.signal]
                points.sort(key=lambda p: p.cycle)

                if hasattr(vc, 'c_consolidated_clocked_assignment_repr'):
                    s = vc.c_consolidated_clocked_assignment_repr(o.clk, o.signal, points)
                else:
                    s = '\n'.join([p.c_hdl_repr() for p in points])

            print('%s' % _s2.set_indentation(s, 4))
            processed_clocked.add(key)


#-------------------------------------------------------------------------
# i/o만 정의  
#-------------------------------------------------------------------------
def _filter_signal_list(mod) : 
    ' 정의된 모든 signal을 port에 없으면 변환한다 '
    # port와 variable은 signal 정의에서 제외한다.
    port_names = [p.name for p in mod.port_list]

    _vars = []
    for o in mod.hdl_objects : 
        _vars += [s.name for s in o.variables]

    ## 
    logic_list = [] 

    # objects에 i/o로 사용된 신호는 모두 포함한다. 
    for o in mod.hdl_objects : 
        for sig in itertools.chain(o.osignals,o.isignals) :
            # print(sig,sig.name,file=sys.stderr)
            if not isinstance(sig,(hs.LogicBase,hs.LogicSlice)) : 
                continue

            if isinstance(sig,hs.LogicSlice) : 
                sig = sig.base_signal

            if (sig.name not in port_names) and (sig.name not in _vars): 
                if sig.name not in [p.name for p in logic_list] : 
                    logic_list.append(sig)

    return logic_list


def _log_msg(verilog=False) : 
    comment = '--' if not verilog else '//'
    __logo_msg = '''
--------------------------------------------------------------------------------
 This file was generated by scode
 DONOT EDIT MANUALLY !!!
--------------------------------------------------------------------------------'''
    return '\n'.join('%s%s' % (comment, s) for s in __logo_msg.strip().split('\n'))


__lib_default = '''
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;'''.strip()


__lib_testbench = '''
use ieee.std_logic_textio.all;
use std.textio.all;
'''.strip()

#-------------------------------------------------------------------------
#  Verilog conversion 
#-------------------------------------------------------------------------
def _verilog_header(mod) :
    ''
    # print("/// WARNING : Verilog conversion is beta stage, USE IT ONLY FOR TEST PURPOSE")
    print(_log_msg(verilog=True))

    for o in mod.hdl_objects : 
        if isinstance(o, (hs.RawCodeDecl, hs.LibraryDecl)):
            print(o.code)

    #-------------------------------------------------------------------------
    #  testbench 
    #-------------------------------------------------------------------------
    # if isinstance(mod, hm.TestbenchModule) : 
    if mod.isTestbench() :
        # print('`timescale 1ns/100ps')
        print('module %s;' % mod.mod_name)
        return 

    #-------------------------------------------------------------------------
    # normal module
    #-------------------------------------------------------------------------
    print('module %s' % mod.mod_name,end='')
    if len(mod.generic_dict) > 0 : 
        print('#(')
        # generic definition
        print('    %s' % _s2.set_indentation(_verilog_generic_def(mod),4).lstrip())
        print(') (')
    else : 
        print('(')


    print('    %s' % _s2.set_indentation(_verilog_port_def(mod),4).lstrip())
    print(');')


def _verilog_body(mod) :
    ' declaration + body '

    logic_list = _filter_signal_list(mod)

    for s in logic_list: 
        print(s.c_signal_decl())

    # forloop variables
    for seq_flag, name in mod.forvar : 
        n = 'genvar' if seq_flag==0 else 'integer'
        print('    %s %s;' % (n,name))


    # state type declaration
    for p in mod.state_types : 
        if isinstance(p,hs.StateType):

            w = p.state_bits_width

            s = ','.join(['%s=%s' % (s.name,codegen.cg_verilog._hex_formatting(s.encoding_value,w)) for s in p.state_items])
            s = '    parameter %s;' % s
            print(s)
    
    print()


    # array initialization : reg_list에서 array있나 check
    reg_list = [s for s in logic_list if s.reg_wire]
    for s in reg_list : 
        if s.isarray() and s.init_defined : 
            s1 = []
            s2 = []
            for i in range(len(s.init)):
                s1.append('%s[%s]' % (s.name,i))
                s2.append('%s' % (s[i].c_value(s.init[i])))
            print('    initial {%s} = {%s};' % (','.join(s1),','.join(s2)))

    print()

    # objects
    for o in mod.hdl_objects : 
        if isinstance(o, (hs.RawCodeDecl, hs.LibraryDecl)):
            continue

        if isinstance(o, hs.BlankLine):
            s = o.c_hdl_repr()
            print(s,end='')
        elif isinstance(o, ht.ClockedAssignment):
            continue
        else :
            s = o.c_hdl_repr()
            print('%s' % _s2.set_indentation(s,4))

    # Consolidated Clocked Stimulus
    processed_clocked = set()
    for o in mod.hdl_objects:
        if isinstance(o, ht.ClockedAssignment):
            gid = o.group_id
            key = (id(o.clk), id(gid) if gid is not None else id(o.signal))
            if key in processed_clocked:
                continue

            if gid is not None:
                # Grouped: collect all signals sharing (clk, group_id) → one process
                all_in_group = [o2 for o2 in mod.hdl_objects
                                if isinstance(o2, ht.ClockedAssignment)
                                and o2.clk is o.clk and o2.group_id is gid]
                signal_map = {}
                for o2 in all_in_group:
                    sid = id(o2.signal)
                    if sid not in signal_map:
                        signal_map[sid] = (o2.signal, [])
                    signal_map[sid][1].append(o2)
                groups = [(sig, sorted(pts, key=lambda p: p.cycle))
                          for sig, pts in signal_map.values()]

                if hasattr(vc, 'c_consolidated_group_clocked_repr'):
                    s = vc.c_consolidated_group_clocked_repr(o.clk, groups)
                else:
                    s = '\n'.join(vc.c_consolidated_clocked_assignment_repr(o.clk, sig, pts)
                                  for sig, pts in groups)
            else:
                # Individual signal: existing behaviour
                points = [o2 for o2 in mod.hdl_objects
                          if isinstance(o2, ht.ClockedAssignment)
                          and o2.clk is o.clk and o2.signal is o.signal]
                points.sort(key=lambda p: p.cycle)

                if hasattr(vc, 'c_consolidated_clocked_assignment_repr'):
                    s = vc.c_consolidated_clocked_assignment_repr(o.clk, o.signal, points)
                else:
                    s = '\n'.join([p.c_hdl_repr() for p in points])

            print('%s' % _s2.set_indentation(s, 4))
            processed_clocked.add(key)

    print('\nendmodule')


def _verilog_port_def(mod):
    def _verilog_port_conversion(p) :
        'input [type] name'
        if p.io == hs.IOport.INP : 
            io = 'input'
        elif p.io == hs.IOport.OUTP : 
            # io = 'output'
            io = 'output' if p.reg_wire==0 else 'output reg'
        else : 
            io = 'inout'

        if isinstance(p,hs.BitVector) :
            s = '{:<6} {}'.format(io,p.name)
        else:
            s = '{:<6} {} {}'.format(io,p.c_type_def(),p.name)

        if not p.init_defined : 
            return '%s' % s
        else: 
            return '%s = %s' % (s,p.c_value(p.init))

    port_list = [_verilog_port_conversion(p) for p in mod.port_list]
    # return '\n'.join(port_list)
    return ',\n'.join(port_list)

def _verilog_generic_def(mod):
    ''
    generic_dict = mod.generic_dict

    s = ',\n'.join(['parameter %-9s = %s' % (g, generic_dict[g].value) for g in generic_dict])

    return s


def component_definition(mod) :
    ' mod의 vhdl, verilog component definition을 출력한다. '
    out_str = ''
    stream = io.StringIO(out_str)

    # verilog instantiation

    # verilog port definition
    with _s2.stdout_redirected(stream):

        print('\nmodule %s' % mod.mod_name,end='')
        if len(mod.generic_dict) > 0 : 
            print('#(')
            # generic definition
            print('    %s' % _s2.set_indentation(_verilog_generic_def(mod),4).lstrip())
            print(') (')
        else : 
            print('(')


        print('    %s' % _s2.set_indentation(_verilog_port_def(mod),4).lstrip())
        print(');')
        print('endmodule\n')

    return stream.getvalue()


if __name__ == '__main__' :
    ''


