'''
    Verilog parser
    2015-05-03 : restarted
'''
import sys
from pyparsing import *

import parser_common

colon,semicolon,lparen,rparen,equal,comma,lbrace,rbrace,backtick = map(Suppress, ':;()=,{}`')
number = Word(nums)

def _cvt_results_to_dict(output):
    ''' dict 를 return 한다. key : module_name, ports
        ports는 string list이고, string은 scode에서 logic 정의하는 형식이다.
    '''
    out_dict = dict()

    out_dict['module_name'] = output['module_name']

    if 'ports' in output.keys() :
        ports = output['ports']

        new_ports = []
        for p in ports : 
            for name in p['names'] : 
                s = dict(name=name, io=p['io'])
                if 'range' in p : 
                    s['range'] = slice(int(p['range']['start']),int(p['range']['stop'])) 
                new_ports.append(s)
                 
        out_dict['ports'] = new_ports

    return out_dict

def _check_verilog_version(input_string):
    ' return 0 : verilog 95, 1 : verilog 2001 '
    var = _verilog_parser_var()

    parser = (SkipTo(Literal('module')).suppress() + Literal('module').suppress() 
            + var("module_name") 
            + Literal("(").suppress() 
            + oneOf("input output inout", caseless=False)
            + SkipTo(Literal(")").suppress()))

    parser.ignore(cppStyleComment)

    try : 
        output = parser.parseString(input_string)
        return 1
    except : 
        return 0
    return output

def _parseModuleDefinition_95(input_string) : 
    ''' 
        verilog 95
    module test(
        clk,reset,we,addra,dina,re,addrb,dinb
    );
        input  clk;
        input  reset;
    ''' 
    var = _verilog_parser_var()

    parser = (SkipTo(Literal('module')).suppress() + Literal('module').suppress() 
            + var("module_name") 
            + Literal("(").suppress() 
            + delimitedList(var,delim=',')('names')
            + Literal(")").suppress() + semicolon

            + OneOrMore(_verilog_parser_port_def_95())('ports')

            # end of module
            + SkipTo(Literal("endmodule")).suppress()
            )

    parser.ignore(cppStyleComment)

    output = parser.parseString(input_string)

    # ports,generics to dictionary
    output = _cvt_results_to_dict(output)

    return output

def _parseModuleDefinition_2001(input_string) : 
    ''' 
        verilog 2001

    module test(
        input clk,
        input reset,
        input[10:0] addra,
        output [35:0] dinb
    );
    ''' 
    var = _verilog_parser_var()

    parser = (SkipTo(Literal('module')).suppress() + Literal('module').suppress() 
            + var("module_name") 
            + Literal("(").suppress() 
            + delimitedList(_verilog_parser_port_def_2001(),delim=',')('ports')
            + Literal(")").suppress() + semicolon

            # end of module
            # + SkipTo(Literal("endmodule")).suppress()
            )

    parser.ignore(cppStyleComment)

    output = parser.parseString(input_string)

    # ports,generics to dictionary
    output = _cvt_results_to_dict(output)
    return output

def parseModuleDefinition(input_string) : 
    if _check_verilog_version(input_string) == 0 : 
        return _parseModuleDefinition_95(input_string)
    else:
        return _parseModuleDefinition_2001(input_string)


def _verilog_statement() : 
    ''

def _verilog_parser_port_def_95() : 
    ''
    var = _verilog_parser_var()
    portio = _verilog_parser_io()


    return  Group(portio('io') 
            + Optional(_verilog_vector_def()('range'))
            + delimitedList(var,delim=',')('names') + semicolon 
            )

def _verilog_parser_port_def_2001() : 
    ''
    # port = CaselessKeyword("input") | CaselessKeyword("output")| CaselessKeyword("inout")
    port = Keyword("input") | Keyword("output") | Keyword("inout")

    var = ~port + _verilog_parser_var()

    portio = _verilog_parser_io()


    return  Group(portio('io') 
            + Optional(_verilog_vector_def()('range'))
            + delimitedList(var,delim=',')('names')
            )


def _verilog_parser_io() : 
    # return oneOf("input output inout", caseless=False)
    output = Keyword("output") + Optional(Keyword("reg")) 
    inout  = Keyword("inout") + Optional(Keyword("reg")) 
    return Keyword("input") | output | inout

def _verilog_vector_def() : 
    return Suppress("[") + number('start') + colon + number('stop') + Suppress("]")

def _verilog_parser_var() : 
    return Word(alphas, alphanums+'_')


if __name__ == '__main__':
    ''
    s = '''
// --------------
module encoder_using_if(
    binary_out , //  4 bit binary output
    encoder_in , //  16-bit input
    enable       //  Enable for the encoder
);

input  enable,enable2; 
input [15:0] encoder_in ; 
output [3:0] binary_out;

always @ (posedge clk)
begin
    b <= bidir;
    a <= inp;
end


endmodule
'''
    # o = parseModuleDefinition(s) 
    # for p in o['ports'] : 
    #     print(p, type(p))
    
    s2 = '''
// --------------
module encoder_using_if(
    binary_out , //  4 bit binary output
    encoder_in , //  16-bit input
    enable       //  Enable for the encoder
);
input binary_out;
input encoder_in;
input enable;
endmodule
'''
    s3 = '''
module imodule_verilog(
    input  clk,
    input  reset,
    input  we,
    input  [10:0] addra,
    input  [35:0] dina,
    input  re,
    // input  [10:0] addrb,
    output  reg [35:0] dinb
);

endmodule
'''
    # o = _check_verilog_version(s3)
    # print(o)

    o = parseModuleDefinition(s3) 
    for p in o['ports'] : 
        print(p, type(p))


