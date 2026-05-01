'''
    beta candiate libraries 

    최종 release될 때에는 core_lib.sh와 같은 해당 library로 옮겨진다.

    beta library는 예고없이 사라질 수 있으므로 각각의 user library에 복사한 후
    사용한다.
'''

def accumulator(clk, reset, enable, acc_int, acc_frac, owidth=16) :
    ''
    N = acc_frac.width
    acc_value  = logic_unique("acc_value[%s]" % owidth)
    s_fraction = logic_unique("s_fraction[%s]" % (acc_frac.width+1))

    s_integer  = logic_unique("s_integer[%s]" % owidth)

    # fraction
    with sequence(clk) :
        s_fraction <= (0,reset,concat(LL(1),s_fraction[acc_frac.width-1:0]) + acc_frac, enable)

    # integer
    if type(acc_int) == int : # integer 
        with sequence(clk) :
            s_integer <= (0,reset,s_integer + acc_int + s_fraction[acc_frac.width], enable)
    elif acc_int.islogic() : # convert to 1 bit vector  
        acc_int_vector  = logic_unique("acc_int_vector[1]")
        acc_int_vector[0] <= acc_int
        with sequence(clk) :
            s_integer <= (0,reset,s_integer + acc_int_vector + s_fraction[acc_frac.width], enable)
    else :
        with sequence(clk) :
            s_integer <= (0,reset,s_integer + acc_int + s_fraction[acc_frac.width], enable)

    acc_value <= s_integer

    return acc_value



#-------------------------------------------------------------------------
# memory 
#-------------------------------------------------------------------------
def array_rom(addr_len,data_width,initdata):
    ''
    rom = array_unique('rom[%s][%s]' % (addr_len,data_width))

    # if initdata is not None : 
    #     rom.init = initdata

    assert initdata is not None
    rom.init = initdata

    rom.readonly = True
    return rom

def array_ram(addr_len,data_width,initdata=None):
    ''
    r = array_unique('ram[%s][%s]' % (addr_len,data_width))

    if initdata is not None: 
        r.init = initdata

    r.readonly = False
    return r

#-------------------------------------------------------------------------
# pattern generator
#-------------------------------------------------------------------------
def pattern_generator(clk,reset,enable,data) : 

    arr_rom = array_rom(len(data),max_bits_of_list(data),data)
    
    n = len(arr_rom)

    # counter
    cnt = logic_unique('cnt[%s]' % min_bits(n-1))

    with sequence(clk) :
        cnt <= (0,reset,cnt + 1,enable)

    return arr_rom[cnt]



#-------------------------------------------------------------------------
# simple dualport memory with array (width of dina, doutb are same)
#-------------------------------------------------------------------------
def array_sdp(clka,we,addra,dina,clkb,re,addrb,*,init_data=None):
    ''
    contents = array_ram(2**addra.width,dina.width,init_data)

    # write
    with sequence(clka) :
        contents[addra] <= (dina,we)

    # read
    doutb = logic_like_unique("doutb",dina)
    with sequence(clkb) :
        doutb <= (contents[addrb],re)

    return doutb

#-------------------------------------------------------------------------
# lut access, lut write is done sequentially after write reset 
#-------------------------------------------------------------------------
def array_lut(clka,wrst,we,dina,clkb,re,addrb,*,init_data=None):

    # write address
    addra = logic_like_unique("addra",addrb)
    with sequence(clka) :
        addra <= (0, wrst, addra + 1, we)
         
    return array_sdp(clka,we,addra,dina,clkb,re,addrb,init_data=init_data)


#-------------------------------------------------------------------------
# simple fifo (without no empty, no full flag) implemented by array
#-------------------------------------------------------------------------
def array_fifo(clka,wrst,we,dina,clkb,rrst,re,*,depth=1024):
    ''
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

    return array_sdp(clka,we,addra,dina,clkb,re,addrb)

## 

# sign extension
def sign_ext(sig,width):
    return concat(FILL(sig[len(sig)-1],width-len(sig)),sig)


# standard fifo (read, write clocks are same)
# http://www.deathbylogic.com/2013/07/vhdl-standard-fifo/
def simple_fifo(clk,rst,we,datain,re,depth=256):
    depth_bits = min_bits(depth-1)

    contents = array_ram(2**depth_bits,datain.width)

    full  = logic_unique("full")
    empty = logic_unique("empty")

    head = logic_unique("head[%s]"%depth_bits)
    tail = logic_unique("tail[%s]"%depth_bits)
    looped = logic_unique("looped")
    dataout = logic_like_unique("dataout",datain)

    with sequence(clk) :
        if rst : 
            head << 0
            tail << 0
            looped << 0

            full <= 0
            empty <= 1
            dataout <= 0
        else : 
            ''
            if re : 
                if looped | (head != tail) : 
                    dataout <= contents[tail]
                
                    if tail == depth-1 : 
                        tail << 0
                        looped << 0
                    else : 
                        tail << tail + 1

            if we : 
                if -looped | (head != tail) : 
                    contents[head] << datain

                    if head == depth-1 : 
                        head << 0
                        looped << 1
                    else : 
                        head << head + 1

        # update flag
        if head == tail : 
            if looped : 
                full <= 1
            else : 
                empty <= 1
        else : 
            full <= 0
            empty <= 0

    return dataout, full, empty


#-------------------------------------------------------------------------
# counter  
#-------------------------------------------------------------------------
def clock_divn(clk,reset,step,enable=None) :
    ' make signal which is divided by clock, step should not be zero '
    divn = logic_unique('divn_out')

    # step != 0
    w = min_bits(step)
    cv = logic_unique('divn_cv[%s]' % w) 
    tc = logic_unique('divn_tc')

    # enable 최초에 tc가 출력된다. 
    if enable is None : 
        with sequence(clk) :
            cv <= (0, reset | (cv==step), cv + 1)

        tc <= (1, -cv, 0)

    else : 
        with sequence(clk) :
            cv <= (0, reset | (cv==step), cv + 1, enable)

        tc <= (1, -cv & enable, 0)

    return tc


def counter_step(clk,reset,enable,step, final_value,*,init_value=0):
    '''(step+1)개의 clock 마다 counting을 한다.
    step : integer or logic, step should not be zero

    example) 4 clock마다 counting하여 8까지 counting한다.
            step = 4-1
            count_value <= counter_step(clk,reset,step,enable,8-1)

    enable되면 0부터 counting하여 step이 되면 count value가 1 증가한다.
    '''
    count_value  = logic_unique("count_value[%s]"%min_bits(final_value))
    cnt          = logic_unique("cnt[%s]"%min_bits(step+1))
    count_enable = logic_unique("count_enable")
    count_inc    = logic_unique("count_inc")

    with sequence(clk) :
        cnt <= (0, reset | (cnt==step), cnt + 1, enable)

    # enable 시작하자 마자 count enable 발생시킨다.
    count_enable <= (1, (cnt==0) & enable & -count_tc, 0) 
    count_inc    <= (1, (cnt==step) & enable & -count_tc, 0) 

    with sequence(clk) :
        count_value <= (init_value, reset, count_value + 1, count_inc)

        count_tc <= (0,reset, 1, count_enable & (count_value==final_value))

    return count_value, count_enable


