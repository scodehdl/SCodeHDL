'''
    API method for *.sc file
    2014-05-05 
    2014-07-02
    2014-10-02 define usignal
    2015-02-12 utility functions
    2015-08-12 signal -> logic
'''
import importlib
import os,sys
import math
from contextlib import contextmanager

##########################################################
# WARNING : sc_api는 _s2,hsignal, htestbench만 import한다. 
##########################################################

import hsignal as hs
import htestbench as ht
import hmodule as hm


# and,or,xor
And = hs.AndExpr
Or  = hs.OrExpr
Xor = hs.XorExpr

# Ge,Gt,Le,Lt
Ge = hs.GeExpr
Gt = hs.GtExpr
Le = hs.LeExpr
Lt = hs.LtExpr

concat = hs.VectorCombine

LogicBase = hs.LogicBase

HH = hs.HH
LL = hs.LL
ZZ = hs.ZZ
XX = hs.XX
INT = hs.INT
FILL = hs.FILL


#-------------------------------------------------------------------------
# module methods
#-------------------------------------------------------------------------
def modulename(mod_name)            : return hs.get_module().modulename(mod_name)
def modulewrapper(name,i,o,io=[],gen={})  : return hs.get_module().modulewrapper(name,i,o,io,gen)

def inport(*args)                : hs.get_module().inport(*args)
def outport(*args,init=hs.NAN)   : hs.get_module().outport(*args,init=init)
def inoutport(*args,init=hs.NAN) : hs.get_module().inoutport(*args,init=init)
def dynport(*args,**kwargs)  : hs.get_module().dynport(*args,**kwargs)

def generic(**kwargs)         : hs.get_module().generic(**kwargs)

def _logic_define(s,sig_type,str_type,**kwargs):
    if type(s) is str : 
        return hs.get_module().logic_define(s,sig_type=sig_type,**kwargs)
    elif isinstance(s,(hs.LogicBase,hs.LogicSlice,hs.ArithmeticOperator)):
        return hs.FunctionExpr(str_type,s)
    else : 
        assert 0, '%s(%s) is known argument type' % (s,type(s))

def unsigned(s) : return _logic_define(s,hs.SigType.unsigned,'unsigned') 
def signed(s)   : return _logic_define(s,hs.SigType.signed,'signed') 

def logic(s,**kwargs)    : return hs.get_module().logic_define(s,sig_type=hs.SigType.logic,**kwargs) 
def logic_unique(s)        : return hs.get_module().logic_unique_define(s,sig_type=hs.SigType.logic)

def logic_like(name,src) : return hs.copy_logic_like(hs.get_module(),name,src)
def logic_like_unique(name,src) : return hs.copy_logic_like_unique(hs.get_module(),name,src)

def array(s,**kwargs)    : return hs.get_module().array_define(s,sig_type=hs.SigType.logic,**kwargs) 
def array_unique(s,*,init=None) : return hs.get_module().array_unique_define(s,sig_type=hs.SigType.logic,init=init)

# state machine
# statetype(st,st_idle,st_rdy,st_cnt)
# statelogic(one_clk, st)
# => 가급적 statetype, statelogic을 사용하지 말고, 
# 한 번에 정의할 수 있는 아래의 stdefine을 이용한다. 

def statetype(*args,**kwargs)        : return hs.get_assign_target().statetype_define(*args,**kwargs)
def statetype_unique(*args,**kwargs) : return hs.get_assign_target().statetype_unique_define(*args,**kwargs)

def statelogic(*args,**kwargs)        : return hs.get_assign_target().statelogic_define(*args,**kwargs)
def statelogic_unique(*args,**kwargs) : return hs.get_assign_target().statelogic_unique_define(*args,**kwargs)

def stdefine(name, *states):
    ''' stdefine(lutstate, st_idle, st_rdy, st_cnt) — AST converts all args to strings.
    StateType + StateLogic 생성, StateItems를 namespace에 등록. StateLogic 반환.
    '''
    mod = hs.get_assign_target()
    st = mod.statetype_define('%s_type' % name, *states)
    sl = mod.statelogic_define(name, st)
    for s in states:
        hs.get_module().namespace[s] = st.item(s)
    return sl

def stdefine_unique(name, *states):
    mod = hs.get_assign_target()
    st = mod.statetype_unique_define('%s_type' % name, *states)
    sl = mod.statelogic_unique_define(name, st)
    for s in states:
        hs.get_module().namespace[s] = st.item(s)
    return sl

##
def rawcode_decl(*args,**kwargs)    : return hs.get_module().rawcode_decl(*args,**kwargs)
def rawcode(*args,**kwargs)         : return hs.get_module().rawcode(*args,**kwargs)
def rawcode_lib(s)                      : return hs.get_module().rawcode_lib(s)

def lib_module(name, i=None, o=None, io=None, generic=None, lib_code=None):
    ' Register an external library component (no component declaration will be emitted). '
    hm._mk_lib_mod(hs.get_module(), name, i, o, io, generic, lib_code)
    hs.get_module().lib_components.append(name)

def blankline(n=1) : return hs.get_module().blankline(n)


def include(*args,**kwargs)         : return hs.get_module().include(*args,**kwargs)
def imodule(name,**kwargs)         : return hs.get_module().imodule(name,**kwargs)
 
def donotconvert() : 
    hs.get_module().conversion_flag = False


def unique(): return hs.get_module().unique()

#-------------------------------------------------------------------------
# sequence interface
#-------------------------------------------------------------------------
def sequence(*args,**kwargs)  : 
    return hs.get_assign_target().sequence_block(*args,**kwargs)

def switch(case_sig): 
    return hs.get_assign_target().switch(case_sig=case_sig)

def case(*args,**kwargs)  : 
    return hs.get_assign_target().case(*args,**kwargs)

def others(*args,**kwargs) : 
    return hs.get_assign_target().others(*args,**kwargs)

def pycond(flag) : return flag

def forloop(name,start,stop) :
    return hs.get_assign_target().forgen_block(name,start,stop)

#-------------------------------------------------------------------------
# testbench 
#-------------------------------------------------------------------------
def testbench(fname)                : return hs.get_module().testbench(fname)

def tb_clock(clk, period=20):
    ' clk: signal object. Toggles every period/2 ns. '
    clk.init = 0
    clk.period = period
    ht.tb_delay(clk, ~clk, period // 2, repeat=True)
    return clk

def tb_reset(when=100, duration=100):
    ' active-high reset: 0 → 1 at when ns → 0 at when+duration ns. Usage: reset <= tb_reset() '
    sig = logic_unique('tbreset')
    sig.init = 0
    ht.tb_delay(sig, 1, when,            repeat=False)
    ht.tb_delay(sig, 0, when + duration, repeat=False)
    return sig

# asynchronous stimulus
def tb_wave_async(value, when):
    '''Single or multi-point wave using relative timing. Usage: sig <= tb_wave_async(value, when)

    sig <= tb_wave_async(1, 150)
    sig <= tb_wave_async((1,0,1,0), (100,50,50,50))
    # -> value 1@100ns, 0@150ns, 1@200ns, 0@250ns
    '''
    from sc_util import max_bits_of_list, min_bits

    if isinstance(value, (list, tuple)):
        width = max(1, max_bits_of_list(value))
    else:
        width = max(1, min_bits(value))

    sig = logic_unique('tbwave[%d]' % width) if width > 1 else logic_unique('wave')
    sig.init = 0

    if isinstance(when, (list, tuple)):
        t = 0
        for v, dt in zip(value, when):
            t += dt
            ht.tb_delay(sig, v, t, repeat=False)
    else:
        ht.tb_delay(sig, value, when, repeat=False)
    return sig


# synchronous stimulus
def tb_wave_sync(clk, value, when, *, group_id=None):
    '''Single or multi-point wave triggered by clock edges. Usage: sig <= tb_wave_sync(clk, value, when)

    sig <= tb_wave_sync(clk, 1, 10)
    sig <= tb_wave_sync(clk, (1,0,1,0), (10,5,5,5))
    # -> value 1@cycle10, 0@cycle15, 1@cycle20, 0@cycle25
    '''
    from sc_util import max_bits_of_list, min_bits

    if isinstance(value, (list, tuple)):
        width = max(1, max_bits_of_list(value))
    else:
        width = max(1, min_bits(value))

    sig = logic_unique('tbsync[%d]' % width) if width > 1 else logic_unique('tbsync')
    sig.init = 0

    if isinstance(when, (list, tuple)):
        c = 0
        for v, dc in zip(value, when):
            c += dc
            ht.tb_clocked_assign(clk, sig, v, c, group_id=group_id)
    else:
        ht.tb_clocked_assign(clk, sig, value, when, group_id=group_id)
    return sig

def tb_pattern(clk, values, clock_index):
    '''Generate (data, valid) pattern stimulus.

    data, valid = tb_pattern(clk, [0xA, 0xB, 0xC], 10)
    # cycle 10: valid=1, data=0xA
    # cycle 11: valid=1, data=0xB
    # cycle 12: valid=1, data=0xC
    # cycle 13: valid=0
    '''
    from sc_util import max_bits_of_list
    assert len(values) > 0, "tb_pattern: values must not be empty"
    n     = len(values)
    width = max(1, max_bits_of_list(values))
    gid   = object()  # unique token → data and valid share one process

    data  = logic_unique('tbpat_data[%d]' % width)
    valid = logic_unique('tbpat_valid')
    data.init = 0
    valid.init = 0

    # valid: 1 for n cycles then 0
    c = 0
    for v, dc in zip(tuple([1] * n + [0]),
                     tuple([clock_index] + [1] * (n - 1) + [1])):
        c += dc
        ht.tb_clocked_assign(clk, valid, v, c, group_id=gid)

    # data: values[0..n-1]
    c = 0
    for v, dc in zip(tuple(values),
                     tuple([clock_index] + [1] * (n - 1))):
        c += dc
        ht.tb_clocked_assign(clk, data, v, c, group_id=gid)

    return data, valid

def tb_pattern_multi(clk, values, clock_index):
    '''Generate multi-signal stimulus from a list of tuples, sharing one process.

    addr, data = tb_pattern_multi(clk, [(0x10, 0xAA), (0x11, 0xBB), (0x12, 0xCC)], [10, 5, 5])
    # cycle 10: addr=0x10, data=0xAA
    # cycle 15: addr=0x11, data=0xBB
    # cycle 20: addr=0x12, data=0xCC

    clock_index: int  → [start, 1, 1, ...]  (delta, same as tb_pattern)
                 list → explicit delta list, len must equal len(values)
    '''
    from sc_util import max_bits_of_list
    assert len(values) > 0, "tb_pattern_multi: values must not be empty"
    n     = len(values)
    ncols = len(values[0])
    assert ncols > 0, "tb_pattern_multi: each row must have at least one value"
    assert all(len(row) == ncols for row in values), "tb_pattern_multi: all rows must have same length"

    if isinstance(clock_index, (list, tuple)):
        assert len(clock_index) == n, "tb_pattern_multi: clock_index list length must equal len(values)"
        deltas = list(clock_index)
    else:
        deltas = [clock_index] + [1] * (n - 1)

    gid  = object()
    sigs = []
    for col in range(ncols):
        col_vals = [row[col] for row in values]
        width    = max(1, max_bits_of_list(col_vals))
        sig      = logic_unique('tbpm[%d]' % width) if width > 1 else logic_unique('tbpm')
        sig.init = 0
        c = 0
        for v, dc in zip(col_vals, deltas):
            c += dc
            ht.tb_clocked_assign(clk, sig, v, c, group_id=gid)
        sigs.append(sig)

    return tuple(sigs)

#-------------------------------------------------------------------------
# utility functions
#-------------------------------------------------------------------------
from sc_util import min_bits, max_bits_of_list, calc_hash_value
