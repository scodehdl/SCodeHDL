'''
    HDL structure objects: blocks, generates, modules
    Extracted from hsignal.py (Phase 5 slim-down)
'''
import collections
import _s2

# hsignal is imported lazily here to avoid circular import.
# All signal/expression classes are accessed via hs.XXX inside method bodies.
import hsignal as hs


#-------------------------------------------------------------------------
# HDLObject base
#-------------------------------------------------------------------------
class HDLObject :
    inst_id = 0

    def __init__(self) :
        HDLObject.inst_id += 1

    @property
    def osignals(self)       : raise NotImplementedError

    @property
    def isignals(self)       : raise NotImplementedError

    @property
    def variables(self) : raise NotImplementedError

    def remove_assignment(self,statement): pass
    def get_assignment(self): return []

class BlankLine(HDLObject):
    ''
    def __init__(self,n=1):
        ''
        super().__init__()
        self.blank_line_num = n

    @property
    def osignals(self) : return []

    @property
    def isignals(self) : return []

    @property
    def variables(self) : return []


class RawCode(HDLObject):
    ''
    def __init__(self,code,sig_olist=[],sig_ilist=[]) :
        ''
        super().__init__()
        self.code = code
        self.sig_olist = sig_olist
        self.sig_ilist = sig_ilist

    @property
    def osignals(self) : return self.sig_olist

    @property
    def isignals(self) : return self.sig_ilist

    @property
    def variables(self) : return []


class RawCodeDecl(RawCode):
    ''

class LibraryDecl(HDLObject):
    ''
    def __init__(self,code) :
        super().__init__()
        self.code = code

    @property
    def osignals(self) : return []

    @property
    def isignals(self) : return []

    @property
    def variables(self) : return []


#-------------------------------------------------------------------------
# IModule : included (instantiated) module
#-------------------------------------------------------------------------
class IModule(HDLObject):
    ' included module '
    _uut_id = 0

    def __init__(self,module,args,port_kwargs,*,uut_id=None,generic_kwargs=None,parent=None,debug_log=False) :
        super().__init__()
        self.module = module
        self.parent = parent
        self.debug_log = debug_log

        if len(args) == 0 :
            self._set_connection_keyword(port_kwargs)
        else :
            self._set_connection_positional(args)

        self._cvt_argument_type()

        self.connection_generic = generic_kwargs

        self._port_in_names    = [p.name for p in self.module.inport_list]
        self._port_out_names   = [p.name for p in self.module.outport_list]
        self._port_inout_names = [p.name for p in self.module.inoutport_list]

        self.uut_id = uut_id if uut_id is not None else IModule._uut_id
        IModule._uut_id += 1

        self._set_wire_reg()

    @classmethod
    def get_uut_id(cls) :
        return IModule._uut_id

    @classmethod
    def set_uut_id(cls,value) :
        IModule._uut_id = value

    def _set_connection_positional(self, args):
        ''
        self.connection_dict = collections.OrderedDict()
        for port,arg in zip(self.module.port_list,args) :
            self.connection_dict[port] = arg

    def _set_connection_keyword(self, connection_dict_):
        ''
        self.connection_dict = collections.OrderedDict()

        for k in self.module.port_list :
            if k.name in connection_dict_ :
                self.connection_dict[k] = connection_dict_[k.name]
            else :
                assert 0, 'port [%s] not found in connection' % k.name

        if self.debug_log :
            _s2.debug_view('---------------------------------------------------')
            _s2.debug_view(self.module.fname)
            _s2.debug_view('---------------------------------------------------')

            for c in self.connection_dict :
                if isinstance(self.connection_dict[c], hs.VectorCombine):
                    k = self.connection_dict[c]
                elif isinstance(self.connection_dict[c], hs.LogicBase):
                    k = self.connection_dict[c].name
                else :
                    k = self.connection_dict[c]
                _s2.debug_view(c.name, '==>', k)

    def _cvt_argument_type(self) :
        for port in self.module.port_list :
            arg = self.connection_dict[port]

            if isinstance(port.width, hs.GenericVar) :
                continue

            logic_name = port.name

            if isinstance(arg,(hs.LogicBase,hs.LogicSlice,hs.SignalConstant)) and port.total_bits > arg.total_bits :
                rem = port.width - arg.width

                new_sig = hs.get_module().logic_unique_define("%s[%s]" % (logic_name,port.width))
                self.connection_dict[port] = new_sig

                if port.io == hs.IOport.INP :
                    concat_sig = hs.VectorCombine(hs.SignalConstant(value=0,width=rem),arg)
                    new_sig <= concat_sig
                else :
                    arg <= new_sig[arg.width-1:0]

            if isinstance(port,hs.Vector) and port.width == 1 and isinstance(arg,(hs.BitVector,hs.LogicSlice)) and arg.width == 1 :
                new_sig = hs.get_module().logic_unique_define("%s[1]" % logic_name)
                new_sig[0] <= arg
                self.connection_dict[port] = new_sig

            if isinstance(port,hs.BitVector) and isinstance(arg,hs.Vector) and arg.width == 1 :
                new_sig = hs.get_module().logic_unique_define("%s" % logic_name)
                new_sig <= arg[0]
                self.connection_dict[port] = new_sig

    @property
    def port_list(self) :
        return self.module.port_list

    @property
    def osignals(self) :
        pout = self.module.outport_list + self.module.inoutport_list
        return [self.connection_dict[k].base for k in pout if isinstance(self.connection_dict[k], hs.LogicMixin)]

    @property
    def isignals(self) :
        pout = self.module.inport_list + self.module.inoutport_list
        return [self.connection_dict[k].base for k in pout if isinstance(self.connection_dict[k], hs.LogicMixin)]

    @property
    def variables(self) : return []

    def _set_wire_reg(self):
        ' module의 output은 사용하는 곳에서는 wire로 선언된다. '
        for k in self.module.outport_list + self.module.inoutport_list :
            p = self.connection_dict[k]
            if p and isinstance(p.width, hs.GenericVar):
                continue
            if p :
                self.connection_dict[k].reg_wire = 0

    def replace_sim_module(self,mod):
        conn_dict = {k.name:v for k,v in self.connection_dict.items()}
        self.module = mod
        for k in mod.port_list :
            self.connection_dict[k] = conn_dict[k.name]


#-------------------------------------------------------------------------
# CBlock : combinational block
#-------------------------------------------------------------------------
class CBlock(HDLObject) :
    ''
    def __init__(self,statement,*,parent=None) :
        ''
        super().__init__()
        self.statement = statement
        self.parent = parent

        self.statement.dst.reg_wire = 0

    @property
    def osignals(self) :  return self.statement.osignals

    @property
    def isignals(self) :  return self.statement.isignals

    @property
    def variables(self) : return []

    def get_assignment(self): return [self.statement]

    @property
    def dst(self) : return self.statement.dst

    @property
    def srcs(self) : return self.statement.srcs

    def is_simple_assign(self):
        return self.statement.is_simple_assign()

    def is_unique_assign(self):
        if self.statement.is_simple_assign() :
            dst = self.statement.dst
            src = self.statement.srcs[0]
            return not dst.unique_defined and src.unique_defined
        else:
            return False


#-------------------------------------------------------------------------
# ForGenerate
#-------------------------------------------------------------------------
class ForGenerate(HDLObject):
    ''
    _gen_id = 0

    def __init__(self,var_name:str,start,stop,*,parent=None) :
        ''
        super().__init__()

        self.seq_flag = 0 if parent == hs.get_module() else 1
        self.for_var = hs.ForVariable(var_name, self.seq_flag)

        self.start = start
        self.stop  = stop

        self.objects = []

        self.gen_id   = ForGenerate._gen_id
        self.gen_name = 'g_%s' % self.gen_id

        ForGenerate._gen_id += 1

    def _io_signals(self, kind='o'):
        signal_list = []
        for o in self.objects:
            if kind=='o':
                signal_list += o.osignals
            elif kind=='i':
                signal_list += o.isignals
        return _s2.remove_same_item(signal_list)

    @property
    def osignals(self) :  return self._io_signals('o')

    @property
    def isignals(self) :  return self._io_signals('i')

    @property
    def variables(self) : return []

    def assign(self,o):
        if not self.seq_flag:
            o.dst.reg_wire = 0
        self.objects.append(o)

    def __enter__(self):
        ''
        self.at_saved = hs.get_assign_target()
        hs.set_assign_target(self)

        name = self.for_var.name
        mod  = hs.get_module()

        if name in mod.namespace.keys() :
            self.save_var = mod.namespace[name]
        else :
            self.save_var = None

        mod.namespace[name] = self.for_var
        return self

    def __exit__(self, type, value, traceback):
        ''
        if self.save_var :
            hs.get_module().namespace[self.for_var.name] = self.save_var
        hs.set_assign_target(self.at_saved)


#-------------------------------------------------------------------------
# helpers used by IfBlock / SwitchBlock / SeqBlock
#-------------------------------------------------------------------------
def _condition2ActiveHigh(sig) :
    'condition이 아닌 logic으로 입력된 경우 active high로 변경한다.'
    if isinstance(sig, hs.SignalUnspecified):
        sig = hs.EqExpr(sig, hs.SignalConstant(1,1))
    elif isinstance(sig, (hs.LogicBase, hs.LogicSlice)):
        sig = hs.EqExpr(sig, hs.SignalConstant(1,1))
    elif isinstance(sig, hs.BooleanOperator):
        for i,op in enumerate(sig.operands) :
            sig.operands[i] = _condition2ActiveHigh(op)
    elif isinstance(sig, hs.InvertOperator):
        sig = hs.InvertOperator(_condition2ActiveHigh(sig.op1))
    return sig

def _remove_assignment(objects,statement):
    for i,o in enumerate(objects) :
        if isinstance(o, hs.SignalAssignment) :
            if id(o) == id(statement):
                objects.pop(i)
        else :
            o.remove_assignment(statement)

def _get_assignment(objects):
    assigns = []
    for o in objects :
        if isinstance(o, hs.SignalAssignment) :
            assigns.append(o)
        else :
            assigns += o.get_assignment()
    return assigns


#-------------------------------------------------------------------------
# IfBlock
#-------------------------------------------------------------------------
class IfBlock:
    ' if/elif/else를 구현한다. '
    def __init__(self,*,parent=None) :
        ''
        super().__init__()
        self.parent = parent
        self.conditions = collections.OrderedDict()

    def _add_if(self,condition):
        objects = []
        self.conditions[condition] = objects
        return IfBlockCondition(objects,parent=self)

    def _check_bool_condition(self, condition):
        if isinstance(condition, bool):
            raise TypeError(
                "Python bool cannot be used directly as an HDL if-condition.\n"
                "Use pycond(...) to evaluate at elaboration time:\n"
                "    if pycond(%s):" % condition
            )

    def If(self, condition):
        self._check_bool_condition(condition)
        condition = _condition2ActiveHigh(condition)
        return self._add_if(condition)

    def Elif(self, condition):
        self._check_bool_condition(condition)
        condition = _condition2ActiveHigh(condition)
        return self._add_if(condition)

    def Else(self): return self._add_if(hs.AllTrue())

    def __enter__(self):
        self.at_saved = hs.get_assign_target()
        hs.set_assign_target(self)
        return self

    def __exit__(self, type, value, traceback):
        ''
        hs.set_assign_target(self.at_saved)

    def _io_signals(self, kind='o'):
        signal_list = []
        for c in self.conditions :
            if kind=='i':
                signal_list += c.isignals
            for o in self.conditions[c] :
                if kind=='o':
                    signal_list += o.osignals
                elif kind=='i':
                    signal_list += o.isignals
        return _s2.remove_same_item(signal_list)

    @property
    def osignals(self) : return self._io_signals('o')

    @property
    def isignals(self) : return self._io_signals('i')

    @property
    def variables(self) :
        v_list = []
        for c in self.conditions :
            for o in self.conditions[c] :
                v_list += o.variables
        return _s2.remove_same_item(v_list)

    def remove_assignment(self,statement):
        for objects in self.conditions.values():
            _remove_assignment(objects, statement)

    def get_assignment(self):
        assigns = []
        for objects in self.conditions.values():
            assigns += _get_assignment(objects)
        return assigns


class IfBlockCondition :
    ''
    def __init__(self,objects,*,parent) :
        ''
        self.parent  = parent
        self.objects = objects

    def assign(self,s):
        self.objects.append(s)

    def remove_assignment(self,s):
        for i,o in enumerate(self.objects) :
            if isinstance(o, hs.SignalAssignment) :
                if id(o) == id(s):
                    self.objects.pop(i)

    def get_assignment(self): return _get_assignment(self.objects)

    def switch(self,case_sig):
        ib = SwitchBlock(case_sig, parent=self)
        self.objects.append(ib)
        return ib

    def ifblock(self):
        ib = IfBlock(parent=self)
        self.objects.append(ib)
        return ib

    def __enter__(self):
        ''
        self.at_saved = hs.get_assign_target()
        hs.set_assign_target(self)
        return self

    def __exit__(self, type, value, traceback):
        ''
        hs.set_assign_target(self.at_saved)


#-------------------------------------------------------------------------
# SwitchBlock / CaseCondition
#-------------------------------------------------------------------------
class SwitchBlock:
    ''
    def __init__(self,case_sig,*,parent=None) :
        ''
        super().__init__()
        self.case_sig = case_sig
        self.parent   = parent
        self.state_item_defined = []
        self.conditions = collections.OrderedDict()

    def _add_case(self,condition):
        objects = []
        self.conditions[condition] = objects
        return CaseCondition(objects, parent=self)

    def case(self,value) :
        if isinstance(self.case_sig, hs.StateLogic) :
            self.state_item_defined.append(value.name)
        return self._add_case(hs.EqExpr(self.case_sig,value))

    def others(self) :
        return self._add_case(hs.AllTrue())

    def __enter__(self):
        ''
        self.at_saved = hs.get_assign_target()
        hs.set_assign_target(self)
        return self

    def __exit__(self, type, value, traceback):
        ''
        hs.set_assign_target(self.at_saved)

        if isinstance(self.case_sig, hs.StateLogic) :
            self.case_sig.switch_block = self

    def _io_signals(self, kind='o'):
        signal_list = []
        for c in self.conditions :
            for o in self.conditions[c] :
                if kind=='o':
                    signal_list += o.osignals
                elif kind=='i':
                    signal_list += o.isignals
        return _s2.remove_same_item(signal_list)

    @property
    def osignals(self) : return self._io_signals('o')

    @property
    def isignals(self) : return self._io_signals('i')

    @property
    def variables(self) :
        v_list = []
        for c in self.conditions :
            for o in self.conditions[c] :
                v_list += o.variables
        return _s2.remove_same_item(v_list)

    def remove_assignment(self,statement):
        for objects in self.conditions.values():
            _remove_assignment(objects, statement)

    def get_assignment(self):
        assigns = []
        for objects in self.conditions.values():
            assigns += _get_assignment(objects)
        return assigns


class CaseCondition :
    ' switchBlock에서 case,other에 의해 이용된다. '
    def __init__(self,objects,*,parent) :
        ''
        self.parent  = parent
        self.objects = objects

    def assign(self,s):
        self.objects.append(s)

    def ifblock(self):
        ib = IfBlock(parent=self)
        self.objects.append(ib)
        return ib

    def __enter__(self):
        self.at_saved = hs.get_assign_target()
        hs.set_assign_target(self)
        return self

    def __exit__(self, type, value, traceback):
        hs.set_assign_target(self.at_saved)

    def remove_assignment(self,statement):
        for i,o in enumerate(self.objects) :
            if id(o.statement) == id(statement):
                self.objects.pop(i)

    def get_assignment(self): return _get_assignment(self.objects)


class SwitchAssignment(SwitchBlock):
    ''


#-------------------------------------------------------------------------
# SeqBlock : sequential (clock-edge) block
#-------------------------------------------------------------------------
def _verilog_chg_reset(mod,sb):
    ''
    assert sb.reset_type == 'async'

    if isinstance(sb.reset, hs.ComparisonOperator) and sb.reset.issimple():
        return

    arst = mod.logic_unique_define("arst")
    arst_statement = (arst <= (1, sb.reset, 0))
    sb.reset = arst


class SeqBlock(HDLObject):
    ''
    def __init__(self,clk,reset=None,*,reset_type='sync',parent=None,edge='rising') :
        ' clock edge : rising (default), falling'
        super().__init__()

        self.clk        = clk
        self.reset      = reset
        self.reset_type = reset_type
        self.parent     = parent
        self.clk_edge   = edge

        self.objects = []

        if isinstance(reset, (hs.LogicBase, hs.LogicSlice, hs.LogicExpr)):
            self.reset = _condition2ActiveHigh(reset)

            if parent.verilog and reset_type == 'async':
                _verilog_chg_reset(parent,self)
        else:
            assert reset is None

    def assign(self,o):
        self.objects.append(o)

    def remove_assignment(self,s):
        for i,o in enumerate(self.objects) :
            if isinstance(o, hs.SignalAssignment) :
                if id(o) == id(s):
                    self.objects.pop(i)
            else :
                o.remove_assignment(s)

    def get_assignment(self): return _get_assignment(self.objects)

    def forgen_block(self,name,start,stop) :
        sb = ForGenerate(name,start,stop,parent=self)
        self.objects.append(sb)
        return sb

    def ifblock(self):
        ib = IfBlock(parent=self)
        self.objects.append(ib)
        return ib

    def switch(self,case_sig):
        ib = SwitchBlock(case_sig, parent=self)
        self.objects.append(ib)
        return ib

    def __enter__(self):
        ''
        self.at_saved = hs.get_assign_target()
        hs.set_assign_target(self)
        return self

    def __exit__(self, type, value, traceback):
        ''
        hs.set_assign_target(self.at_saved)

    def _io_signals(self, kind='o'):
        signal_list = []
        for o in self.objects:
            if kind=='o':
                signal_list += o.osignals
            elif kind=='i':
                signal_list += o.isignals
        return _s2.remove_same_item(signal_list)

    @property
    def osignals(self) : return self._io_signals('o')

    @property
    def isignals(self) :
        if self.reset is None :
            return self._io_signals('i')
        else :
            return self._io_signals('i') + self.reset.isignals

    @property
    def variables(self) :
        s = []
        for o in self.objects:
            s += o.variables
        return _s2.remove_same_item(s)
