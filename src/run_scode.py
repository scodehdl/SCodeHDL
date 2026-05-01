'''
    *.sc를 conversion한다.

    2014-05-05 : *.s2lab과 *.sc를 분리한다.
    2014-05-15 : SLAB_ROOT_DIR는 여러 개의 path를 포함하는 경우 ;로 분리한다. 
    2014-07-29 : imodule port template 출력하기
    2015-10-20 : support plugin
'''
import os,sys
import io
import importlib

import _s2
import hsignal as hs
import hmodule as hm
import hpostproc as hp
import hgenerator as hg
import hsimulation as hv

import codegen.cg_vhdl
import codegen.cg_verilog
import sc_json_export

_dependent_files = {}

def exec_slab(fnames, outdir=None, *, root_dir=None, silent=False, verilog=False, plugin_run=False, save_json=False):
    if root_dir is not None:
        with _s2.root_dir_context(root_dir):
            return _exec_slab_inner(fnames, outdir, silent=silent, verilog=verilog, plugin_run=plugin_run, save_json=save_json)
    else:
        return _exec_slab_inner(fnames, outdir, silent=silent, verilog=verilog, plugin_run=plugin_run, save_json=save_json)


def _exec_slab_inner(fnames, outdir=None, *, silent=False, verilog=False, plugin_run=False, save_json=False):
    root_dir = _s2.get_root_dir()

    # add current directory into python path
    sys.path.append(os.path.abspath('./'))


    # set configuration
    _s2.set_scode_config()

    #
    if outdir==None : 
        outdir = _s2.get_output_dir(root_dir)

    # # plugin
    # plugin_dir = _s2.get_plugin_dir()

    console_run = len(fnames)==1

    # conversion
    for fname in fnames : 
        # disp information
        _s2.debug_view('ROOT_DIR=%s'%root_dir,'Source=%s'%fname,'Outdir=%s'%outdir, 'PROJNAME=%s'%_s2.get_proj_name())

        ext = _s2.extension_only(fname)

        if ext in ['.sc']:
            mod = exec_scode_one(fname,outdir,silent=silent,verilog=verilog,console_run=console_run,save_json=save_json)

            # code generation
            if mod.conversion_flag:
                hg.hdl_code_generator(mod,outdir,silent=silent,verilog=verilog)

            # post processing
            hp.run_post_after_codegen(mod)
            if plugin_run : 
                exec_plugin(mod,outdir)



        else :
            print('Unsupported file type (%s)' % ext)

        sys.stdout.flush()

def exec_plugin(mod,outdir): 

    # plugin
    plugin_dir = _s2.get_plugin_dir()

    if mod and os.path.exists(plugin_dir):
        with _s2.workdir(outdir) : 
            sys.path.append(plugin_dir)

            
            # unparse
            # ----------------------------------------------------------------------
            # python3.7에서 error 발생하여 comment (2019/8/8)
            #   File "d:\my\dropbox\scode\src\unparser.py", line 578, in _Call
            #     if t.starargs:
            # AttributeError: 'Call' object has no attribute 'starargs'
            # ----------------------------------------------------------------------
            # a = importlib.import_module('scplugin_unparse') 
            # a.run(mod)

            # module information
            # a = importlib.import_module('scplugin_moduleinfo') 
            # a.run(mod)

            # latency calculator
            # a = importlib.import_module('scplugin_latency') 
            # a.run(mod)

            # execute the plugins in config
            # ini_file = '%s/config.ini' % root_dir
            # plugin_options = _s2.get_config_options('plugin',ini_file)
            # print(plugin_options)


            # remove plugin_dir
            sys.path = sys.path[:-1]  


def _imodule_str(fname,mod): 
    result = io.StringIO()
    print('imodule("%s",' %fname ,file=result)
    for p in mod.port_list : 
        print('    %s = %s,' % (p.name,p.name), file=result)
    
    print(')' ,file=result)
    return result.getvalue()

def get_imodule_template(fname):
    ' *.sc 파일을 읽어들여 imdoule template을 생성한다. return 값은 string '

    ## 
    ext = _s2.extension_only(fname)
    if ext == '.sc' : 
        mod = hm.parse_scfile(fname)
    elif ext in ['.vhd', '.vhdl'] : 
        mod = hm.make_module_from_vhdl_file(fname) 
    elif ext in ['.v'] : 
        mod = hm.make_module_from_verilog_file(fname) 
    else : 
        assert ext in ['.sc', '.vhd', '.vhdl']

    out_str = _imodule_str(fname,mod)

    # verilog port 
    hg.hdl_conversion_method(codegen.cg_verilog)
    verilog_port = hg.component_definition(mod)

    return out_str + verilog_port 

def get_dependent_file(fname):
    ''
    fn = _s2.filename_only(fname)
    # print(fn)
    if fn in _dependent_files.keys() : 
        return _dependent_files[fn]
    else : 
        _s2.debug_view('Warning:%s not in dependent list (%s)' % (fn, _dependent_files.keys()))
        return ''


def exec_scode_one(fname,outdir=None,*,silent=False, verilog=False, console_run=False, save_json=False):
    ' fname에는 *.sc의 extension이 포함되어 있다. '
    if outdir == None :
        outdir = './'

    # run file
    _s2.debug_view('exec_scode_one : %s' % fname)
    hs.LogicBase.set_inst_id(0)
    hs.IModule.set_uut_id(0)

    # parse
    mod = hm.parse_scfile(fname,parent=None,outdir=outdir,debug_log=True,verilog=verilog)

    global _dependent_files
    _dependent_files[_s2.filename_only(fname)] = mod.dependent_files

    # post processing : return modified module
    mmod = hp.run_post_processing(mod)

    
    #-------------------------------------------------------------------------
    # get module information
    #-------------------------------------------------------------------------
    if console_run and save_json :
        with hs.module_assigned_to_target(mmod) :
            sc_json_export.save_module_json(mmod, mmod.outdir)


    return mmod



if __name__ == '__main__' :
    ''
    if len(sys.argv) == 2 :
        _s2.admin = True
        fname = sys.argv[1]
        root_dir = os.path.abspath(os.path.dirname(fname))

        # conversion
        verilog = _s2.get_verilog_output()
        exec_slab([fname], root_dir=root_dir, plugin_run=True, verilog=verilog)


    elif len(sys.argv) == 3 :
        if sys.argv[1] == '-verilog':
            fname = sys.argv[2]
            root_dir = os.path.abspath(os.path.dirname(fname))
            exec_slab([fname], root_dir=root_dir, verilog=True, plugin_run=True)
        elif sys.argv[1] == '-comp':
            fname = sys.argv[2]
            print(get_imodule_template(fname))



