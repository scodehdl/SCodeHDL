'''
    run isim fuse simulator
    2013-07-03
    2013-09-10 : 복수개의 파일 지원
    2013-10-10 : support verilog simulation
    2013-10-30 : 포함되는 module을 자동으로 찾아서 simulation하는 방식으로 변경.
    2015-04-23 : pkg_util.vhd -> scode_util.vhd, 128 bits까지 확장
    2015-07-29 : 1024 array까지 scode_util.vhd에 정의
    2015-08-13
    2015-10-21 : run_fuse를 plugin에서 수행시킨다.
'''
import os,sys
import glob
import getopt
import importlib

import _s2
import hsignal as hs
import hmodule as hm


def run_sim_plugin(fname,*,outdir=None,ip_dir=None,verilog=False,fusesim_dir=None):
    ''
    # plugin
    plugin_dir = _s2.get_plugin_dir()

    root_dir = _s2.get_root_dir()
    if outdir==None : 
        outdir = _s2.get_output_dir(root_dir)

    if fusesim_dir==None : 
        fusesim_dir = outdir

    _s2.debug_view('Simulation : %s , outdir=%s, fusesimdir=%s' % (fname,outdir,fusesim_dir))
    vhdl_flag = not verilog

    # directory management
    if ip_dir is not None : 
        ip_dir = os.path.abspath(ip_dir)

    # fuse dir
    fuse_dir = '%s/fusesim' % fusesim_dir
    outdir = os.path.abspath(outdir)

    # make fuse directory if needed
    if not os.path.exists(fuse_dir):
        os.makedirs(fuse_dir)


    # .sc 제거
    if _s2.extension_only(fname) == '.sc' : 
        top_module = os.path.splitext(fname)[0]
    else : 
        top_module = fname

    top_module_name = _s2.filename_only(top_module) 

    # make project file
    if vhdl_flag : 
        flist = [os.path.join(outdir,n) for n in ['%s.vhd'%top_module_name]] 
    else :  
        flist = [os.path.join(outdir,n) for n in ['%s.v'%top_module_name]] 

    _s2.debug_view('simulation files : %s' % flist)

    # get module files list 
    flist += _get_module_file_list(top_module,vhdl_flag,outdir)


    #-------------------------------------------------------------------------
    # execute
    #-------------------------------------------------------------------------
    abs_fuse_dir = os.path.abspath(fuse_dir)
    if os.path.exists(plugin_dir):
        with _s2.workdir(plugin_dir) : 
            sys.path.append(plugin_dir)
            a = importlib.import_module('scplugin_simulate_isim') 
            a.run(filelist=flist,sim_dir=abs_fuse_dir)
            sys.path = sys.path[:-1]  # remove plugin_dir




def _get_child_file_list(mod,vhdl_flag,outdir):
    ''
    flist = []
    plugin_list = []    

    def _append_file(fnames):
        ''
        # 존재하지 않는 경우만 append
        for fname in fnames : 
            ''
            fn = os.path.abspath(fname)
            if (fn not in flist) and (_s2.filename_only(fn) not in plugin_list): 
                flist.append(fn)

    for o in mod.hdl_objects : 
        if isinstance(o, hs.IModule):
            for fname in [o.module.fname] + o.module.dependent_files :

                if fname.endswith('.sc') :
                    ''
                    # sc가 포함하는 파일을 recursive하게 추가
                    m = hm.parse_scfile(fname,outdir=outdir)
                    # flist += _get_child_file_list(m,vhdl_flag,outdir)
                    _append_file(_get_child_file_list(m,vhdl_flag,outdir))

                    #
                    if vhdl_flag : 
                        fn = '%s/%s.vhd' % (outdir,_s2.filename_only(fname))
                    else : 
                        fn = '%s/%s.v' % (outdir,_s2.filename_only(fname))
                    _append_file([fn])

                # elif fname.endswith('.vhd') :
                elif fname.endswith(('.vhd','.v')) :
                    _append_file([fname])

    return flist

def _get_module_file_list(module_name,vhdl_flag,outdir):
    ''
    fname = '%s.sc' % module_name

    if os.path.exists(fname):
        mod = hm.parse_scfile(fname,outdir=outdir)

        child_files = _get_child_file_list(mod,vhdl_flag,outdir)

        # add manually added file
        child_files += [os.path.abspath(f) for f in mod.add_files]

        _s2.debug_view('child modules : %s' % child_files)
        return child_files
    else : 
        assert 0, '[%s] not exist' % fname



def mk_package_file(outdir):
    ''
    fname = '%s/%s' % (outdir,'scode_util.vhd')
    fname = os.path.abspath(fname)

    # bit_array_str =  
    s = "    type std_{0}bit_array is array (natural range <>) of std_logic_vector({1} downto 0);"
    # bit_array_str = '\n'.join([s.format(i+1,i) for i in range(128)])
    bit_array_str = '\n'.join([s.format(i+1,i) for i in range(1024)])

    s = '''
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

package scode_util is
{0}
end scode_util;

package body scode_util is
end scode_util;

'''.format(bit_array_str) 

    with open(fname,'w') as f:
        f.write(s)
        print('%s generated'%fname)

    return fname 

if __name__ == '__main__' : 
    # ''' -c : compile only flag
    # python run_fuse.py counter
    # python run_fuse.py -c counter
    # '''

    # optlist, module_names = getopt.getopt(sys.argv[1:], 'c')
    # cflag = '-c' in (o[0] for o in optlist)

    # fname = sys.argv[1]
    # # run_fuse(fname,compile_only=cflag)
    # run_fuse(fname,compile_only=True)

    mk_package_file('/tmp/')




