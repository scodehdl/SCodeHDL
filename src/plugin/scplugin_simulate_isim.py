'''
    xilinx isim simulation (called by simulation logic)

    xilinx environment should be called before running this script 
    (For example execute "C:/Xilinx/14.7/ISE_DS/settings64.bat")
    
    2015-10-21
    2016-08-10 : verilog lib added
'''
import os,sys
import subprocess

from contextlib import contextmanager



def run(filelist,sim_dir) : 
    ''
    if len([f for f in filelist if f.endswith('.v')]) > 0 : 
        verilog_flag = True
        filelist.append('C:/Xilinx/14.7/ISE_DS/ISE//verilog/src/glbl.v')
    else : 
        verilog_flag = False

    # make project file
    with open('%s/simulate_isim.prj'%sim_dir, 'w') as f : 
        ''
        for fname in filelist :
            if fname.endswith(('.vhd','.vhdl')) : 
                print('vhdl work "%s"'%fname,file=f)
            elif fname.endswith(('.v',)) : 
                print('verilog work "%s"'%fname,file=f)

    # 1st file is the top module 
    top_module_name = filename_only(filelist[0])

    # run fuse
    with workdir(sim_dir) : 
        ''
        if not verilog_flag : 
            cmd = 'fuse.exe -prj simulate_isim.prj -o simulate_isim.exe work.%s' % (top_module_name) 
        else : # verilog for unisim
            cmd = 'fuse.exe work.glbl -prj simulate_isim.prj -o simulate_isim.exe -lib unisims_ver -lib unimacro_ver -lib xilinxcorelib_ver -lib secureip work.%s' % (top_module_name) 
        error = os.system(cmd)

        os.system('simulate_isim.exe -gui -wdb simulate_isim.wdb')



@contextmanager
def workdir(path):
    old_dir = os.getcwd()
    os.chdir(path)
    yield
    os.chdir(old_dir)

def filename_only(fname) : 
    ' delete directory and extension '
    return os.path.splitext(os.path.basename(fname))[0]



