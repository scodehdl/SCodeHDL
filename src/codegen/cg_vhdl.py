'''
    VHDL code generation
    2013-06-08
    2013-08-01 : conversion에 관계되는 것은 모두 이곳으로 모음.
    2013-10-31 : refactoring (가급적 isinstance함수를 사용하지 않는 방향으로)
    2013-11-05 : vhdl_stimulus.py 합침. VHDL refactoring complete
    2013-12-13 : sequence , falling_edge 지원
    2014-05-05 : cg_vhdl.py로 이름 변경한 후 slab 지원 시작
    2014-05-11 : c_dst_repr, c_src_repr을 c_repr로 교체
    2014-05-11 : SignalConstant 정리
    2014-09-30 : -1은 1로 치환 (width가 1인 경우, c_repr_constant)
    2015-02-13 : 초기화 값을 변환한다.
    2015-04-23 : std_logic_arith, std_logic_unsigned library 사용하지 않을 수 있게 변경
    2015-09-09 : constant array 
'''
import io
import sys
import collections 
from string import Template
import itertools
import math
import textwrap

if __name__ == '__main__':
    sys.path.append('..')
    
import _s2
import hsignal as hs

# TIME_SLACK = 0.1  # 0.1ns
TIME_SLACK = 0.0


#-------------------------------------------------------------------------
# type, declaration 
#-------------------------------------------------------------------------
# type definition
def __vector_r(p):

    if p.sig_type is hs.SigType.logic : 
        type_name = 'std_logic_vector'
    else : # signed, unsigned 
        type_name = p.sig_type.name 

    if not isinstance(p.width, hs.GenericVar) : 
        if len(p.hdl_width_dict)==0:
            _w = p.total_bits
            if p.little_endian : 
                return '%s(%s downto %s)'%(type_name,(_w+p.start_bit-1),p.start_bit)
            else : 
                return '%s(%s to %s)'%(type_name,p.start_bit,(_w+p.start_bit-1))
        else: 
            k=p.hdl_width_dict
            return '%s(%s %s %s)'%(type_name,k['from'],k['dir'],k['to'])

    else : # sc에서 generic사용하여 width 결정한 vector이다.
        return '%s(%s-1 downto %s)'%(type_name,p.width.key,p.start_bit)

def __array_r(p):
    if p.little_endian : 
        return 'std_%sbit_array(%s downto 0)'% (p.width,len(p)-1)
    else : 
        return 'std_%sbit_array(0 to %s)'% (p.width,len(p)-1)

def c_type_def_logic(self): 
    return 'std_logic'

def c_type_def_vector(self): 
    return __vector_r(self)

def c_type_def_array(self): 
    return __array_r(self)


def c_type_def_slice(self): # vector or array 
    if isinstance(self.base_signal,hs.Array):
        return __array_r(self.base_signal)
    else : 
        return __vector_r(self.base_signal)


# signal declaration
def c_signal_decl(self):

    p = self if not isinstance(self,hs.LogicSlice) else self.base_signal
    if not p.init_defined: 
        return 'signal %-20s : %s;' % (p.name, p.c_type_def())
    else : 
        if isinstance(p, hs.Array) and p.init_defined and p.readonly:
            ' constant array '
            s = 'type %s_array is array(%s downto 0) of std_logic_vector(%s downto 0);\n' % (p.name,len(p)-1,p.width-1)
            s += 'constant %s : %s_array := %s;' % (p.name, p.name,p.c_value(p.init))
            return s
        else : 
            return 'signal %-20s : %s:=%s;' % (p.name, p.c_type_def(),p.c_value(p.init))


# state declaration
def c_signal_decl_state_logic(self):
    p = self
    s = 'signal %-20s : %s;' % (p.name, p.state_type.name)

    return s
#-------------------------------------------------------------------------
# value, value reset
#-------------------------------------------------------------------------
def _check_nan_to_zero(value) : 
    ' nan이면 0으로 return '
    # if math.isnan(value):
    if _s2.check_nan(value):
        return 0
    else : 
        return value


def c_logic_value(self,value) : 
    ' logic value : 0 or 1'
    value = _check_nan_to_zero(value)
    return "'%d'" % value

def c_vector_value(self,value) : 
    ' vector value '
    value = _check_nan_to_zero(value)
    return _hex_formatting(value,self.total_bits)


def c_mulitvector_value(self,value) : 
    ' multivector value '
    value = self.init_to_vector_value(value)
    value = _check_nan_to_zero(value)
    return _hex_formatting(value,self.total_bits)

def c_array_value(self,value) : 
    ''
    if type(value) is list : 
        ''
        # 한 line이 max_chars 넘으면 여러 라인으로 펼친다. 
        # git에서 10000 chars 넘으면 text 파일로 인식하지 못한다.
        max_chars = 9000
        one_width = _hex_formatting(value[0],self.width)
        n_per_line = max_chars // len(one_width)

        # array를 downto로 변환하니 value를 뒤집어야 한다.
        v_list = [_hex_formatting(v,self.width,nospace_flag=True) for v in value[::-1]]

        if len(value) > n_per_line: 
            s = ' '.join(v_list)    # s : ("11" & x"ff") ("11" & x"fe")
            wrap_list = textwrap.wrap(s,max_chars)
            k = [','.join(i.split(' ')) for i in wrap_list]
            return "(%s)" % ',\n'.join(k)
        else : # one line 
            return "(%s)" % (','.join(v_list))
        
    else : 
        value = _check_nan_to_zero(value)

        if value == 0:
            return "(others=>(others=>'0'))"
        else : 
            return "(others=>%s)" % _hex_formatting(value,self.width)


def c_signalslice_value(self,value) : 
    ' slice value '
    if isinstance(self, hs.ArraySlice):
        raise SyntaxError

    value = _check_nan_to_zero(value)
    if self.isvector() : 
        return _hex_formatting(value,self.width)
    else : # logic 
        return "'%d'" % value

def c_logic_value_reset(self,variable_flag=False) :
    symbol = '<=' if variable_flag==False else ':='
    return '%s %s %s' % (self.name,symbol,self.c_value(self.init))

def c_vector_value_reset(self,variable_flag=False) :
    ' vector value '
    symbol = '<=' if variable_flag==False else ':='

    value = _check_nan_to_zero(self.init)

    if value == 0 :  
        return "%s %s (others=>'0')" % (self.name,symbol)
    else : 
        # print(value)
        # return "%s %s %s" % (self.name,symbol,_hex_formatting(value,self.width))
        return "%s %s %s" % (self.name,symbol,_hex_formatting(value,self.total_bits))

def c_multivector_value_reset(self,variable_flag=False) :
    ' multi vector value '
    symbol = '<=' if variable_flag==False else ':='

    value = self.init_to_vector_value(self.init)
    value = _check_nan_to_zero(value)

    if value == 0 :  
        return "%s %s (others=>'0')" % (self.name,symbol)
    else : 
        return "%s %s %s" % (self.name,symbol,_hex_formatting(value,self.total_bits))

def c_array_value_reset(self,variable_flag=False) :
    symbol = '<=' if variable_flag==False else ':='

    if self.init_defined : 
        return "%s %s (%s)" % (self.name,symbol,self.c_value(self.init))
    else : 
        return "%s %s (others=>(others=>'0'))" % (self.name,symbol)


def c_statelogic_value_reset(self,variable_flag=False) :
    symbol = '<=' if variable_flag==False else ':='
    return '%s %s %s' % (self.name,symbol,self.init.name)

def c_constant_high_impedance(self,dummy=None):
    ''
    if self.width == 1 : return "'%s'" % 'Z'
    else : return '"%s"' % ('Z'*self.width)


#-------------------------------------------------------------------------
# representaion
#-------------------------------------------------------------------------
def c_repr(self): 
    return self.name

def c_repr_vector_combine(self): 
    # return ' & '.join(v.c_repr() for v in self.vectors)
    
    def _c_repr(v):
        # vector combine에서는 SignalConstant가 0이어도 others를 사용하면 안 됨
        if isinstance(v,hs.SignalConstant) : # 
            if v.width == 1 :  # _hex_formatting은 vector만 처리한다.
                return "'%s'" % v.value 
            else : 
                return _hex_formatting(v.value,v.width) 
        else : 
            return v.c_repr()

    return ' & '.join(_c_repr(v) for v in self.vectors)


def c_repr_signalslice(self):

    name= self.base_signal.name

    if isinstance(self, hs.ArraySlice): 
        ' Array에서 slice로 오는 경우만 있다. '
        return  '%s(%s downto %s)'%(name, self.slice1.start, self.slice1.stop)

    elif isinstance(self, hs.VectorSlice): 
        ''
        if isinstance(self.base_signal,hs.Array) : 
            ' Array에서 파생된 VectorSlice'
            if type(self.slice1) == int : 
                s = '%s(%s)'%(name, self.slice1)
            elif type(self.slice1) == slice : 
                s = '%s(%s downto %s)'%(name, self.slice1.start, self.slice1.stop)
            elif isinstance(self.slice1, hs.Vector):
                s = '%s(to_integer(unsigned(%s)))'%(name,self.slice1.name)
            elif isinstance(self.slice1, hs.VectorSlice):
                s = '%s(to_integer(unsigned(%s)))'%(name,c_repr_signalslice(self.slice1))
            else : 
                assert 0, '%s not supported' % self.slice1

            # slice2
            if self.slice2 is not None : 
                if type(self.slice2) == int : 
                    s += '(%s)'%(self.slice2)
                else : 
                    s += '(%s downto %s)'%(self.slice2.start, self.slice2.stop)
            return s

        elif isinstance(self.base_signal,hs.Vector) : 
            'vector에서 온 경우에는 slice만 있다.'
            # return  '%s(%s downto %s)'%(name, self.slice1.start, self.slice1.stop)
            if self.little_endian :  
                return  '%s(%s downto %s)'%(name, self.slice1.start, self.slice1.stop)
            else : 
                return  '%s(%s to %s)'%(name, self.slice1.start, self.slice1.stop)

        elif isinstance(self.base_signal,hs.VectorSlice) : 
            ' VectorSlice에서 다시 VectorSlice가 나온 경우 '
            return  '%s(%s downto %s)'%(name, self.slice1.stop + self.slice2.start, self.slice1.stop + self.slice2.stop)

        else : 
            return 'c_repr_signalslice:',self.base_signal, isinstance(self.base_signal,hs.Vector)

    else : # BitVectorSlice

        if isinstance(self.base_signal,hs.Vector) : 
            if type(self.slice1) == int : 
                return '%s(%s)'%(name, self.slice1)
            elif isinstance(self.slice1, hs.Vector):
                return '%s(to_integer(unsigned(%s)))'%(name,self.slice1.name)
            elif isinstance(self.slice1, hs.VectorSlice):
                return '%s(to_integer(unsigned(%s)))'%(name,c_repr_signalslice(self.slice1))
            elif isinstance(self.slice1, hs.ForVariable):
                return '%s(%s)'%(name,self.slice1.name)
            elif isinstance(self.slice1, hs.ArithmeticOperator):
                return '%s(%s)'%(name,c_op_src_repr_arithmetic(self.slice1))
            else : 
                assert 0, '%s not supported' % self.slice1

        elif isinstance(self.base_signal.base_signal,hs.Array) : 
            # Array에서 BitVectorSlice가 되려면 slice는 두 개 존재한다.
            # Array -> VectorSlice -> BitVectorSlice

            # slice1과 slice2가 모두 interger이다. 
            # return '%s(%s)(%s)'%(name, self.slice1, self.slice2)
            def _index_str(a):
                if type(a) == int : 
                    s1 = '(%s)' % a
                else : # vector
                    s1 = '(to_integer(unsigned(%s)))' % a.name
                return s1

            s1 = _index_str(self.slice1)
            s2 = _index_str(self.slice2)

            return '%s%s%s' % (name,s1,s2)

        elif isinstance(self.base_signal,hs.VectorSlice) : 
            ' VectorSlice에서 BitVector가 된 경우는 slice1는 물론 slice2까지 참조해야 한다.'
            if type(self.slice2) == int : 
                # print(self,self.base_signal, self.slice1, self.slice2,file=sys.stderr)
                return '%s(%s)'%(name, self.slice1.stop + self.slice2)
            else : 
                assert 0, '%s not supported' % self.slice2



def c_repr_valuetype(self):
    return self.code

def c_repr_for_var(self): 
    return self.name

def c_repr_constant(self): 
    ''
    v = self.value

    if self.array_flag : 
        if v == 0:
            return "(others=>(others=>'0'))"
        else : 
            return "(others=>%s)" % _hex_formatting(v,self.width)

    # mark = '"' if self.vector_1bit or self.width > 1 else "'"  # vector : ", logic '
    mark = '"' if self.vector_1bit or isinstance(self.width, hs.GenericVar) or self.width > 1 else "'"  # vector : ", logic '
    if type(v) == str : # 'X', 'Z'
        return '%s%s%s' % (mark, v*self.width, mark)
    else : # integer
        if self.width == 1 : 
            if v < 0 : v = 1   # -1은 1로 치환
            return '%s%s%s' % (mark, v, mark)
        else : 
            # return _hex_formatting(v,self.width) 
            if v==0 :
                return "(others=>'0')"
            else : 
                return _hex_formatting(v,self.width) 
    

def c_repr_signal_assignment(self):
    ' combinational assignement (when 사용) '
    # if isinstance(self, hs.SignalAssignmentMux):
    #     ''
    #     return __comb_mux(self.dst,self.sel,self.src)

    # else : # SignalAssignment
    if 1 : 
        dst        = self.dst
        values     = self.values
        conditions = self.conditions

        if len(conditions) >= 1 : 
            cvt_code = '%s <= ' % dst.c_repr()
            for i, kk in enumerate(zip(values,conditions)) : 
                v, c = kk 
                cvt_code += '%s when %s else ' % (v.c_repr(), c.c_repr())
 
            # last value : combination은 항상 value의 개수가 condition 개수보다 1개 많음
            # combinational은 recursive 지원하지 않는다.
            assert not isinstance(values[i+1],hs.AssignmentBase), "Combinational statment don't support recursive assignment "

            cvt_code += '%s;' % values[i+1].c_repr() 
            return cvt_code

        else : # no condition
            return _simple_statement(dst,values[0])

#-------------------------------------------------------------------------
# operator source representation 
#-------------------------------------------------------------------------
def c_op_src_repr(self):
    return repr(self)

def c_op_src_repr_function(self):
    # return '%s(%s)' % (self.func, self.argv.c_repr())
    func_name = self.func if self.func != 'logic' else 'std_logic_vector'

    return '%s(%s)' % (func_name, self.argv.c_repr())

def c_op_src_repr_boolean(self):
    if isinstance(self, (hs.AndExpr)):
        s = ' and '.join([e.c_repr() for e in self.operands])
        return '(%s)' % s
    elif isinstance(self,(hs.OrExpr)):
        s = ' or '.join([e.c_repr() for e in self.operands])
        return '(%s)' % s
    elif isinstance(self,(hs.XorExpr)):
        ''
        s = ' xor '.join([e.c_repr() for e in self.operands])
        return '(%s)' % s
    else : 
        return repr(self)

def c_op_src_repr_condition(self):
    condition = self

    op1,op2 = condition.op1, condition.op2

    if isinstance(op2, hs.SignalConstant):
        # if isinstance(op1, hs.FunctionExpr):
        #     op2 = op1.argv.c_value(op2.value)
        # else : 
        #     op2 = op1.c_value(op2.value)

        if op1.isvector() : # op2의 width로 표현한다.  
            op2 = _hex_formatting(op2.value,op2.width)
        else : 
            op2 = op1.c_value(op2.value)

    else : 
        op2 = op2.c_repr()

    op1 = op1.c_repr()

    if isinstance(condition, hs.ComparisonOperator):
        return _binary_operator(op1,op2, condition.operator)


def _arith_op_repr(op):
    ''
    if isinstance(op, hs.SignalConstant):
        op_r = op.value
    elif isinstance(op, hs.VectorCombine):
        op_r = 'unsigned(%s)' % op.c_repr() 
    elif isinstance(op,hs.ArithmeticOperator):  # multiple operation : A + B + C
        op_r = '(%s %s %s)' % (_arith_op_repr(op.op1),op.operator,_arith_op_repr(op.op2))
    elif isinstance(op,(hs.LogicBase,hs.VectorSlice)) : 
        if op.sig_type == hs.SigType.logic : 
            op_r = 'unsigned(%s)' % op.c_repr()
        else : 
            op_r = op.c_repr()
    elif isinstance(op,(hs.BitVectorSlice)) : 
        op_r = '("" & %s)' % op.c_repr()
    elif type(op) is int : 
        op_r = repr(op)
    else : 
        op_r = op.c_repr()

    return op_r

def c_op_src_repr_arithmetic(self):
    ' self.operator : + , - , *'

    assert self.operator in ['+', '-', '*']

    expr = self
    op1,op2 = expr.op1, expr.op2

    op1 = _arith_op_repr(op1)
    op2 = _arith_op_repr(op2)

    return '%s %s %s' % (op1,expr.operator,op2)

def c_op_src_repr_invert(self):
    if isinstance(self.op1, hs.LogicExpr):
        return 'not (%s)' % (self.op1.c_repr())
    else : 
        return 'not %s' % (self.op1.c_repr())

#-------------------------------------------------------------------------
#  HDLObject representation
#-------------------------------------------------------------------------
def c_cblock_repr(self): 
    return self.statement.c_repr()



#-------------------------------------------------------------------------
# seqblock 
#-------------------------------------------------------------------------
def c_seqblock_repr(self): 
    seq = self
    ''
    edge = 'rising_edge' if seq.clk_edge != 'falling' else 'falling_edge'

    indent_num = 12 if self.reset and self.reset_type=='sync' else 8

    if seq.reset : # async reset
        _sigs = []
        for s in seq.osignals : 
            _sigs.append(s)

        _vars = []
        for s in seq.variables : 
            _vars.append(s)
            
        # VectorSlice 중복을 피하기 위한 코드 추가
        _r_init = []
        for s in _vars : 
            k = '%s;' % s.c_value_reset(variable_flag=True)
            if k not in _r_init : 
                _r_init.append(k)

        for s in _sigs : 
            k = '%s;' % s.c_value_reset()
            if k not in _r_init : 
                _r_init.append(k)

        reset_init = '\n'.join(_r_init)
        reset_init = _s2.set_indentation(reset_init, indent_num).strip()
    
    # variable definition
    variable_def = ''
    if  seq.variables : 
        # variable_def += '\n'
        for v in seq.variables : 
            variable_def += '\n    variable %s : %s;' % (v.name,v.c_type_def())

    # body
    statements = ''
    if seq.objects :
        statements = __seqobject(seq.objects)
        statements = _s2.set_indentation(statements,indent_num).strip()

    #-------------------------------------------------------------------------
    # code generation
    #-------------------------------------------------------------------------
    _tmpl_process = '''
process($clk)$variable_def
begin
    if $edge($clk) then
        $statements
    end if;
end process;
'''
    _tmpl_process_areset = '''
process($clk, $reset)$variable_def
begin
    if $reset_expr then
        $reset_init
    elsif $edge($clk) then
        $statements
    end if;
end process;
'''
    # sync reset
    _tmpl_process_sreset = '''
process($clk)$variable_def
begin
    if $edge($clk) then
        if $reset_expr then
            $reset_init
        else
            $statements
        end if;
    end if;
end process;
'''
    
    cvt_code = ''
    if seq.reset : 
        assert isinstance(self.reset, hs.LogicExpr)
        reset = ','.join(i.name for i in self.reset.isignals)
        reset_expr = self.reset.c_repr()

        _tmpl_process_reset = _tmpl_process_sreset if self.reset_type=='sync' else _tmpl_process_areset 
        cvt_code += Template(_tmpl_process_reset).safe_substitute(
                    clk = seq.clk.name,
                    reset      = reset,
                    reset_expr = reset_expr,
                    reset_init = reset_init,
                    variable_def = variable_def,
                    statements = statements,
                    edge = edge,
                )
    else : # no reset
        cvt_code += Template(_tmpl_process).safe_substitute(
                    clk = seq.clk.name,
                    variable_def = variable_def,
                    statements = statements,
                    edge = edge,
                )
    return cvt_code

def c_module_repr(self): 
    ' imodule에 의해 include되는 module을 표현한다. '

    o = self

    __tmpl = '''
$uut : $entity_name port map (
    $port_connection
);
'''
    __tmpl_generic = '''
$uut : $entity_name
generic map (
    $generic_connection)
port map (
    $port_connection
);
'''
    def _connect_sig(k,v) : 
        ''
        if type(v) == int : 
            s = k.c_value(v)
            result = '    %-19s => %s'%(k.name,s)
        else : 
            v1_ = v.c_repr()
            result = '    %-19s => %s'%(k.name,v1_)
        return result

    # port => connection
    clist = []
    for port_sig in o.module.port_list :
        conn_sig = o.connection_dict.get(port_sig,None)
        if conn_sig is None : conn_sig = hs.SIG_OPEN

        clist.append(_connect_sig(port_sig,conn_sig))
    port_conn = ',\n'.join(clist).strip()

    # generic
    if o.connection_generic is not None and len(o.connection_generic) >  0 :
        clist = []
        for port_sig in o.module.generic_dict :
            conn_sig = o.connection_generic.get(port_sig,None)
            if conn_sig is None : 
                continue
            
            # clist.append('    %-19s => %s'%(port_sig,conn_sig))   # k, v

            if type(conn_sig) is str : 
                # check boolean
                if conn_sig.lower() in ['true','false'] : 
                    clist.append('    %-19s => %s'%(port_sig,conn_sig.lower()))   # k, v
                else : 
                    clist.append('    %-19s => "%s"'%(port_sig,conn_sig))   # k, v
            else:
                clist.append('    %-19s => %s'%(port_sig,conn_sig))   # k, v
        gen_conn = ',\n'.join(clist).strip()


    #-------------------------------------------------------------------------
    # conversion 
    #-------------------------------------------------------------------------
    # generic connection
    if o.connection_generic is None or len(o.connection_generic) == 0 :
        ''
        # conversion
        cvt_code = Template(__tmpl).safe_substitute(
                    uut             = 'u%s_%s' % (o.uut_id,o.module.mod_name),
                    entity_name     = o.module.mod_name,
                    port_connection = port_conn,
                )
    else : # generic 존재 
        cvt_code = Template(__tmpl_generic).safe_substitute(
                    uut             = 'u%s_%s' % (o.uut_id,o.module.mod_name),
                    entity_name     = o.module.mod_name,
                    generic_connection = gen_conn,
                    port_connection = port_conn,
                )


    return cvt_code 

def c_rawcode_repr(self) :
    return self.code

def c_blankline_repr(self) :
    # return "%s\n" % self.blank_line_num
    s = ""
    for i in range(self.blank_line_num) :
        s += "\n"
    return s

def c_switch_assign_repr(self) :
    _tmpl_process = '''
process($sensitivity)
begin
    $switch_statement
end process;
'''
    # print(self.isignals)
    # print(self.case_sig.c_repr())
    sensitivity = ','.join([i.c_repr() for i in [self.case_sig] + self.isignals])

    # 
    code = _s2.set_indentation(__switch_block(self),4).strip()
    cvt_code = Template(_tmpl_process).safe_substitute(
                switch_statement = code,
                sensitivity = sensitivity
            )
    return cvt_code

#-------------------------------------------------------------------------
# for loop 
#-------------------------------------------------------------------------
def _generic_arith_op_repr(op):
    ''
    if type(op) is int : 
        op_r = '%s' % op
    elif isinstance(op,hs.GenericArithmetic):
        op_r = '(%s %s %s)' % (_generic_arith_op_repr(op.op1),op.operator,_generic_arith_op_repr(op.op2))
    elif isinstance(op,hs.GenericVar):
        op_r = '%s' % op.key
    else : 
        op_r = op.c_repr()

    return op_r

def c_op_src_repr_generic_arithmetic(self):
    ' self.operator : + , - , *'

    assert self.operator in ['+', '-', '*']

    expr = self
    op1,op2 = expr.op1, expr.op2

    op1 = _generic_arith_op_repr(op1)
    op2 = _generic_arith_op_repr(op2)

    return '%s %s %s' % (op1,expr.operator,op2)

def c_forgen_repr(self): 
    ''
    _tmpl_forgen = '''
$gname : for $name in $start to $stop generate
begin
    $statements
end generate;
'''
    _tmpl_forloop = '''
for $name in $start to $stop loop
    $statements
end loop;
'''
    name = self.for_var.name
    gname = self.gen_name

    def _ss_repr(s):
        if type(s) is int : 
            return '%s' % s
        elif isinstance(s, hs.GenericVar) :
            return '%s' % s.key
        elif isinstance(self.stop, hs.GenericArithmetic) : 
            return s.c_repr()
        else : 
            return s

    start = _ss_repr(self.start)
    stop  = _ss_repr(self.stop)

    statements = ''
    if self.objects :
        if self.seq_flag==0:
            for o in self.objects :
                statements += o.c_repr()  # combinational objects
        else : 
            statements = __seqobject(self.objects)

        statements = _s2.set_indentation(statements,4).strip()

    _tmpl_s = _tmpl_forgen if self.seq_flag==0 else _tmpl_forloop        

    cvt_code = Template(_tmpl_s).safe_substitute(
                name = self.for_var.name,
                gname = gname,
                start = start,
                stop = stop,
                statements = statements,
            )
    return cvt_code


#-------------------------------------------------------------------------
# stimulus 
#-------------------------------------------------------------------------
def c_stimulus_repr(self): 
    return repr(self)

def c_delayed_assignment_repr(self):
    '''VHDL: signal <= expr after delay ns;
    repeat=True  →  clk <= not clk after 10 ns;
    repeat=False →  reset <= '0' after 100 ns;
    '''
    o = self
    if hasattr(o.expr, 'c_repr'):
        expr_str = o.expr.c_repr()
    else:
        expr_str = o.signal.c_value(o.expr)
    return '%s <= %s after %d ns;' % (o.signal.c_repr(), expr_str, o.delay)

def c_consolidated_assignment_repr(signal, points):
    '''VHDL: signal <= val1 after time1, val2 after time2...;'''
    items = []
    for p in points:
        if hasattr(p.expr, 'c_repr'):
            expr_str = p.expr.c_repr()
        else:
            expr_str = p.signal.c_value(p.expr)
        items.append('%s after %d ns' % (expr_str, p.delay))
    
    return '%s <= %s;' % (signal.c_repr(), ', '.join(items))


def c_stimulus_clock_repr(self):
    o = self
    half_period1 = int(o.period/2)
    half_period2 = o.period - int(o.period/2)

    if half_period1 == half_period2 : 
        return '%s <= not %s after %s ns;' % (o.clk.name,o.clk.name,half_period1)


def c_clocked_assignment_repr(self):
    '''VHDL: Single-cycle clocked stimulus process fallback.'''
    clk_name = self.clk.c_repr()
    sig_name = self.signal.c_repr()
    if hasattr(self.expr, 'c_repr'):
        expr_str = self.expr.c_repr()
    else:
        expr_str = self.signal.c_value(self.expr)
    
    waits = "\n    ".join(["wait until rising_edge(%s);" % clk_name for _ in range(self.cycle)])
    
    res = f"""
process
begin
    {waits}
    {sig_name} <= {expr_str};
    wait;
end process;"""
    return res.strip()

def c_consolidated_clocked_assignment_repr(clk, signal, points):
    '''VHDL: Multi-cycle clocked stimulus process for a signal.'''
    clk_name = clk.c_repr()
    sig_name = signal.c_repr()

    body = []
    last_cycle = 0
    for p in points:
        diff = p.cycle - last_cycle
        if diff > 0:
            if diff == 1:
                body.append(f"wait until rising_edge({clk_name});")
            else:
                body.append(f"for i in 1 to {diff} loop")
                body.append(f"    wait until rising_edge({clk_name});")
                body.append(f"end loop;")

        if hasattr(p.expr, 'c_repr'):
            expr_str = p.expr.c_repr()
        else:
            expr_str = p.signal.c_value(p.expr)
        body.append(f"{sig_name} <= {expr_str};")
        last_cycle = p.cycle

    body_str = "\n    ".join(body)
    res = f"""
process
begin
    {body_str}
    wait;
end process;"""
    return res.strip()


def c_consolidated_group_clocked_repr(clk, signal_points_groups):
    '''VHDL: Multiple signals driven together in one process.

    signal_points_groups: list of (signal, sorted_points)
    '''
    from itertools import groupby
    clk_name = clk.c_repr()

    all_points = []
    for signal, points in signal_points_groups:
        for p in points:
            all_points.append((p.cycle, signal, p.expr))
    all_points.sort(key=lambda x: x[0])

    body = []
    last_cycle = 0
    for cycle, group in groupby(all_points, key=lambda x: x[0]):
        diff = cycle - last_cycle
        if diff > 0:
            if diff == 1:
                body.append(f"wait until rising_edge({clk_name});")
            else:
                body.append(f"for i in 1 to {diff} loop")
                body.append(f"    wait until rising_edge({clk_name});")
                body.append(f"end loop;")

        assign_strs = []
        for _, sig, expr in group:
            expr_str = expr.c_repr() if hasattr(expr, 'c_repr') else sig.c_value(expr)
            assign_strs.append(f"{sig.c_repr()} <= {expr_str};")
        body.append(" ".join(assign_strs))
        last_cycle = cycle

    body_str = "\n    ".join(body)
    return f"process\nbegin\n    {body_str}\n    wait;\nend process;"


    __tmpl = '''
clk_process_${uut}_p : process
begin
    $clk <= '1';
    wait for $half_period1 ns;
    $clk <= '0';
    wait for $half_period2 ns;
end process;
'''

    cvt_code = ''
    cvt_code += Template(__tmpl).safe_substitute(
                clk = o.clk.name,
                uut = o.id,
                half_period1 = half_period1,
                half_period2 = half_period2,
            )
    return cvt_code

def c_stimulus_reset_repr(self): 
    o = self
    __tmpl = '''
reset_process_${uut}_p : process
begin
    $reset <= '0';
    wait for $delay ns;
    wait until rising_edge($clk);
    $reset <= '1';
    wait until rising_edge($clk);
    $reset <= '0';
    wait;
end process;
'''

    cvt_code = ''
    cvt_code += Template(__tmpl).safe_substitute(
                clk = o.clk.name,
                reset = o.reset.name,
                uut = o.id,
                delay = o.delay,
            )
    return cvt_code

def c_stimulus_wave_repr(self) : 
    '''
    example) value_time = [(0,100),(1,100),(0,0)]
    =>          
        reset <= '0'; wait for 100 ns;  
        reset <= '1'; wait for 100 ns;  
        reset <= '0';
        wait;
    '''
    o = self

    __tmpl = '''
wave_process_${uut}_p : process
begin
    wait for ${time_slack} ns;
    $wave
    wait;
end process;
'''
    # wave = ["%s <= %s; wait for %s ns;"%(o.sig.name,o.sig.c_value(value),time) for value,time in o.value_time]
    wave = []
    for value,time in o.value_time:
        if type(value) == int :      
            wave.append("%s <= %s; wait for %s ns;"%(o.sig.c_repr(),o.sig.c_value(value),time))
        else : 
            wave.append("%s <= %s; wait for %s ns;"%(o.sig.c_repr(),value.c_repr(),time))

    wave = _s2.list_to_indented_line(wave,4).strip()

    #
    cvt_code = ''
    cvt_code += Template(__tmpl).safe_substitute(
                sig = o.sig.name,
                uut = o.id,
                time_slack = TIME_SLACK,
                wave = wave,
            )

    return cvt_code 



def c_stimulus_file_input_repr(self):
    ''
    __tmpl_fin = '''
rfile_p_$uut : process
    variable buf : line;
    file infile : text;
    variable ch_dummy : character;
    variable ch : std_logic_vector(3 downto 0);
    $var_list

begin
    file_open(infile, "$fname", read_mode);
    report("[$fname] input started");
    $init_list
    wait until $enable='1';

    while not (endfile(infile)) loop
        readline(infile, buf);

        if buf(1) /= '#' then
            wait until rising_edge($clk);
            $read_list
        end if;
    end loop;
    file_close(infile);
    report("[$fname] input ended");
    wait;
end process;
    '''
    var_list = []
    for i,s in enumerate(self.ilist)  : 
        if isinstance(s,hs.Vector) : 
           var_list.append('variable v_%s : %s;' % (s.name,s.c_type_def()))

    init_list = []
    for i,s in enumerate(self.ilist)  : 
        if isinstance(s,hs.BitVector) : 
            init_list.append("%s <= '0';" % (s.name))
        elif isinstance(s,hs.Vector) : 
            init_list.append("%s <= (others=>'0');" % (s.name))
        else : 
            assert 0, 'Un-supported type : %s' % s

    read_list = []
    for i,s in enumerate(self.ilist)  : 
        if i == len(self.ilist) - 1 :  # last 
            sp_read = ''
        else : 
            sp_read = "read(buf, ch_dummy);"

        if isinstance(s,hs.BitVector) : 
            # read_list.append('read(buf, ch);  %s <= to_std_logic(ch); %s' % (s.name,sp_read))
            read_list.append('hread(buf, ch);  %s <= ch(0); %s' % (s.name,sp_read))
        elif isinstance(s,hs.Vector) : 
            read_list.append('hread(buf, v_{0}); {0} <= v_{0}; {1}'.format(s.name,sp_read))
        else : 
            assert 0, 'Un-supported type : %s' % s

    # conversion
    cvt_code = ''
    cvt_code += Template(__tmpl_fin).safe_substitute(
                clk = self.clk.name,
                uut = self.id,                
                enable = self.enable.name,
                fname = self.fname,
                var_list = _s2.list_to_indented_line(var_list,8).strip(),
                init_list = _s2.list_to_indented_line(init_list,4).strip(),
                read_list = _s2.list_to_indented_line(read_list,12).strip(),
            )

    return cvt_code 


def c_stimulus_file_output_repr(self):
    ''
    __tmpl_fout = '''
wfile_p_$uut : process
    variable buf : line;
    file outfile : text;
    variable i : integer;
begin
    file_open(outfile, "$fname", write_mode);
    report("[$fname] output started");
    i := 0;
    while i < $output_num loop
        wait until rising_edge($clk);

        if $enable='1' then
            $write_list

            writeline(outfile,buf);

            i := i + 1;
        end if;
    end loop;
    file_close(outfile);
    report("[$fname] output ended");
    wait;
end process;
    '''
    write_list = []
    for i,s in enumerate(self.olist)  : 
        if i == len(self.olist) - 1 :  # last 
            sp_write = ''
        else : 
            sp_write = 'write(buf, " ");'

        if isinstance(s,hs.BitVector) : 
            write_list.append('write(buf,%s); %s' % (s.c_repr(),sp_write))
        elif isinstance(s,hs.Vector) : 
            write_list.append('hwrite(buf,%s); %s' % (s.c_repr(),sp_write))
        else : 
            assert 0, 'Un-supported type : %s' % s

    # conversion
    cvt_code = ''
    cvt_code += Template(__tmpl_fout).safe_substitute(
                clk = self.clk.name,
                uut = self.id,
                enable = self.enable.name,
                fname = self.fname,
                output_num = self.output_num,
                write_list = _s2.list_to_indented_line(write_list,12).strip()
            )

    return cvt_code 

#-------------------------------------------------------------------------
#  simple statement 
#-------------------------------------------------------------------------
def _simple_statement(dst,v):
    return '%s <= %s;' % (dst.c_repr(),v.c_repr())


def _simple_statement_variable(dst,v):
    # return '%s := %s;' % (dst.c_repr(),_cvt_value(dst, v))
    return '%s := %s;' % (dst.c_repr(),v.c_repr())

#-------------------------------------------------------------------------
# sequential if statement 
#-------------------------------------------------------------------------
def __seq_statement(statement) : 
    # return __seq_statement_(statement,_simple_statement) 

    if isinstance(statement,hs.SignalAssignment) : 
        return __seq_statement_(statement,_simple_statement)
    elif isinstance(statement,hs.VariableAssignment) : 
        return __seq_statement_(statement,_simple_statement_variable) 


def __seq_statement_variable(statement) : 
    return __seq_statement_(statement,_simple_statement_variable)

def __seq_statement_(statement, conv_func) : 
    ' assignment and sequential if, elif, else '

    __tmpl_if = '''
if $condition then
    $statement
'''
    __tmpl_elif = '''elsif $condition then
    $statement
'''

    dst        = statement.dst
    values     = statement.values
    conditions = statement.conditions
    
    #
    if len(conditions) >= 1 : 
        ''
        cvt_code = ''

        for i, kk in enumerate(zip(values, conditions)) : 
            v, c = kk 
            __tmpl = __tmpl_if if i==0 else __tmpl_elif 

            # statement = conv_func(dst,v)
            if isinstance(v, hs.AssignmentBase):
                statement = _s2.set_indentation(__seq_statement_(v,conv_func),4).strip()
            else : 
                statement = conv_func(dst,v)

            cvt_code += Template(__tmpl).safe_substitute(
                    condition  = c.c_repr(),
                    # statement  = conv_func(dst,v),
                    statement  = statement,
            )

        # else
        if len(values) > len(conditions) :
            cvt_code += 'else\n'

            # cvt_code += '    %s\n' % conv_func(dst,values[i+1])
            v = values[i+1]

            if isinstance(v, hs.AssignmentBase):
                statement = _s2.set_indentation(__seq_statement_(v,conv_func),4).strip()
            else : 
                statement = conv_func(dst,v)

            cvt_code += '    %s\n' % statement

        cvt_code += 'end if;'            
        return cvt_code.lstrip()

    else : # no condition    
        return conv_func(dst,values[0])


#-------------------------------------------------------------------------
# sequential conversion 
#-------------------------------------------------------------------------
def _ifblock(ifblock):
    ''
    keys = ifblock.conditions

    cvt_code = ''
    for i,cond in enumerate(keys) : 
        if i == 0 : 
            m = 'if' 
        elif isinstance(cond,hs.AllTrue):
            m = 'else' 
        else : 
            m = 'elsif'

        if m == 'else':
            cvt_code += '%s\n' % (m)   # else
        else : 
            cvt_code += '%s %s then\n' % (m,cond.c_repr())

        for s in ifblock.conditions[cond] : 
            cvt_code += '    %s\n' % _s2.set_indentation(__seq_(s),4).strip()

    if len(ifblock.conditions) > 0 : 
        cvt_code += 'end if;\n'

    return cvt_code


def __seq_(o):
    if isinstance(o,hs.SignalAssignment) : 
        cvt_code = '%s\n' % __seq_statement(o)
    elif isinstance(o,hs.VariableAssignment) : 
        cvt_code = '%s\n' % __seq_statement_variable(o)
    elif isinstance(o,hs.SwitchBlock) : 
        cvt_code = '%s\n' % __switch_block(o)
    elif isinstance(o,hs.ForGenerate) : 
        cvt_code = '%s\n' % o.c_hdl_repr()
    else :
        cvt_code = '%s' % _ifblock(o)
    return cvt_code

def __seqobject(objects):
    ''
    cvt_code = ''  

    for o in objects : 
        cvt_code += __seq_(o) 

    return cvt_code


def __switch_block(swb):
    ''
    cvt_code = ''
    if swb.conditions :
        cvt_code = __switch_case(swb.case_sig,swb.conditions)

    return cvt_code


def _check_simple_statement(s):
    ' condition이 없으면 simple statement'
    if len(s.values)==1 and len(s.conditions)==0 :
        return 1
    else:
        return 0


def __switch_case(case_sig,conditions) :  
    ''
    _tmpl_case_other = '''
case $sel is
    $when_statements
end case;
'''
    _tmpl_case_process = '''
case $sel is
    $when_statements
    $other_statements
end case;
'''
    
    other_exist = False

    def _when_cvt(k, objects):
        ''
        num = len(objects)
        if num == 1 and not isinstance(objects[0],hs.IfBlock) and _check_simple_statement(objects[0]) :
            t = 'when %s => %s' % (k, __seq_statement(objects[0]))
        else : 
            t = 'when %s =>\n' % k
            t += '    %s\n' % _s2.set_indentation(__seqobject(objects),4).strip()
        return t.rstrip()

    statements = []
    for cond in conditions : 
        ''
        if not isinstance(cond,hs.AllTrue) : 
            if type(cond.op2) is int :  
                k = case_sig.c_value(cond.op2)
            elif isinstance(cond.op2,hs.SignalConstant) :  
                k = case_sig.c_value(cond.op2.value)
            else : 
                k = cond.op2.value.name

        else : 
            k = 'others'
            other_exist = True

        t = _when_cvt(k,conditions[cond])
        statements.append(t)

    statements = '\n'.join(statements)
    statements = _s2.set_indentation(statements, 4).strip()

    if other_exist : 
        cvt_code = Template(_tmpl_case_other).safe_substitute(
                    sel = case_sig.c_repr(),
                    when_statements = statements,
                )
    else : 
        cvt_code = Template(_tmpl_case_process).safe_substitute(
                    sel = case_sig.c_repr(),
                    when_statements = statements,
                    other_statements = 'when others => null;',
                )

    return cvt_code

#-------------------------------------------------------------------------
# sub functions 
#-------------------------------------------------------------------------
def _hex_formatting(value,n,nospace_flag=False) : 
    ' 이 procedure는 vector를 표시하는 경우에만 call된다. '
    ' vector value를 hex로 표시한다. '

    # generic
    if isinstance(n,hs.GenericVar):
        return 'std_logic_vector(to_unsigned(%s,%s))' % (value,n.key)

    # 
    if value < 0 : # 음수는 2's complement로 변경한다. 
        value = 2**n + value

    bin_digit = n % 4 
    hex_digit = n // 4 
    
    if bin_digit==0:  # multiple of 4
        return 'x"%s"' % hex(value)[2:2+hex_digit].zfill(hex_digit)
    elif hex_digit == 0 :  
        ' 4bits 미만인 경우이다. '
        assert 0 < bin_digit < 4
        return '"%s"' % bin(value)[2:].zfill(bin_digit)    
    else : 
        hvalue = int(hex(value)[2:][-hex_digit:],16)
        bvalue = ((bin(value - hvalue)[2:])[:-hex_digit*4]).zfill(bin_digit)

        s = '%s'%hex(hvalue)[2:]

        if nospace_flag : 
            if bin_digit == 1 : 
                ' bin digit는 "이 아닌 \'을 사용해야 한다. "' 
                return '(\'%s\'&x"%s")' % (bvalue, s.zfill(hex_digit))
            else : 
                return '("%s"&x"%s")' % (bvalue, s.zfill(hex_digit))
        else : 
            if bin_digit == 1 : 
                ' bin digit는 "이 아닌 \'을 사용해야 한다. "' 
                return '(\'%s\' & x"%s")' % (bvalue, s.zfill(hex_digit))
            else : 
                return '("%s" & x"%s")' % (bvalue, s.zfill(hex_digit))


def _binary_operator(op1, op2, operator) : 
    ' =, >, < , >= '
    # conversion to vhdl
    if operator == '==' : operator = '='
    elif operator == '!=' : operator = '/='

    return '%s %s %s' % (op1,operator,op2)


if __name__ == '__main__':
    ''






