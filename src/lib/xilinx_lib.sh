'''
    xilinx libraries
    
    * primitives : library for functional simulation of xilinx primitives
    * block ram : sdp, fifo 
    * dsp48
'''

#-------------------------------------------------------------------------
# xilinx library helpers (VHDL library declarations)
#-------------------------------------------------------------------------
_lib_unisim   = 'library unisim;\nuse unisim.vcomponents.all;'
_lib_unimacro = 'library unimacro;\nuse unimacro.vcomponents.all;'

def xilinx_unisim_lib(data):
    for d in data:
        lib_module(d['name'], d['i'], d['o'], d.get('io'), d.get('generic'), lib_code=_lib_unisim)

def xilinx_unimacro_lib(data):
    for d in data:
        lib_module(d['name'], d['i'], d['o'], d.get('io'), d.get('generic'), lib_code=_lib_unimacro)

def xilinx_unisim_lib_append(name, i, o, io=None, generic=None):
    lib_module(name, i, o, io, generic, lib_code=_lib_unisim)

def xilinx_unimacro_lib_append(name, i, o, io=None, generic=None):
    lib_module(name, i, o, io, generic, lib_code=_lib_unimacro)


#-------------------------------------------------------------------------
# unisim library
#-------------------------------------------------------------------------
_xilinx_primitives_data = [
    ## name should be capital case
    {'name': 'BUFG',    'i':['I'],          'o':['O'],     'io':None,   'generic':None},
    {'name': 'BUFGMUX', 'i':['I0','I1','S'],'o':['O'],     'io':None,   'generic':None},
    {'name': 'BUFGP',   'i':['I'],          'o':['O'],     'io':None,   'generic':None},
    {'name': 'IBUF',    'i':['I'],          'o':['O'],     'io':None,   'generic':None},
    {'name': 'IBUFG',   'i':['I'],          'o':['O'],     'io':None,   'generic':None},
    {'name': 'IBUFDS',  'i':['I','IB'],     'o':['O'],     'io':None,   'generic':None},
    {'name': 'IBUFGDS', 'i':['I','IB'],     'o':['O'],     'io':None,   'generic':None},
    {'name': 'IBUFGDS_DIFF_OUT', 'i':['I','IB'],     'o':['O','OB'],     'io':None,   'generic':None},
    {'name': 'IOBUF',   'i':['I','T'],      'o':['O'],     'io':['IO'], 'generic':None},
    {'name': 'OBUF',    'i':['I'],          'o':['O'],     'io':None,   'generic':None},
    {'name': 'OBUFDS',  'i':['I'],          'o':['O','OB'],'io':None,   'generic':None},
    {'name': 'OBUFT',   'i':['I','T'],      'o':['O'],     'io':None,   'generic':None},
    {'name': 'OBUFTDS', 'i':['I','T'],      'o':['O','OB'],'io':None,   'generic':None},
]

xilinx_unisim_lib(_xilinx_primitives_data)


#-------------------------------------------------------------------------
# block memory 
#-------------------------------------------------------------------------
_xilinx_block_ram = [ 

    # SDP (Simple Dual Port RAM)
    {   
        'name'    : 'BRAM_SDP_MACRO',
        'i'       : ['RST','WRCLK','RDCLK','DI[1]','WRADDR[1]','RDADDR[1]','WE[1]','WREN','RDEN','REGCE'],
        'o'       : ['DO'],
        'io'      : None,
        'generic' : {   
                        'BRAM_SIZE':"18Kb", 
                        'DEVICE':'7SERIES',
                        "DO_REG":"0",
                        "WRITE_WIDTH":16,
                        "READ_WIDTH":16,
                    },
    },

    # Dual Clock First-In, First-Out (FIFO) RAM Buffer
    {
        'name'    : 'FIFO_DUALCLOCK_MACRO',
        'i'       : ['DI[1]','RDCLK','RDEN','RST','WRCLK','WREN'],
        'o'       : ['ALMOSTEMPTY','ALMOSTFULL','DO','EMPTY','FULL','RDCOUNT','RDERR','WRCOUNT','WRERR'],
        'io'      : None,
        'generic' : {   
                        'DEVICE':'7SERIES',
                        'FIFO_SIZE':"18Kb", 
                        "DATA_WIDTH":4,  # Width of DI/DO bus 
                    },
    },
]
xilinx_unimacro_lib(_xilinx_block_ram)


#-------------------------------------------------------------------------
# api functions which use _xilinx_block_ram
#-------------------------------------------------------------------------
# regce : valid only if DO_REG is 1

# use only one 18Kb or 36Kb BRAM
def xbram_sdp(wclk,waddr,wdata,wen,rclk,raddr,ren,*,device="7SERIES"):
    assert wen.width == ren.width == 1, "Width of we and re should be 1"
    return _xbram_sdp(wclk,waddr,wdata,wen,rclk,raddr,ren,device=device)

def xbram_sdp_lut(clka,wrst,dina,we,clkb,addrb,re,*,device="7SERIES"):
    # write address
    # TODO : support asymmetric width
    addra = logic_like_unique("addra",addrb)
    with sequence(clka) :
        addra <= (0, wrst, addra + 1, we)
         
    return xbram_sdp(clka,addra,dina,we,clkb,addrb,re,device=device)


def xbram_sdp_fifo(clka,wrst,we,dina,clkb,rrst,re,*,depth=1024,device="7SERIES"):
    ' simple fifo (no empty, no full flag) implemented by sdp '
    w = min_bits(depth-1)

    doutb = logic_like_unique("doutb",dina)

    addra = logic_unique("addra[%s]" % w)
    addrb = logic_unique("addrb[%s]" % w)

    # write 
    with sequence(clka) :
        addra <= (0, wrst, addra + 1, we)

    # read 
    with sequence(clkb) :
        addrb <= (0, rrst, addrb + 1, re)

    return _xbram_sdp(clka,addra,dina,we,clkb,addrb,re,device=device)


def _xbram_sdp(wclk,waddr,wdata,wen,rclk,raddr,ren,*,device="7SERIES"):
    ''
    wr_addr_bits = waddr.width
    wr_data_bits = wdata.width
    rd_addr_bits = raddr.width

    # based on write 
    bram_kind,we_bits,min_addr_bits = xbram_sdp_conf(wr_addr_bits,wr_data_bits)

    # expand to minimum address bits
    if min_addr_bits > wr_addr_bits :
        diff_bits = min_addr_bits - wr_addr_bits

        modified_waddr_bits = min_addr_bits
        modified_waddr = logic_unique('%s[%s]'%(waddr.name,min_addr_bits))
        modified_waddr <= waddr

        modified_raddr_bits = rd_addr_bits + diff_bits
        modified_raddr = logic_unique('%s[%s]'%(raddr.name,rd_addr_bits+diff_bits))
        modified_raddr <= raddr

    else : 
        modified_waddr_bits = wr_addr_bits
        modified_waddr = waddr

        modified_raddr_bits = rd_addr_bits
        modified_raddr = raddr


    # support asymmetric width
    rd_data_bits = int(wr_data_bits * 2**(modified_waddr_bits-modified_raddr_bits))

    we_bits   = logic_unique("xbram_sdp_we[%d]:=-1" % we_bits)
    rdata     = logic_unique("xbram_rdata[%d]" % rd_data_bits)

    BRAM_SDP_MACRO(
        # generic
        DEVICE      = device,
        WRITE_WIDTH = wr_data_bits,
        READ_WIDTH  = rd_data_bits,
        DO_REG      = 0,
        BRAM_SIZE   = bram_kind,

        # port
        WRCLK  = wclk,
        RDCLK  = rclk,
        DI     = wdata,
        WRADDR = modified_waddr,
        RDADDR = modified_raddr,
        WE     = we_bits,
        WREN   = wen,
        RDEN   = ren,
        RST    = 0,  # doesnot control reset
        REGCE  = 0,  # valid only if DO_REG is 1
        DO     = rdata,
    )
    return rdata


'''
    Asynchronous reset of all FIFO functions, flags, and pointers. 
    RST must be asserted for five read and write clock cycles.     

    RDEN must be low before RST becomes active high, and RDEN remains low during this reset cycle. 
    WREN must be low before RST becomes active high, and WREN remains low during this reset cycle. 
'''
def xfifo_dual(wclk,rst,wen,wdata,rclk,ren,*,depth=1024,device="7SERIES"):
    ' dual clock fifo, doesnot support asymmetric width '
    depth_bits = min_bits(depth-1)  # if 1024 given, w is 10
    wr_data_bits = wdata.width

    fifo_size = xfifo_conf(depth_bits,wr_data_bits)

    rdata = logic_unique("xfifo_rdata[%s]" % wr_data_bits)

    empty = logic_unique("xfifo_empty")
    full = logic_unique("xfifo_full")

    # wr_count, rd_count are not used but are needed in simulation and implementation 
    wr_count = logic_unique("xfifo_wr_count[%s]" % depth_bits)
    rd_count = logic_unique("xfifo_rd_count[%s]" % depth_bits)

    # macro
    FIFO_DUALCLOCK_MACRO(
        # generic
        DEVICE      = device,
        DATA_WIDTH  = wdata.width,
        FIFO_SIZE   = fifo_size,    # 18Kb or 36Kb

        # port
        RST         = rst,  # async
        WRCLK       = wclk,
        DI          = wdata,
        WREN        = wen,

        RDCLK       = rclk,
        RDEN        = ren,

        DO          = rdata,
        ALMOSTEMPTY = None,
        ALMOSTFULL  = None,
        EMPTY       = empty,
        FULL        = full,
        RDCOUNT     = rd_count,
        RDERR       = None,
        WRCOUNT     = wr_count,
        WRERR       = None,
    )
    return rdata, empty, full

#-------------------------------------------------------------------------
# XSDP (xilinx simple dual port) memory expansion 
#-------------------------------------------------------------------------
def xsdp_1024_16_16(clka,addra,dina,we,clkb,addrb,re):
    assert dina.width == 16 and addra.width <= 10
    return xbram_sdp(clka,addra,dina,we,clkb,addrb,re)

def xsdp_1024_18_18(clka,addra,dina,we,clkb,addrb,re):
    return xbram_sdp(clka,addra,dina,we,clkb,addrb,re)

def xsdp_1024_32_32(clka,addra,dina,we,clkb,addrb,re):
    return xbram_sdp(clka,addra,dina,we,clkb,addrb,re)

def xsdp_1024_36_36(clka,addra,dina,we,clkb,addrb,re):
    return xbram_sdp(clka,addra,dina,we,clkb,addrb,re)

def xsdp_2048_18_18(clka,addra,dina,we,clkb,addrb,re):
    return xbram_sdp(clka,addra,dina,we,clkb,addrb,re)

def xsdp_2048_36_36(clka,addra,dina,we,clkb,addrb,re):
    " use two 36Kb BRAM (2048_18_18) "
    low  = xbram_sdp(clka,addra,dina[17:0],we,clkb,addrb,re)
    high = xbram_sdp(clka,addra,dina[35:18],we,clkb,addrb,re)
    return concat(high,low)



#-------------------------------------------------------------------------
# sub functions 
#-------------------------------------------------------------------------
def xbram_sdp_conf(addr_bits, data_bits):
    ' return (18Kb or 32Kb, WE width, modified addr bits) '
    KB18 = '18Kb'
    KB36 = '36Kb'

    if data_bits==1 : 
        if addr_bits<=14:
            return KB18,1,14
        elif addr_bits==15:
            return KB36,1,addr_bits
    elif data_bits==2 : 
        if addr_bits<=13:
            return KB18,1,13
        elif addr_bits==14:
            return KB36,1,addr_bits
    elif 3 <= data_bits <= 4 : 
        if addr_bits<=12:
            return KB18,1,12
        elif addr_bits==13:
            return KB36,1,addr_bits
    elif 5 <= data_bits <= 9 : 
        if addr_bits<=11:
            return KB18,1,11
        elif addr_bits==12:
            return KB36,1,addr_bits
    elif 10 <= data_bits <= 18 : 
        if addr_bits<=10:
            return KB18,2,10
        elif addr_bits==11:
            return KB36,2,addr_bits
    elif 19 <= data_bits <= 36 : 
        if addr_bits<=9:
            return KB18,4,9
        elif addr_bits==10:
            return KB36,4,addr_bits
    elif 37 <= data_bits <= 72 : 
        return KB36,8,9

    assert 0 , "Unknown configuration (data : %s, addr : %s)" % (data_bits, addr_bits)

def xfifo_conf(depth_bits,data_bits) : 
    if 1 <= data_bits <= 4 :
        if depth_bits==12:
            return '18Kb'
        elif depth_bits==13:
            return '36Kb'
    elif 5 <= data_bits <= 9 : 
        if depth_bits==11:
            return '18Kb'
        elif depth_bits==12:
            return '36Kb'
    elif 10 <= data_bits <= 18 : 
        if depth_bits==10:
            return '18Kb'
        elif depth_bits==11:
            return '36Kb'
    elif 19 <= data_bits <= 36 : 
        if depth_bits==9:
            return '18Kb'
        elif depth_bits==10:
            return '36Kb'
    elif 37 <= data_bits <= 72 : 
        assert depth_bits==9
        return '36Kb'


# #-------------------------------------------------------------------------
# # dsp48 macro
# #-------------------------------------------------------------------------
# _xilinx_dsp48_macro = [ 
# 
#     # MULT_MACRO
#     {   
#         'name'    : 'MULT_MACRO',
#         'i'       : ['A','B','CE','CLK','RST'],
#         'o'       : ['P'],
#         'io'      : None,
#         'generic' : {   
#                         'DEVICE':'7SERIES',
#                         "WIDTH_A":25,
#                         "WIDTH_B":18,
#                         "LATENCY":3,
#                     },
#     },
# ]
# xilinx_unimacro_lib(_xilinx_dsp48_macro)
# 
# def xdsp48_mult(clk,A,B,*,latency=3,device="7SERIES"):
#     ' A*B '
#     P = logic_unique("P[%s]"%(A.width+B.width))
# 
#     MULT_MACRO(
#         DEVICE      = device,
#         WIDTH_A     = A.width,
#         WIDTH_B     = B.width,
#         LATENCY     = latency,
# 
#         # port
#         A           = A,
#         B           = B,
#         CE          = 1,
#         CLK         = clk,
#         RST         = 0,
# 
#         P           = P,
#     )
#     return P
# 
# 
# #-------------------------------------------------------------------------
# # dsp48 
# # synthesizer convert mult_s25_s18 into dsp48
# #-------------------------------------------------------------------------
# def _dsp48_mult(clk,a,b):
#     a_d = logic_unique("a_d[%d]"%a.width)
#     b_d = logic_unique("b_d[%d]"%b.width)
#     m   = logic_unique("m[%d]"%(a.width+b.width))
#     p   = logic_unique("p[%d]"%(a.width+b.width))
# 
#     with sequence(clk) :
#         ''
#         # dsp48에 맞추어 구현한다. 3 latency
#         a_d <= a; 
#         b_d <= b; 
#         m <= signed(a_d) * signed(b_d); 
#         p <= m
#     return p
# 
# def mult_s25_s18(clk,a,b):
#     ' xilinx 7 series, 3 latency '
#     assert a.width <= 25 and b.width <= 18
#     return _dsp48_mult(clk,a,b)
# 
# def mult_s18_s18(clk,a,b):
#     ' xilinx spartan 6 series, 3 latency '
#     assert a.width <= 18 and b.width <= 18
#     return _dsp48_mult(clk,a,b)



#-------------------------------------------------------------------------
# idelay2, serdes 
#-------------------------------------------------------------------------



