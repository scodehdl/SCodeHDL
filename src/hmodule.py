'''
    Module definition
    2014-05-05 
    2014-05-11 : support include() function
    2014-05-15 : module() -> imodule()
    2014-05-29 : _cvt_expr_to_signal
    2014-06-19 : 1st_run에서 signal names를 알아낸다.
    2014-07-04 : support plugin
    2014-08-13 : dictionary의 value에 있는 signal도 1st pass에서 추출한다.
    2015-09-09 : vhdl에서 vector의 range에 generic이 있으면 width가 string이 된다.
'''
from enum import Enum
import os,sys
import glob
import collections
import functools
import ast
import io
import re
import keyword
import traceback
# import inspect
import builtins
import copy
import json
from contextlib import contextmanager

import _s2
import hsignal as hs
import htestbench as ht

import parser_vhdl
import parser_verilog
import parser_common
import ast_signal,ast_exec

core_lib_code = ''

INP = hs.INP
OUTP = hs.OUTP
INOUTP = hs.INOUTP
DYNAMICP = hs.DYNAMICP


# Parser pipeline — moved to hparser.py (Phase 5)
# Re-exported here for backward compatibility (hm.parse_scfile still works)
from hparser import (
    parse_scfile,
    _transformCode,
    _core_lib_parsed,
    _exec_pre_cmd,
    _mk_module,
    _get_sc_contents,
    _1st_run_for_logic_definition,
    _exec_2nd_run,
    make_module_from_vhdl_file, make_module_from_vhdl_string,
    make_module_from_verilog_file, make_module_from_verilog_string,
    _mk_signal_port,
    _mk_lib_mod, _mk_lib_mod_sub,
    _lib_module_func, _lib_module_func_with_lib, _lib_module_check_add,
)


class HDLModule : 
    ''
    def __init__(self,module_name,*,parent=None,outdir=None,fname='',verilog=False) :
        ''
        # self.name = module_name
        self.mod_name = module_name
        self.parent = parent
        self.fname = fname  # self.basepath determined
        self.outdir = outdir if outdir else self.basepath 
        self.debug_log = False
        
        #
        self.__global_namespace = collections.OrderedDict()
        self.__local_namespace = collections.OrderedDict()
        self.__local_space_flag = 0  # 0:global, 1:local

        self.hdl_objects = []
        self.__port_in    = []
        self.__port_out   = []
        self.__port_inout = []
        self.generic_dict = collections.OrderedDict()

        self.conversion_flag = True
        self.from_scfile = True   # *.sc로 부터 만들어짐.
        self.verilog = verilog

        # 
        self.imodules = {}  # include되는 module을 저장하는 list
        self.dependent_files = []

        self.add_files = []   # simulation에서 수동으로 파일 첨부할 때 사용한다.

        self.lib_components = []  # component 선언이 불필요한 외부 라이브러리 컴포넌트

        self.state_types  = []
        self.state_logics = []

        # id management
        self._imodule_id = collections.defaultdict(int)

        # key is seed of unique name
        self._unique_id = collections.defaultdict(int)   # logic, state unique id

        # testbench
        self.tb_file_used = False

        # execute pre command
        _exec_pre_cmd(self,self.outdir)


        self._1st_flag = True

        # PostModuleInfo instance : post processing에서 정의된다.  
        # so post processing이나 code generation에서만 사용한다.
        self.post = None

        # will be used in verilog conversion
        self.forvar = []  # list of forvar (seq_flag, name)

    @property
    def vhdl(self) : return not self.verilog

    def modulename(self,mod_name):
        if self.mod_name != mod_name : 
            self.mod_name = mod_name

    @property
    def abs_fname(self) : return os.path.abspath(self.__fname)

    @property
    def fname(self) : return self.__fname
    @fname.setter
    def fname(self,value)  : 
        self.__fname = value
        self.basepath = _s2.get_basepath(self.__fname)

    @property
    def namespace(self) : return self.__global_namespace

    @namespace.setter
    def namespace(self,value)  : self.__global_namespace = value

    @contextmanager
    def unique(self) :

        self.__local_namespace = collections.OrderedDict()
        self.__local_space_flag = 1

        yield

        self.__local_space_flag = 0

        for k,v in self.__local_namespace.items() : 
            if v is None : 
                del self.namespace[k]
            else : # overwrite
                self.namespace[k] = v

    def isTestbench(self) :
        return len(self.port_list) == 0

    def _add_obj(self,o):
        o.id = len(self.hdl_objects)
        self.hdl_objects.append(o)

    def is_1st_run(self) : return self._1st_flag
    def is_2nd_run(self) : return not self._1st_flag

    def set_1st_run(self,_1st_flag):
        self._1st_flag = _1st_flag

    # cblock으로 만들어 append
    def assign(self,statement)  : 
        if type(statement) is hs.SignalAssignment:
            # assert len(statement.values) == len(statement.conditions)+1, 'number of values is shoand conditions should be equal in combinational circuit, expected %s' % (len(statement.conditions)+1)
            assert len(statement.values) == len(statement.conditions) + 1, \
    f"Combinational circuit: The number of values " \
    f"must be exactly one more than the number of conditions. \nExpected number of values is {len(statement.conditions)+1}."

        cb = hs.CBlock(statement,parent=self) 
        self._add_obj(cb)
        return cb

    def remove_assignment(self, statement):
        ' remove assignment statement '
        for i,o in enumerate(self.hdl_objects) : 
            if isinstance(o,hs.CBlock) : 
                if id(o.statement) == id(statement):  
                    self.hdl_objects.pop(i)
            else : 
                o.remove_assignment(statement)

    def get_assignment(self):
        assigns = []
        for o in self.hdl_objects : 
            assigns += o.get_assignment()
        return assigns


    @property
    def port_list(self) : 
        return self.__port_in + self.__port_out + self.__port_inout

    @property
    def inport_list(self) : return self.__port_in

    @inport_list.setter
    def inport_list(self,value)  : self.__port_in = value

    @property
    def outport_list(self) : return self.__port_out

    @outport_list.setter
    def outport_list(self,value)  : self.__port_out = value

    @property
    def inoutport_list(self) : return self.__port_inout

    @inoutport_list.setter
    def inoutport_list(self,value)  : self.__port_inout = value

    @property
    def port_names(self): return [p.name for p in self.port_list]

    @property
    def inport_names(self): return [p.name for p in self.inport_list]

    @property
    def outport_names(self): return [p.name for p in self.outport_list]

    @property
    def inoutport_names(self): return [p.name for p in self.inoutport_list]

    def get_outport_with_name(self,name):
        for p in self.outport_list : 
            if p.name == name : 
                return p
        return None

    # port i/o setting
    def inport(self,*p):
        _port_in = self._cvt_str_2_ports(p,INP)
        self.__port_in +=_port_in

    def outport(self,*p,init=hs.NAN):
        _port_out = self._cvt_str_2_ports(p,OUTP,init=init)
        self.__port_out += _port_out

    def inoutport(self,*p,init=hs.NAN):
        _port_inout = self._cvt_str_2_ports(p,INOUTP,init=init)
        self.__port_inout += _port_inout

    def dynport(self,*logic_group):
        ''
        for s in logic_group :
            s.io = DYNAMICP

    def hash_name(self,name) : 
        ' kind : logic or state '
        key_name = name

        _id = self._unique_id[key_name]
        h_name = hs.calc_hash_value('%s_%s' % (key_name,_id))

        self._unique_id[key_name] += 1
        return h_name

    def logic_define(self,s:str,*,sig_type=hs.SigType.logic,init=hs.NAN):
        ' helper function of logic definition '
        # new_sig = self._logic_define(s,sig_type,False,init=init)

        if self.__local_space_flag :
            new_sig = self._unique_define(s,sig_type,False,init=init)
        else : # normal
            new_sig = self._logic_define(s,sig_type,False,init=init)
        return new_sig

    def logic_unique_define(self,s : str,sig_type=hs.SigType.logic,*,init=hs.NAN):
        ' unique signal : 주어진 이름에 id를 붙여 unique한 이름을 만든다.'
        return self._unique_define(s,sig_type,False,init=init)


    def array_define(self,s:str,*,sig_type=hs.SigType.logic,init=hs.NAN):
        # new_sig = self._logic_define(s,sig_type,True,init=init)
        if self.__local_space_flag :
            new_sig = self._unique_define(s,sig_type,True,init=init)
        else : # normal
            new_sig = self._logic_define(s,sig_type,True,init=init)

        assert isinstance(new_sig, hs.Array)
        return new_sig

    def array_unique_define(self,s,*,sig_type=hs.SigType.logic,init=None):
        ''
        sig = self._unique_define(s,sig_type,True,init=init)
        return sig

    def _add_local_space(self,sig): # save to local namespace
        name = sig.name
        if name in self.namespace.keys() :
            self.__local_namespace[name] = self.namespace[name]
        else : 
            self.__local_namespace[name] = None

    def logic_2_namespace(self,sig):  # add
        self.namespace[sig.name] = sig

        if self.__local_space_flag :
            self._add_local_space(sig)

    def _unique_define(self,s,sig_type,array_flag,init=hs.NAN):
        # 이름을 추출하여 hash를 추가한다. 
        # # abc[a] : 최초의 word가 group(1)이 된다. 

        o = re.search( r"(\w*)(.*)", s)   

        name = o.group(1)
        new_s = '%s_%s%s' % (name,self.hash_name(name),o.group(2))

        sig = self._logic_define(new_s,sig_type,array_flag,init=init,unique=True)

        # parsing후에 최종 이름 결정된다. 
        sig.name = name
        sig.unique_defined = True
        sig.unique_candidate = name

        if self.__local_space_flag :
            self._add_local_space(sig)
            self.namespace[name] = sig
        return sig

    def _logic_define(self,name_str,sig_type,array_flag=False,init=hs.NAN,*,unique=False):
        ''
        sig = self._cvt_str_2_sub(name_str,array_flag)
        sig.sig_type = sig_type
        if not _s2.check_nan(init) :
            sig.init = init

        if not unique : # unique이면 이름으로 사용 못하고, instance로 사용하게 된다.
            self.namespace[sig.name] = sig

        return sig


    def _cvt_str_2_ports(self,io_tuple,io_type,init=hs.NAN):
        ' io_tuple : "a", "b" '
        io_list = []

        if io_tuple=='':
            return io_list

        if not _s2.check_nan(init) and len(io_tuple) > 1:
            raise ValueError('init cannot be used with multiple ports - use a separate call for each port with init')

        for i,p in enumerate(io_tuple) :
            if not p : continue

            assert type(p) == str

            sig = self._cvt_str_2_sub(p,False)
            sig.io = io_type
            if not _s2.check_nan(init):
                sig.init = init
            io_list.append(sig)

        return io_list

    def _exec_code(self,code_s,namespace):  # code_s : str or ast.parsed
        code = compile(code_s,'','exec')
        exec(code , namespace)

    def _cvt_str_2_sub(self, io_str, array_flag=False):
        '''Parse a signal spec string and create (or look up) the signal object.

        io_str is a signal spec such as "clk", "data[8]", "bus[15:0]".
        parser_common.str2signals() converts it to executable Python code, e.g.:
            "data[8]"  ->  "data = hs.Vector(8, name='data')"
        That code is exec'd into the module namespace so the signal becomes
        accessible by name.

        On the 1st pass the signal is always (re-)created to establish its type.
        On the 2nd pass an existing entry is kept unchanged — the 1st pass
        already set up the correct object and we just need to return a reference.
        '''
        assert type(io_str) == str

        code, sig_name = parser_common.str2signals(io_str, array_flag)

        # check name in python keywords
        assert sig_name not in keyword.kwlist, '[%s] is reserved words, so cannot be used in signal name' % sig_name

        if self._1st_flag :
            self._exec_code(code, self.namespace)
        else :  # 2nd run, don't update if exist
            if sig_name not in self.namespace.keys() :
                self._exec_code(code, self.namespace)

        return self.namespace[sig_name]

    def _enum_state(self,name,str_list):
        num = 0
        enum_list = []

        for item in str_list :  
            if item.find(':=') == -1 : 
                enum_list.append([item,num])
            else: 
                name, num = item.split(':')
                num = eval(num)
                enum_list.append([name,num])

            num += 1

        state_enum = Enum(name,enum_list)
        return state_enum

    #-------------------------------------------------------------------------
    # state type
    #-------------------------------------------------------------------------
    def statetype_define(self,statetype_name,*states,encoding='binary',unique=False):
        ''
        if len(states) == 0:
            state_enum = []
        elif len(states) == 1 and isinstance(states[0], (tuple, list)):
            # 기존 호환: statetype("name", ("a","b","c")) — Enum starts at 1
            state_enum = Enum(statetype_name, states[0])
        elif len(states) == 1 and isinstance(states[0], str) and ' ' in states[0]:
            # 기존 호환: statetype("name", "a b c")
            state_enum = _s2.enum_from_str(statetype_name, states[0])
        else:
            # 새 방식: statetype(name, a, b, c) → 각각 string
            state_enum = _s2.enum_from_str(statetype_name, ' '.join(states))

        stype = hs.StateType(state_enum,name=statetype_name,encoding=encoding,unique=unique)
        self.namespace[stype.name] = stype 

        # add
        self.state_types.append(stype)
        return stype

    def statetype_unique_define(self,statetype_name,states_str,encoding='binary'):
        return self.statetype_define(statetype_name,states_str,encoding=encoding,unique=True)

    #-------------------------------------------------------------------------
    # state logic
    #-------------------------------------------------------------------------
    def statelogic_define(self,slogic_name:str,stype,unique=False):
        ''
        slogic = hs.StateLogic(stype, name=slogic_name)
        slogic.unique_candidate = slogic_name

        if unique : 
            slogic.name = '%s_%s' % (slogic_name,self.hash_name(slogic_name)) 
            slogic.unique_defined = True

        # add to namespace
        self.namespace[slogic.name] = slogic 
        self.state_logics.append(slogic)
        return slogic

    def statelogic_unique_define(self,slogic_name,stype):
        return self.statelogic_define(slogic_name,stype,unique=True)


    #-------------------------------------------------------------------------
    def _check_dependency_exists(self,fname):
        fn = os.path.normcase(fname)
        if fn in self.dependent_files : 
            return True
        else : 
            return False

    def _add_dependency(self,fname):
        fn = os.path.normcase(fname)
        if fn not in self.dependent_files : 
            self.dependent_files.append(fn)
    
    def include(self,fname):
        
        fn = os.path.abspath(os.path.join(self.basepath,fname))
        if os.path.exists(fn):
            fname = fn
        else : 
            # 없으면 rootdir, user lib, default lib순으로 찾는다.
            fname = _s2.get_include_file(fname)
        
        if self._check_dependency_exists(fname):
            return 

        #
        self._add_dependency(fname)

        with open(fname, "r",encoding='latin-1') as f:
            parsed = _transformCode(f.read())

            code = compile(parsed, fname, 'exec')
            exec(code , self.namespace)

    def generic(self,**kwargs):
        self.generic_dict = _s2.odict()
        for key,value in kwargs.items() : 
            gvar = hs.GenericVar(key,value) 
            self.generic_dict[key] = gvar

        self.namespace.update(self.generic_dict)

    def _mk_imodule(self,fname):
        ''
        # parse file
        ext = os.path.splitext(fname)[1] 
        if ext in ['.sc'] :
            mod = _1st_run_for_logic_definition(fname,parent=self,outdir=self.outdir)
        elif ext in ['.v'] :
            mod = make_module_from_verilog_file(fname,parent=self)
        else : # vhdl
            mod = make_module_from_vhdl_file(fname,parent=self)
        return mod

    def _imodule_file_path(self,fname):
        # check filename 
        assert type(fname)==str , '%s should be file name' % fname

        fname = os.path.join(self.basepath,fname)

        ext = os.path.splitext(fname)[1] 
        assert ext in ['.vhd', '.vhdl','.v', '.sc']

        _s2.debug_view('imodule :', fname)
        return fname

    def testbench(self,fname):
        ''
        _s2.debug_view('testbench :', fname)
        fname = self._imodule_file_path(fname)

        mod = self._mk_imodule(fname)

        # port list을 namespace에 저장, init 정의는 모두 없앤다.
        for k in mod.port_list :
            k.init = hs.NAN
            self.namespace[k.name] = k

        # add with IModule
        kwargs = {k.name:k for k in mod.port_list}
        self._add_obj(hs.IModule(mod,(),kwargs,parent=self))

        self.imodules[fname] = mod

        return mod

    def _get_mod_by_name(self,name):
        ' Get module by name. If not exist in imodules, add it '
        if name not in self.imodules :  
            mod = self._mk_imodule(name)
            self.imodules[name] = mod
        else : 
            mod = self.imodules[name]

            # generic이 존재하는 module인 경우 generic에 의해 
            # port information이 변경 가능하므로 copy한다. 
            if len(mod.generic_dict) > 0 : 
                mod = self._mk_imodule(name)

        return mod


    def imodule(self,mod_fname,**kwargs):
        ' kwargs만 지원한다 (2016-08-11) '
        args = ()

        fname = self._imodule_file_path(mod_fname)


        if self._1st_flag : 
            if any(isinstance(kwargs[k],hs.SignalUnspecified) for k in kwargs):
                mod = self._get_mod_by_name(fname)
                self._imodule_auto_define(mod,kwargs)
            # return

        if self.debug_log :
            _s2.debug_view('[%s] => args:%s, kwargs:%s' % (fname,args,kwargs))

        mod = self._get_mod_by_name(fname)
        kwargs = self._cvt_expr_to_signal(kwargs)
        self.imodule_check_add(mod, args, kwargs)

        return mod            

    def _cvt_expr_to_signal(self,kwargs):
        ''
        # keywords argument가 expression으로 확장될 때, signal이 정의 될 수 있다. 
        # signal의 정의 순서를 일정하게 하기 위해서 key를 sorting한 후 처리한다.

        new_kwargs = {}
        for k in sorted(kwargs.keys()) : 
            v = kwargs[k]

            candidate_name = k
            if isinstance(v,(hs.VectorCombine,hs.ArithmeticOperator)):
                ' concat(a,b)를 임시 signal 만든 후 교체한다. '
                # sig = self.logic_unique_define("logic_x[%s]"%v.width)
                sig = self.logic_unique_define("%s[%s]"%(candidate_name,v.width))
                sig <= v
                v = sig
            elif isinstance(v,hs.InvertOperator) and v.op1.islogic() :
                sig = self.logic_unique_define(candidate_name)
                sig <= v
                v = sig
            # elif isinstance(v,hs.ComparisonOperator):
            elif isinstance(v,(hs.ComparisonOperator,hs.BooleanOperator)):
                sig = self.logic_unique_define(candidate_name)
                sig <= (1,v,0)
                v = sig



            new_kwargs[k] = v

        return new_kwargs 

    def _imodule_auto_define(self,mod,kwargs):
        ''
        if any(isinstance(kwargs[k],hs.SignalUnspecified) for k in kwargs):

            out_list = [p.name for p in mod.outport_list]  

            for k in kwargs : # kwargs는 mod의 port name을 나타낸다.
                src = kwargs[k]  # src는 imodule에 전달되는 argument이다.
                if isinstance(src,hs.SignalUnspecified) :
                    if k in out_list :
                        p = mod.get_outport_with_name(k)
                        name = src.name
                        self.namespace[name] = hs.copy_logic_like(self,name,p)
        return 

    def imodule_check_add(self, mod, args, kwargs):
        ' parameter checking하고 옳은 경우 IModule object add한다. '

        # id 관리 (module의 name별로 따로 관리한다.)
        uut_id = self._imodule_id[mod.mod_name]
        self._imodule_id[mod.mod_name] += 1

        assert(len(args)==0),'can not use positional and keyword arguments'

        # check all input exists in kwargs
        inport_exist = [n for n in mod.inport_names + mod.inoutport_names if n not in kwargs]
        assert len(inport_exist)==0, '%s should exist in keywords list' % inport_exist

        # set None if output not exist
        outport_exist = [n for n in mod.outport_names if n not in kwargs]
        if len(outport_exist) > 0 : 
            for o in outport_exist : 
                kwargs[o] = None

        # outport value는 none이거나 logic이어야만 한다.
        for k,v in kwargs.items() : 
            if k in mod.outport_names and v is not None and not isinstance(v, (hs.LogicBase,hs.LogicSlice)) : 
                assert 0, 'outport[%s] should be logic, not %s' % (k,v)


        # 입력된 keyword가 port or generic에 있어야 한다. 또한 port인 경우 string type이 아니어야 한다.
        for k in kwargs : 
            if k in mod.port_names:
                assert type(kwargs[k]) is not str, 'String type(%s) cannot be used in connection value ' % kwargs[k]

            if k in mod.port_names or k in mod.generic_dict.keys() : 
                continue
            else : 
                assert 0, '[%s] not found in module connection' % k

        # 
        port_keywords    = {k:kwargs[k] for k in kwargs if k in mod.port_names}
        generic_keywords = {k:kwargs[k] for k in kwargs if k in mod.generic_dict.keys()}
        assert len(port_keywords) == len(mod.port_list), '%s => %s(given) : %s(ports)' % (mod.mod_name,len(port_keywords),len(mod.port_list))

        # generic_keywords이 존재하면, 주어진 값에 의해 module port의 port width를 다시 결정한다.
        self._modify_port_width(generic_keywords,mod)

        # make IModule and add
        sb = hs.IModule(mod,args,port_keywords,parent=self,generic_kwargs=generic_keywords,
                        debug_log=self.debug_log,uut_id=uut_id)
        self._add_obj(sb)

    def _modify_port_width(self,generic_keywords,module):
        ''
        for key in generic_keywords : 
            ''
            # print(key)
            for p in module.port_list : 
                if isinstance(p, hs.Vector) and len(p.hdl_width_dict) > 0 : 
                    p.width = parser_common.getVectorWidth(p.hdl_width_dict,generic_keywords)

    def modulewrapper(self,name,i,o,io,gen):
        mod = _mk_lib_mod(self,name,i,o,io,gen)
        return mod

    def rawcode_decl(self,code,*, olist=[],ilist=[]) : 
        ' architecture declaration part에 들어간다. '
        o = hs.RawCodeDecl(code,sig_olist=olist,sig_ilist=ilist)
        self._add_obj(o)

    def rawcode(self,code,*, olist=[],ilist=[]) : 
        o = hs.RawCode(code,sig_olist=olist,sig_ilist=ilist)
        self._add_obj(o)

    def rawcode_lib(self,code):
        o = hs.LibraryDecl(code)
        self._add_obj(o)

    def blankline(self,n=1):
        o = hs.BlankLine(n)
        self._add_obj(o)

    def forgen_block(self,name,start,stop) :
        ''
        sb = hs.ForGenerate(name,start,stop,parent=self)
        self._add_obj(sb)
        return sb

    def sequence_block(self,clk,*,arst=None,srst=None,edge='rising') :
        ''
        if srst : 
            _reset = srst
            rst_type = 'sync'
        elif arst :  # asynchronous 
            _reset = arst
            rst_type = 'async'
        else : 
            _reset = None
            rst_type = None

        sb = hs.SeqBlock(clk,_reset,reset_type=rst_type,parent=self,edge=edge)
        self._add_obj(sb)
        return sb

    def switch(self,case_sig) :
        'combinational switch이다.'
        sb = hs.SwitchAssignment(case_sig,parent=self)
        self._add_obj(sb)
        return sb



    @property
    def isignals(self) : 
        ot = []
        for o in self.hdl_objects :
            ot += o.isignals
        return ot

    @property
    def osignals(self) : 
        ''
        ot = []
        for o in self.hdl_objects :
            ot += o.osignals
        return ot


    def delete_module_logic_unique(self):
        ''
        # for k,v in self.namespace.items():
        #     if isinstance(v, hs.LogicBase) and v.unique_defined : 
        #         del self.namespace[k]

        # python 3.7에서 error 발생 : RuntimeError: OrderedDict mutated during iteration                
        # namespace에서 바로 지우지 않고, 나중에 지우는 방식으로 변경 (2019/8/8)
        key_deleted = []
        for k,v in self.namespace.items():
            if isinstance(v, hs.LogicBase) and v.unique_defined : 
                key_deleted.append(k)

        for k in key_deleted : 
            del self.namespace[k]
                


    def delete_module_statesignal(self):
        key_deleted = []
        for k,v in self.namespace.items():
            if isinstance(v, (hs.StateType,hs.StateLogic)) and v.unique_defined  : 
                # del self.namespace[k]
                key_deleted.append(k)

        for k in key_deleted : 
            del self.namespace[k]


class VHDLModule(HDLModule):
    ''
class VerilogModule(HDLModule):
    ''




#-------------------------------------------------------------------------
#  
#-------------------------------------------------------------------------
