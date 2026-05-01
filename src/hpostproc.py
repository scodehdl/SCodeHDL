'''
    post processing 


    2016-08-03 : _set_unique_name,
    2016-09-02 : run_post_after_codegen
'''
import os,sys

import collections
from enum import Enum

import hsignal as hs
import hmodule as hm

class PostModuleInfo:
    ''
    def __init__(self,mod) :
        ''
        self.mod = mod

        self.logics_dict = collections.OrderedDict()

        # set information 
        self._set_module_info()

        # store post result
        self.mod.post = self

        # processing
        self._post_processing()                

    def _set_module_info(self):
        mod = self.mod

        # set logic information
        for k,v in mod.namespace.items():
            if isinstance(v, hs.LogicBase) : 
                self.logics_dict[k] = v

        # set destination information
        for hdl in mod.hdl_objects:
            ''
            # print(hdl, hdl.osignals)


    def _post_processing(self):
        ''
        #-------------------------------------------------------------------------
        # post processing : inout, unique name
        #-------------------------------------------------------------------------
        with hs.module_assigned_to_target(self.mod) :

            # determine the dynamic port
            _set_dynamic_port(self.mod,self)

            # outin 이름 처리  
            # output가 input으로 사용되는 경우 처리 (VHDL에서만)
            if not self.mod.verilog : 
                _output_2_input(self.mod)


            #-------------------------------------------------------------------------
            # a <= logic_unique : function return을 간략화한다. 
            #-------------------------------------------------------------------------
            # _simplify_logic_unique(self.mod)

            # unique name 처리
            _set_unique_name(self.mod,self)

            # VHDL only, for generate instance id
            if not self.mod.verilog : 
                _set_forgen_unique(self.mod)

            # statetype의 state item을 enum으로 정의한다.
            _define_statetype_enum(self.mod)


    @property
    def local_logics_dict(self) : 
        return collections.OrderedDict((k,v) for k,v in self.logics_dict.items() if v.io==None)

    @property
    def dynamic_port_dict(self) : 
        return collections.OrderedDict((k,v) for k,v in self.logics_dict.items() if v.io=='dynamic')



def run_post_processing(mod):
    ' module parsing이 끝난 후 code generation 전에 call된다. '

    # set post information
    mod.post = PostModuleInfo(mod)

    #-------------------------------------------------------------------------
    # checking 
    #-------------------------------------------------------------------------
    with hs.module_assigned_to_target(mod) :
        # check overlapped signal/port name with included module name 
        for o in mod.hdl_objects : 
            if isinstance(o, hs.IModule):
                ''
                mname = o.module.mod_name
                # assert mname not in hm.get_module_logics(mod).keys(), 'Module name[%s] overlaps with signal/port name' % mname
                assert mname not in mod.post.logics_dict.keys(), 'Module name[%s] overlaps with signal/port name' % mname

        # state item이 case에 모두 정의되었는지 check한다.
        _check_stateitem_definition(mod)

        # state type name과 logic 중복 check 
        _check_statetype_name_valid(mod)


    return mod


def run_post_after_codegen(mod):
    ' code generation 후에 call된다. '


#-------------------------------------------------------------------------
# unique name
#-------------------------------------------------------------------------
def _set_unique_name(mod,post) : 
    ''
    logic_dict = post.logics_dict  # port도 포함

    # name은 case 구분없이 check한다. (case insensitive because of VHDL)
    logic_defined = {k.lower():v for k,v in logic_dict.items() if not v.unique_defined}
    logic_unique = collections.OrderedDict((k,v) for k,v in logic_dict.items() if v.unique_defined)

    for k,v in logic_unique.items() : 

        # case 구분없이 check하기 위해 lower로 conversion 한 후 check한다. 
        if v.unique_candidate.lower() in logic_defined.keys() : 

            unique_candidate = v.unique_candidate

            # 실제 같은 logic이 다른 이름으로 사용되고 있을 수 있다.
            if id(logic_defined[unique_candidate.lower()]) != id(v) : 
                v.name = _find_unique_name(unique_candidate, logic_defined)
            else : 
                v.name = unique_candidate

        else : # change name to candidate
            v.name = v.unique_candidate

        logic_defined[v.name.lower()] = v  # update name with lower case


    # state type
    for v in mod.state_types : 
        # print(logic_defined)
        unique_candidate = v.unique_candidate

        if v.unique_defined and unique_candidate.lower() in logic_defined.keys() : 
            if id(logic_defined[unique_candidate.lower()]) != id(v) : 
                v.name = _find_unique_name(unique_candidate, logic_defined)
            else : 
                v.name = unique_candidate

        else : # change name to candidate
            v.name = unique_candidate

        # print(v,v.name,v.unique_candidate, v.unique_defined,unique_candidate.lower() in logic_defined.keys(),'*****')
        logic_defined[v.name.lower()] = v  # update name with lower case

        # check unique state items
        if v.unique_defined and (mod.verilog or (mod.vhdl and False)):  # 추후 vhdl은 조건 추가
           for item in v.state_items : 
                if item.name.lower() in logic_defined.keys() : 
                    item.name = _find_unique_name(item.name, logic_defined)

                logic_defined[item.name.lower()] = item



def _find_unique_name(name, logic_defined):
    count = 2
    while True : 
        # kname = '%s%s' % (name, count)
        kname = '%s_%s' % (name, count)  # _가 두 개 연속되면 VHDL에서 error
        if kname.lower() not in logic_defined : 
            return kname
        else : 
            count += 1

    return name

#-------------------------------------------------------------------------
# dynamic port 
#-------------------------------------------------------------------------
def _set_dynamic_port(mod,post) : 
    ''
    dyn = post.dynamic_port_dict

    onames = [s.name for s in mod.osignals if s is not None]
    inames = [s.name for s in mod.isignals if s is not None]

    for d in dyn : 
        # output이 우선 순위가 있다.
        if d in onames : 
            mod.port_out = [mod.namespace[d]]
        elif d in inames : 
            mod.port_in = [mod.namespace[d]]
        else : # delete because it was not used
            del mod.namespace[d]

#-------------------------------------------------------------------------
# outin
#-------------------------------------------------------------------------
def _output_2_input(mod):
    ' output을 input으로 사용된 경우 처리. '

    # outnames = [v.name for v in module.port_out]
    outnames = mod.outport_names

    # 중복되는 signal은 하나만 처리한다. 
    # outname에 있는 signal만 추출
    _signal_names = []
    for o in mod.hdl_objects: 
        for s in o.isignals : 
            if (not s.name in _signal_names) and (s.name in outnames) : 
                _signal_names.append(s.name)

    # outin 처리
    if 1 :             
        for sig_name in _signal_names : 

            if sig_name in outnames : 
                ' replace '
                idx = outnames.index(sig_name)
                
                sig = mod.outport_list[idx]

                # make new signal and replace
                if isinstance(sig, hs.BitVector): 
                    new_sig = hs.BitVector(name=sig.name,init=sig.init)
                elif isinstance(sig, hs.Array): 
                    new_sig = hs.Array(len(sig), sig.width, name=sig.name,init=sig.init)
                elif isinstance(sig, hs.MultiVector): 
                    new_sig = hs.MultiVector(sig.shape, name=sig.name)
                else : 
                    new_sig = hs.Vector(sig.width, name=sig.name,init=sig.init)

                new_sig.io = hs.IOport.OUTP
                mod.outport_list[idx] = new_sig


                # sig name은 module parsing 끝난 후, unique할 때까지 변경 될 수 있다.
                sig.unique_candidate = '%s_oi' % (sig.name)
                sig.name = '%s_%s' % (sig.name,hs.calc_hash_value('%s'%sig.name))
                sig.io = None   # port에서 local로 변경
                sig.unique_defined = True

                # combination assignment (new_sig <= sig)
                mod.assign(hs.SignalAssignment(new_sig, sig))

                # update namespace
                mod.namespace[sig.name] = sig
                mod.namespace[new_sig.name] = new_sig

def _check_stateitem_definition(mod) :
    ' state item이 case에 모두 정의되었는지 check한다. '
    for sl in mod.state_logics : 
        if not sl.switch_block: 
            continue

        error = False
        items = []
        for item in sl.items : 
            if item not in sl.switch_block.state_item_defined : 
                error = True
                items.append(item)

        if error : 
            assert 0, 'Error : %s not defined in case statement' % items

def _check_statetype_name_valid(mod) : 
    ''
    states = []
    for sl in mod.state_logics:
        items = [i for i in sl.items if i not in states]
        states += items

    if states : 
        # logics = hm.get_module_logic_names(mod)
        logics = mod.post.logics_dict.keys()

        error = False
        error_list = []
        for name in logics : 
            if name in states : 
                error = True
                error_list.append(name)

        if error : 
            assert 0, 'Error : %s defined multiple in logic and state type' % error_list

def _define_statetype_enum(mod):
    ' statetype을 enum으로 정의한다.'
    defined = []
    for sl in mod.state_logics:
        if id(sl) not in defined : 

            s = ','.join(it.name for it in sl.state_type.state_items)
            sl.state_type.state_enum = Enum(sl.state_type.name, s)

            defined.append(id(sl))



#-------------------------------------------------------------------------
#  _simplify_logic_unique
#  : dst가 port이면서 다른 input에 사용된 경우 outin 처리가 제대로 안 되고 있음.
#  그러므로 _simplify_logic_unique은 outin 처리가 끝난 후 call되어야 한다.
#-------------------------------------------------------------------------
# def _simplify_logic_unique(mod):
#     ''
#     for h in mod.hdl_objects : 
#         if isinstance(h, hs.CBlock) and h.is_unique_assign():
#             dst,src = h.dst, h.srcs[0]
# 
#             # dst가 logic slice인 경우 처리하지 않는다. (가독성 and 복잡해진다.)
#             if isinstance(dst,hs.LogicSlice):
#                 continue
# 
#             # destination이 portout이면 outin 처리가 된 경우에는 error 발생한다. 
#             if dst.io == hs.OUTP:
#                 continue
# 
#             # print(dst.name,dst.io,dst.unique_candidate, '<<<', src.name, src.unique_candidate)
# 
#             src.name = dst.unique_candidate
#             src.unique_defined = False
#             src.io = dst.io
# 
#             del mod.namespace[dst.name]
#             mod.remove_assignment(h.statement)
 

#-------------------------------------------------------------------------
# forgenerate 
#-------------------------------------------------------------------------
def _set_forgen_unique(mod):
    ''
    for h in mod.hdl_objects : 
        if isinstance(h,hs.ForGenerate):
            if h.gen_name in mod.post.logics_dict.keys():
                h.gen_name = _get_unique_name(h.gen_name,mod)


def _get_unique_name(name,mod):
    n = 2
    final = False
    while not final : 
        new_name = '%s_%s' % (name,n)
        if new_name not in mod.post.logics_dict.keys():
            final = True
        else:
            n += 1
    return new_name


