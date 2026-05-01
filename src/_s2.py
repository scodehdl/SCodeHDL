'''
    Basic functions : python standard library만 사용한다.
    2013-04-25
    2014-05-10 : get slice value from vectors
    2014-10-02 : bits_num
    2015-11-11 : configuration
'''
import collections
import os,sys
import copy
from contextlib import contextmanager
import itertools
import warnings
import configparser,codecs
import shutil
# from win32api import OutputDebugString
import traceback
import math
import time
import hashlib
from enum import Enum
import glob


#-------------------------------------------------------------------------
# configuration  
#-------------------------------------------------------------------------
admin = False

# USE_VHDL_2D_PORT = False    # TODO : False로 하는 경우 module별로 package 이름이 틀려서 type error가 발생한다.
# USE_UNISIM_LOWER_CASE = False
# USE_AST_ANDOR = False

def set_scode_config() : 
    ''

#-------------------------------------------------------------------------
#  procedures
#-------------------------------------------------------------------------
def filename_only(fname) : 
    ' delete directory and extension '
    return os.path.splitext(os.path.basename(fname))[0]

def extension_only(fname) : 
    ' extension include the dot (".exe"), extension이 없는 경우 empty string이 return된다. '
    ext = os.path.splitext(fname)[1]
    if ext == '.' :  # ' test. '
        return ''
    else : 
        return ext

def get_basepath(fname):
    p = os.path.dirname(os.path.abspath(fname))
    p = p.replace('\\','/')  # path에 \u가 포함되어 있으면 unicode error를 발생시킨다.
    return p

def get_filelist_basename(directory,extension):
    ''
    return [filename_only(f) for f in glob.glob("%s/*.%s" % (directory,extension))]
    

# list를 indentation된 string으로 변경
list_to_indented_line = lambda list_data,indent,term_char='' : ' '*indent + ('%s\n%s'%(term_char,' '*indent)).join(list_data) 

def match_list_pair(dst,src) :
    ''' list가 아닌 경우는 한 개의 element를 가진 list로 변경하고, 
        list인 경우는 개수를 맞춘다. 
    '''
    if type(dst) == list : 
        if type(src) == list : 
            ' both of list '
            assert len(dst) == len(src)
        else : # vaule
            src = [src for i in range(len(dst))]
    else : 
        assert type(src) is not list
        dst = [dst]
        src = [src]
    return dst,src

def _nonspace_index(s) : 
    return len(s) - len(s.lstrip())

def _min_indentation(str_list) : 
    if str_list : 
        return min(_nonspace_index(s) for s in str_list)
    else : # blank list 
        return 0

def set_indentation(str_statement, indent_num) : 
    ' 주어진 문장을 indendataion 설정한다.'
    if not str_statement : 
        # return ' ' * indent_num
        return ''

    # sl = [s for s in str_statement.split('\n') if s!='']
    sl = [s for s in str_statement.split('\n')]
    min_indent = _min_indentation(sl)

    sl = [s[min_indent:] for s in sl]

    # return list_to_indented_line(sl, indent_num)
    cvt = ''
    for s in sl : 
        if s : 
            cvt += '%s%s\n' % (' '*indent_num,s)
        else : 
            cvt += '\n'
    return cvt.rstrip() # last \n을 없앤다.

# obsolete decorator
class obsolete :  
    def __init__(self,arg='') :
        ''
        self.msg = arg

    def __call__(self,func) : 
        ''
        def wrapped_func(*args, **kwargs): 
            print("%s() will be obsolete => %s" % (func.__name__,self.msg))
            return func(*args, **kwargs) 
        return wrapped_func

# dict2 for dot access to attributes
class dict2(dict):
    def __getattr__(self, name):
        return self[name]

def cvt2dict2(d) : 
    ' standard dictionary를 dict2 class로 변경한다. '
    t = dict2()
    for k in d : 
        t[k] = d[k]
    return t        
    
    

odict = collections.OrderedDict


# class odict2(collections.OrderedDict):
#     def __init__(self,**kwargs):
#         super(collections.OrderedDict, self).__init__(kwargs) 
# 
#     def __getattr__(self, name):
#         return self[name]


def remove_same_item(data) : 
    ' use id() function '
    id_data = [id(d) for d in data] 

    udata = collections.OrderedDict()    
    for d in data : 
        ''
        if id(d) not in udata : 
            udata[id(d)] = d
    
    return list(udata.values())
 
@contextmanager
def workdir(path):
    old_dir = os.getcwd()
    os.chdir(path)
    yield
    os.chdir(old_dir)

# path 추가 후 복구한다.
@contextmanager
def pythonpath(path):
    old_path = copy.copy(sys.path)
    sys.path.insert(0,path)
    yield
    sys.path = old_path


# list flattening
def list_flatten(data) : 
    '[[1,2,3],[4,5,6], [7], [8,9]] -> [1, 2, 3, 4, 5, 6, 7, 8, 9]'
    return list(itertools.chain(*data))

def warning(msg):
    print(msg)

@contextmanager
def stdout_redirected(new_stdout):
    '''
        usage :
        with opened(filename, "w") as f:
            with stdout_redirected(f):
                print "Hello world"
        
        or use os.devnull for nothing
    '''
    save_stdout = sys.stdout
    sys.stdout = new_stdout
    try:
        yield None
    finally:
        sys.stdout = save_stdout

@contextmanager
def stderr_redirected(new_stderr):
    save_stderr = sys.stderr
    sys.stderr = new_stderr
    try:
        yield None
    finally:
        sys.stderr = save_stderr


' dictionary의 key를 모두 lower case로 변경한다. '
def tolower_keys(d):
    result = {}
    for key, value in d.items() : 
        result[key.lower()] = value
    return result

#----------------------------------------------------------------
# config
#----------------------------------------------------------------
# INI configuration
def get_config(section,option,fname='config.ini') : 
    ' get config ' 
    return __getConfiguration(section,option,fname)

def get_config_options(section,fname='config.ini') : 
    ' return options of given section by dictionary (key:option, value:option value)'
    parser = configparser.ConfigParser()
    with codecs.open(fname, 'r', encoding='utf-8') as f:
        parser.readfp(f)    
    
    d = collections.OrderedDict()
    for o in parser.options(section):
        d[o] = parser.get(section, o) 

    return d

def set_config(section,option,value,fname='config.ini') : 
    ' set config and save to file '
    return __setConfiguration(section,option,value,fname)

def __getConfiguration(section,option,fname='config.ini') : 
    parser = configparser.ConfigParser()
    with codecs.open(fname, 'r', encoding='utf-8') as f:
        parser.readfp(f)    

    # sections(), options()
    return parser.get(section, option) 

def __setConfiguration(section,option,value,fname='config.ini') : 
    parser = configparser.ConfigParser()
    with codecs.open(fname, 'r', encoding='utf-8') as f:
        parser.readfp(f)    
    # parser.read(fname)
    
    value = str(value) 
    parser.set(section, option, value) 
    parser.write(open(fname,'wb'))



#-------------------------------------------------------------------------
# SC source error — shows only the .sc file frame, not internal frames
#-------------------------------------------------------------------------

class SCSourceError(Exception):
    '''User-visible error pinpointing a line in a .sc source file.'''
    def __init__(self, sc_fname, sc_lineno, sc_line, cause):
        self.sc_fname  = sc_fname
        self.sc_lineno = sc_lineno
        self.sc_line   = sc_line.rstrip() if sc_line else ''
        self.cause     = cause
        super().__init__(str(cause))

    def display(self):
        msg = '  File "%s", line %d\n' % (self.sc_fname, self.sc_lineno)
        if self.sc_line:
            msg += '    %s\n' % self.sc_line
        msg += '%s: %s' % (type(self.cause).__name__, self.cause)
        sys.stdout.buffer.write((msg + '\n').encode(sys.stdout.encoding, errors='replace'))


def raise_sc_source_error_syntax(fname, syntax_err):
    '''Convert a SyntaxError from ast.parse into SCSourceError using the .sc fname.'''
    lineno = syntax_err.lineno or 0
    line   = (syntax_err.text or '').rstrip()
    raise SCSourceError(fname, lineno, line, syntax_err) from None


def raise_sc_source_error(exc_val, exc_tb):
    '''Walk traceback, find the innermost .sc frame, raise SCSourceError.
    Call from an except block: raise_sc_source_error(exc, exc.__traceback__)
    '''
    sc_frame = None
    for fs in traceback.extract_tb(exc_tb):
        if fs.filename.endswith('.sc'):
            sc_frame = fs
    if sc_frame is not None:
        raise SCSourceError(sc_frame.filename, sc_frame.lineno, sc_frame.line, exc_val) from None
    raise exc_val  # no .sc frame — propagate original


#
def mkdir_of_file(fname):
    ' file이 속한 directory가 없으면 생성한다. '
    dname = os.path.dirname(fname)
    if not os.path.exists(dname) : 
        ' make directory '
        os.makedirs(dname)

def clean_directory(wdir):
    ' directory안의 내용을 모두 지움 '
    for root, dirs, files in os.walk(wdir):
        for f in files:
            try : 
                os.unlink(os.path.join(root, f))
            except:
                pass
        for d in dirs:
            try : 
                shutil.rmtree(os.path.join(root, d))
            except:
                pass

def get_cmd_option(o,optlist):
     "optlist : [('-a', ''), ('-b', ''), ('-c', 'foo'), ('-d', 'bar')]"
     try : 
         k = [i[0] for i in optlist].index(o)
         return optlist[k][1]
     except :  
         return None

def mk_serdes_pattern(bits, pattern_data):
    ' LSB first serdes pattern '
    result = []
    for p in pattern_data : 
        result += list(reversed(format(p,'0%sb'%bits)))

    result = [int(i) for i in result]  # str -> int
    return result

def get_slice_value(value, slice_) : 
    ''
    def _get_bit(i): 
        return (value & 1<<i) >> i

    if type(slice_) == int : 
        return _get_bit(slice_)
    else : # slice
        ''
        s,e = slice_.start, slice_.stop
        # TODO start가 stop보다 큰 경우만 우선 고려한다. 7:0 , 3:0
        v = 0
        for i in range(e,s + 1):
            v += _get_bit(i) << (i-e)
        return v    


#-------------------------------------------------------------------------
# debug view 
#-------------------------------------------------------------------------
def debug_view(*s) :
    # if get_plugin_loaded() : 
    msg = ' '.join(str(i) for i in s)
    # OutputDebugString("[slab] %s" % msg)

def profile(func):
    def wrap(*args, **kwargs):
        started_at = time.time()
        result = func(*args, **kwargs)
        msg = time.time() - started_at
        # OutputDebugString("[scode profile] %s" % msg)
        print("[scode profile] %s" % msg)
        return result
    return wrap

def disp_error() : 
    print(traceback.format_exc(),file=sys.stderr)


#-------------------------------------------------------------------------
# directory management
#-------------------------------------------------------------------------

_root_dir_override = None   # set by root_dir_context()
_defines = {}               # set by set_defines() from CLI -D flags


def set_defines(d):
    global _defines
    _defines = dict(d)


def get_defines():
    return _defines

@contextmanager
def root_dir_context(path):
    '''Temporarily override SLAB_ROOT_DIR for programmatic callers (e.g. pythonnet, pytest).
    Sets both the internal override and os.environ so that user .sh code that calls
    os.getenv('SLAB_ROOT_DIR') directly also receives the correct value.
    '''
    global _root_dir_override
    resolved = os.path.abspath(str(path))
    _root_dir_override = resolved

    prev_env = os.environ.get('SLAB_ROOT_DIR')
    os.environ['SLAB_ROOT_DIR'] = resolved
    try:
        yield
    finally:
        _root_dir_override = None
        if prev_env is None:
            os.environ.pop('SLAB_ROOT_DIR', None)
        else:
            os.environ['SLAB_ROOT_DIR'] = prev_env


def _effective_root_dir():
    '''Returns active root dir: override > SLAB_ROOT_DIR env > cwd.'''
    if _root_dir_override is not None:
        return _root_dir_override
    return os.getenv('SLAB_ROOT_DIR')


def get_include_file(fname):
    # override > SLAB_ROOT_DIR > default lib
    root_dir = _effective_root_dir() or ''

    fn = os.path.join(root_dir, fname)
    if os.path.exists(fn):
        return fn

    fn = os.path.join(root_dir, 'lib', fname)
    if os.path.exists(fn):
        return fn

    return os.path.join(get_default_lib_dir(), fname)


def get_root_dir():
    ''
    root_dir = _effective_root_dir()
    if root_dir is not None:
        for s in root_dir.split(';'):
            if s not in sys.path:
                sys.path.append(s)
        lib = '%s/lib' % root_dir
        if lib not in sys.path:
            sys.path.append(lib)
    else:
        root_dir = os.path.abspath('./')
        if root_dir not in sys.path:
            sys.path.append(root_dir)

    return root_dir

def get_plugin_dir() : 
    ''
    plugin_dir = os.getenv('SLAB_PLUGIN_DIR')

    if not plugin_dir : 
        plugin_dir = _read_config('config','plugin_dir')
        if plugin_dir=='' : 
            plugin_dir = os.path.join(os.path.dirname(__file__), 'plugin')

    return plugin_dir


def get_output_dir(root_dir) : 
    ''
    outdir = './'

    # confif 파일이 있으면 outdir 있는지 check하여 사용한다.
    ini_file = '%s/config.ini' % root_dir
    try : 
        if os.path.exists(ini_file):
            outdir = get_config('config','outdir', fname=ini_file)
            outdir = os.path.join(root_dir,outdir)
    except : 
        ''
        disp_error()

    return outdir

def get_default_lib_dir() : 
    # TODO : SLAB_LIBRARY_DIR 이용하자.
    plugin_dir = os.getenv('SLAB_PLUGIN_DIR')

    if not plugin_dir : 
        return os.path.join(os.path.dirname(__file__), 'lib')
    else : 
        return '%s/../lib' % plugin_dir

def _read_config(section, option):
    ''
    root_dir = get_root_dir()

    ini_file = '%s/config.ini' % root_dir
    try : 
        if os.path.exists(ini_file):
            data = get_config(section, option, fname=ini_file)
            # outdir = os.path.join(root_dir,outdir)
            return data
        else : 
            return ""
    except : 
        ''
        return ''

def get_proj_name() : 
    ''
    prj_name = os.getenv('SLAB_PROJ_NAME')
    if not prj_name:  # None or ""
        prj_name = _read_config('config','proj_name')

    return prj_name
    # return prj_name.lower()

#-------------------------------------------------------------------------
# configuration 
#-------------------------------------------------------------------------
def get_verilog_output() : 
    try : 
        return eval(_read_config('config','verilog'))
    except : 
        return False

#-------------------------------------------------------------------------
# compatibility 
#-------------------------------------------------------------------------
def get_vhdl_2d_port() : 
    try : 
        return eval(_read_config('compatibility','vhld_2d_port'))
    except : 
        return False

def get_ast_andor() : 
    try : 
        return eval(_read_config('compatibility','ast_andor'))
    except : 
        return False

def get_with_sc_if() : 
    try : 
        return eval(_read_config('compatibility','with_sc_if'))
    except : 
        return True


def get_unisim_lower() : 
    try : 
        return eval(_read_config('compatibility','unisim_lower'))
    except : 
        return False


# math.isnan을 사용하면 num이 굉장히 커질때 overflow error 발생한다.
def check_nan(num):
    # return num != num
    if isinstance(num, (list, str)):
        return False
    return math.isnan(num)

def file_hash_value(fname):
    ' return full hash value of file '
    s = open(fname,encoding='latin-1').read()
    return hashlib.md5(bytes(s,'latin-1')).hexdigest()


# make enum starts from 0 in python 3.4 
def enum_from_str(name,s):
    se = Enum(name,s)
    se = Enum(name,[(e.name,e.value-1) for e in se])
    return se



