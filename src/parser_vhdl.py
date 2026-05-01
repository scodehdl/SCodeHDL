'''
    VHDL code generator 
    2013/02/18 : start 
    2013/03/04 : port (  => manage the case 
    2013/03/05 : support multiple library definition
    2013-10-16 : support generic
    참고자료: http://tams-www.informatik.uni-hamburg.de/vhdl/tools/grammar/vhdl93-bnf.html#primary

    2014-05-19 : port name이 ,로 연결된 경우 지원
        clk,reset : std_logic;  
'''
import sys
from pyparsing import *

# import _s2
import parser_common

colon,semicolon,lparen,rparen,equal,comma,lbrace,rbrace,backtick = map(Suppress, ':;()=,{}`')
varray = ['std_%sbit_array'%i for i in range(64)]

def _cvt_results_to_dict2(output,*keys):
    ' parse result를 주어진 key를 갖는 dictionary로 변경한다. '
    o = dict()
    for k in keys : 
        # print(k,output.keys())
        if k in output.keys() : 
            if isinstance(output[k], ParseResults) : 
                o[k] = [i.asDict() for i in output[k]]
            else :  
                o[k] = output[k]

    # ports,signals를 dictionary로 변경 
    # 2018/05/09 : scodestudio에서 dict에 asDict 없다는 error가 발생한다. 
    # comment하고 수행해도 결과 이상없다. 0.93 patch1 
    def _p_2_dict(p) : 
        # if p['type'] == 'std_logic': 
        #     ''
        # elif p['type'] == 'std_logic_vector': 
        #     p['range'] = p['range'].asDict()  # from, dir, to
        #     print(p['range'])
        # else : # array
        #     p['range'] = p['range'].asDict()  # from, dir, to
        return p

    if 'ports' in output.keys() : 
        for p in o['ports'] : 
            # print(p)
            p = _p_2_dict(p)

    if 'signals' in output.keys() : 
        for p in o['signals'] : 
            p = _p_2_dict(p)

    return o

def parseEntityDefinition(input_string) : 
    ''' 
    ''' 
    var = _vhdl_parser_var()

    # parser = (SkipTo('entity',ignore=comment).suppress() + CaselessLiteral('entity').suppress() 
    parser = (SkipTo(CaselessLiteral('entity')).suppress() + CaselessLiteral('entity').suppress() 
            + var("entity_name") + CaselessLiteral("is").suppress()

            # generic definiton
            + Optional(_vhdl_parser_generic_def())

            # port definition
            + _vhdl_parser_port_def()

            # end of entity
            + CaselessLiteral("end").suppress() + var.suppress() + semicolon
            )
    parser.ignore(_vhdl_parser_comment())

    output = parser.parseString(input_string)

    # ports,generics to dictionary
    output = _cvt_results_to_dict2(output,'entity_name','ports','generics')

    # print(output)
    return output


def parseSignalDefinition(input_string) : 
    ''
    comment = _vhdl_parser_comment()
    var = parser_common.var

    # portio = parser_common.getPortIODefinition()
    porttype = _vhdl_parser_type()
    signal = (SkipTo('signal',ignore=comment).suppress() 
            + CaselessLiteral('signal').suppress() 
            + Group(var('name') + colon + porttype('type')) + semicolon)
    
    # signal이 한 개도 선언되지 않는 경우 처리 (Optional)
    parser = (SkipTo(CaselessLiteral('architecture')).suppress() + CaselessLiteral('architecture').suppress() + var.suppress() 
           + CaselessLiteral('of').suppress() + var.suppress() + CaselessLiteral('is').suppress()
           + Optional(OneOrMore(signal)('signals')) + CaselessLiteral("begin").suppress())

    parser.ignore(comment)
    output = parser.parseString(input_string)

    return _cvt_results_to_dict2(output,'signals')


def _vhdl_parser_port_def() : 
    ''
    var = _vhdl_parser_var()
    portio = _vhdl_parser_io()
    porttype = _vhdl_parser_type()
    portinit = _vhdl_value_init()
    port = Group(delimitedList(var,delim=',')('names') + colon + portio('io') + porttype('type') + Optional(':=' + portinit('init')))

    return (CaselessLiteral('port').suppress() 
        + lparen 
        + delimitedList(port, delim = ';' )('ports') 
        + rparen + semicolon)

def _vhdl_parser_comment() : 
    ''
    commentmark = '--'
    return (commentmark + restOfLine).suppress()

def _vhdl_parser_generic_def() : 
    var = _vhdl_parser_var()
    porttype = _vhdl_parser_type()

    generic = (Group(var('name') + colon + porttype('type') 
            + Optional(colon + equal + parser_common.number('value')))
            )

    # generic = var('name')
    return (CaselessLiteral('generic').suppress() 
            + lparen 
            # + delimitedList(generic, delim = ';' )('ports') 
            + delimitedList(generic, delim = ';' )('generics') 
            + rparen + semicolon)

def _vhdl_parser_var() : 
    return Word(alphas, alphanums+'_')

def _vhdl_parser_io() : 
    return oneOf("in out inout", caseless=True)

def _vhdl_logic_value() : 
    return oneOf("'0' '1' 'z'", caseless=True)

def _vhdl_vector_init() : 
    return lparen + CaselessLiteral('others') + CaselessLiteral('=>') + _vhdl_logic_value() + rparen

def _vhdl_value_init() : 
    return _vhdl_logic_value() | _vhdl_vector_init()

def _vhdl_parser_type() : 
    ''' port / signal type definition
    ex : std_logic, std_logic_vector(4 downto 0), std_8bit_array(3 downto 0) 
    '''
    number = Word(nums)
    term = number | Word(alphanums+'_') 
    operator = oneOf('- +')
    # expr = Combine(term + Optional(operator + term))
    expr = (term + Optional(operator + term)).setParseAction(lambda t: ''.join(t))

    logictype = CaselessLiteral('std_logic')('type')

    vrange = Group(lparen + expr('from') + oneOf('downto to', caseless=True)('dir') + expr('to') + rparen)('range')
    # vectortype        = CaselessLiteral('std_logic_vector')('type') + vrange
    vectortype        = oneOf("std_logic_vector signed unsigned", caseless=True)('type') + vrange

    vector_array_type = oneOf(' '.join(varray), caseless=True)('type') + vrange

    # integer type
    integer_type = CaselessLiteral('integer')

    # combine all
    porttype = (vectortype | logictype | vector_array_type | integer_type)
    return porttype
 
if __name__ == '__main__':
    ''
    #-------------------------------------------------------------------------
    # entity 
    #-------------------------------------------------------------------------
    s = '''
LIBRARY ieee;
USE ieee.std_logic_1164.ALL;
-- synthesis translate_off
Library XilinxCoreLib;
-- synthesis translate_on
ENTITY dccancel_e7 IS
	port (
	clk: in std_logic;
	ce: in std_logic;
	nd: in std_logic;
	filter_sel: in std_logic_vector(1 downto 0);
	rfd: out std_logic;
	rdy: out std_logic;
	din_1: in std_logic_vector(19 downto 0);
	din_2: in std_logic_vector(19 downto 0);
	dout_1: out std_logic_vector(32 downto 0);
	dout_2: out std_logic_vector(32 downto 0));
END dccancel_e7;
    '''

    s = '''
entity bufg is
port (
    I                 : in  std_logic;
    I2                 : in  std_logic_vector(2 downto 0) := "000";
    O                 : out std_logic
);
end entity;
'''
    
    o = parseEntityDefinition(s) 
    for p in o['ports'] : 
        print(p, type(p))


    # f = open('D:/work/VHDL_nplate/src/TX/serdes/top_nto1_pll_diff_rx.vhd')
    # # f = open('test.vhd')
    # o = parseEntityDefinition(f.read()) 
    # for p in o['ports'] : 
        # print(p, type(p))
    
