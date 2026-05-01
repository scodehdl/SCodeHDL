'''
    core libraries 
'''
#-------------------------------------------------------------------------
# double buffering to prevent metastability
# data2 <= double_sync(clk, data)
#-------------------------------------------------------------------------
def double_sync(clk,data_in):
    name = data_in.name

    if data_in.islogic() : 
        data_in_1d = logic_unique("%s_1d"%name)
        data_out   = logic_unique("%s_out"%name)
    else : 
        data_in_1d = logic_unique("%s_1d[%s]" % (name,data_in.width))
        data_out   = logic_unique("%s_out[%s]" % (name,data_in.width))

    with sequence(clk) : 
        data_in_1d <= data_in
        data_out <= data_in_1d

    return data_out

# strobe generation
def start_strobe(clk,sig):
    ' logic의 처음에 1clock 신호를 만든다. '
    name = sig.name

    out = logic_unique("%s_start" % name)
    sig_1d = logic_unique("%s_1d" % name)

    with sequence(clk) :
        sig_1d <= sig

    out <= (1,And(sig_1d==0,sig==1),0)
    return out

def end_strobe(clk,sig):
    ' logic의 마지막에 1clock 신호를 만든다. '
    name = sig.name

    out = logic_unique("%s_end" % name) 
    sig_1d = logic_unique("%s_1d" % name)

    with sequence(clk) :
        sig_1d <= sig

    out <= (1,And(sig_1d==1,sig==0),0)
    return out

def start_strobe_meta(clk,sig):
    ' sig가 clk에 동기 안 맞는 경우 double sync가 필요하다. '
    sig_meta = double_sync(clk,sig)
    # print(sig_meta.name, sig_meta.unique_candidate)
    return start_strobe(clk,sig_meta)

def end_strobe_meta(clk,sig):
    ' sig가 clk에 동기 안 맞는 경우 double sync가 필요하다. '
    sig_meta = double_sync(clk,sig)
    return end_strobe(clk,sig_meta)

# delay
def delay_logic(clk,in_data,delay_num):
    ''
    dly_logic = [logic_like_unique('%s%sD' %(in_data.name,i+1),in_data) for i in range(delay_num)]

    with sequence(clk) :
        ' reset없이 아래와 같이 작성하면 xilinx같은 경우 Flip-flop이 아닌 SRL16을 필요시 자동으로 사용한다. '
        for i in range(delay_num):
            dly_logic[i] <= (in_data if i==0 else dly_logic[i-1])

    return dly_logic[-1]  # return last one


# conversion array <-> multivector
def ar2mv(src):
    dst = logic_unique("%s[%s][%s]" % (src.name,len(src),src.width))

    for i in range(len(src)):
        dst[i] <= src[i]

    return dst

def mv2ar(src):
    dst = array_unique("%s[%s][%s]" % (src.name,len(src),src.width))

    for i in range(len(src)):
        dst[i] <= src[i]

    return dst


#-------------------------------------------------------------------------
#  counter library
#-------------------------------------------------------------------------
def counter_trigger(clk,reset,n) : 
    '''  주어진 n까지 counting 하고 1개의 trigger를 발생시킨다. 
    '''
    count = logic_unique('ctrg_out[%s]' % min_bits(n)) 
    tc = logic_unique('ctrg_tc') 
    ended = logic_unique('ctrg_ended') 

    with sequence(clk) :
        count <= (0, reset | tc, count + 1, -tc & -ended)

    tc <= (1, count==n,0)

    with sequence(clk) :
        ended <= (0,reset, 1, tc)

    return tc


def counter_period(clk,reset,n,enable=None) : 
    ''' period generation : enable이 None인 경우는 free-running counter이고,
    parameter가 주어진 경우에는 enable구간에서만 tc가 출력된다.
    '''
    w = min_bits(n)
    cv = logic_unique('cperiod_v[%s]' % w) 
    tc = logic_unique('cperiod_tc')
    out = logic_unique('cperiod_out')

    if enable is None : # 
        with sequence(clk) :
            cv <= (0, Or(reset,tc), cv + 1)
    else : 
        with sequence(clk) :
            cv <= (0, Or(reset,tc), cv + 1,enable)

    tc <= (1, cv==n,0)

    # compare with 1 to generate at 1st 
    out <= (1, cv==1,0)
    return out


def trigger_delay(clk,reset,trigger,delay):
    ' trigger가 발생하면, delay 지난 후 하나의 pulse가 만들어진다. '
    # cnt = logic_unique("tdelay_cnt[%s]:=0"%min_bits(delay))
    cnt = logic_unique("tdelay_cnt[%s]"%min_bits(delay))
    tc = logic_unique("tdelay_tc")
    enable = logic_unique("tdelay_enable")

    with sequence(clk) :
        enable <= (0,Or(reset,tc),1,trigger)

    with sequence(clk) :
        cnt <= (0, Or(reset,trigger), cnt + 1,enable)

    tc <= (1, cnt==delay, 0)  
    return tc
 

def trigger_enable(clk,reset,trigger,enable_num,delay=None):
    ''
    cnt = logic_unique("tenable_cnt[%s]"%min_bits(enable_num))
    enable = logic_unique("tenable_enable")
    tc = logic_unique("tenable_tc")
    
    if delay is None : 
        trg = trigger
    else : # make delayed trigger
        trg = trigger_delay(clk,reset,trigger,delay)

    ##
    with sequence(clk) :
        enable <= (0, Or(reset,tc), 1, trg)
 
    with sequence(clk) :
        cnt <= (0, Or(reset,trg), cnt + 1, enable)

    tc <= (1, cnt==enable_num,0)

    return enable



#-------------------------------------------------------------------------
# shifter and rotator 
#-------------------------------------------------------------------------
def srl(data,n) :
    ' shift right logic'
    return concat(LL(n),data[data.width-1:n])

def sll(data,n) :
    ' shift left logic'
    return concat(data[data.width-1-n:0], LL(n))

def sra(data,n) :
    ' shift right arithmetic'
    w = data.width
    cc = concat()
    for i in range(n):
        cc.append(data[w-1])

    return concat(cc,data[w-1:n])

# rotator
def ror(data,n):
    ' rotate right '
    return concat(data[n-1:0],data[data.width-1:n])

def rol(data,n):
    ' rotate left '
    w = data.width
    return concat(data[w-1-n:0],data[w-1:w-n])


#-------------------------------------------------------------------------
# testbench library 
#-------------------------------------------------------------------------

# synchronous stimulus
def tbl_high(clk,n):
    ' simulation이 시작된 후 n개 clock에서 high가 된다. '
    cout = logic_unique("cout[%s]:=0" % min_bits(n))
    cout_tc = logic_unique("cout_tc:=0")

    with sequence(clk) :
        cout <= cout + 1

        cout_tc <= (1,cout==n)

    return cout_tc

def tbl_low(clk,n):
    ' simulation이 시작된 후 n개 clock에서 low가 된다. '
    return ~tbl_high(clk,n)

def tbl_high_between(clk,n1,n2):
    s = logic_unique("hstart")
    e = logic_unique("hend")
    r = logic_unique("hresult")

    s <= tbl_high(clk,n1)
    e <= tbl_high(clk,n2)

    r <= (1, s & -e, 0)
    return r


def tbl_low_between(clk,n1,n2): return ~tbl_high_between(clk,n1,n2)
def tbl_high_oneshot(clk,n): return tbl_high_between(clk,n,n+1)
def tbl_low_oneshot(clk,n): return tbl_low_between(clk,n,n+1)

def tbl_pattern(clk,n,data): 
    ' n is start clock location, data is list or ndarray '

    num = len(data) 
    width = int(max_bits_of_list(data))

    # define unique logic
    sel = logic_unique('sel[%s]:=0' % min_bits(num-1))
    pattern = logic_unique('pattern[%s]' % width)
    enable = logic_unique('enable') 
    pattern_data = array_unique("pattern_data[%s][%s]"%(num,width), init=data)

    # 
    enable <= tbl_high_between(clk,n,n+num)

    # if the number of data is not 2's multiple, index error occurred. So check sel is less than num-1
    with sequence(clk) :
        sel <= (sel+1,And(enable,sel < num-1))

    pattern <= pattern_data[sel]

    return pattern, enable

