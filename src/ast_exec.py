'''
    ast execution
    2014-05-16
    2014-05-28 : 자동 변수 선언. 
                 자동 선언이 combination에서만 작동한다.  sequence문장에서는 사용 할 수 없음
    2014-06-07 : 자동 변수 선언은 exec가 아닌 ast parsing으로 옮긴다.                  
                 ast 실행중에 처리하면 nesting을 처리하기가 너무 힘듬.

    2014-08-14 : support a = dict(...); imodule(fname, **a)
   
    2016-08-03 : 1st run에서만 call된다. 

'''
import os,sys
import re
import ast,copy
import traceback

import _s2
import hsignal as hs

def ast_exec(module, parsed):
    '''Execute each top-level AST statement for the 1st pass (signal discovery).

    1st run에서만 call된다.

    The 1st pass purpose is to discover all signal/port names and their widths
    so that the 2nd pass (hmodule._exec_2nd_run) can execute the full sc file
    with a complete namespace.

    Each statement is executed by _exec_one_ast, which catches NameError and
    injects a SignalUnspecified placeholder for every unknown name, then retries.
    When an imodule() call is encountered the sub-module is parsed recursively,
    which can introduce many new names in one shot — hence the retry loop.
    '''

    for p in parsed.body :
        exec_again = _exec_one_ast(module,p)

        # imodule 연결시에는 name error가 계속적으로 발생한다. 그러므로 error가 없어질때까지 계속
        # 수행해야 한다. 다만 무한 루프에 빠지지 않기 위해 1000개로 제한한다.
        # Guard against infinite loops; 1000 retries is far more than any real sc
        # file would ever need (a single statement can reference at most O(100) names).
        N = 1000
        for i in range(N):
            if not exec_again :
                break
            exec_again = _exec_one_ast(module,p)

    # 1st run이 끝난 후 SignalUnspecified가 있으면 에러 처리하여야 한다.
    # Remaining SignalUnspecified entries mean a name was used but never defined.
    # Logged as a warning here; hard error is raised in _exec_2nd_run instead.
    name_list = []
    for k in module.namespace :
        if isinstance(module.namespace[k], (hs.SignalUnspecified)) :
            name_list.append(k)

    if len(name_list) > 0 :
        _s2.debug_view('[%s] 1st run end [%s]' % (module.mod_name,name_list))
        # raise AssertionError("[%s] %s not defined" % (module.fname,name_list))



#-------------------------------------------------------------------------
# b       : node.value.id=b, node.value.slice.value.n=0
# b[0]    : node.value.value.id=b, node.value.slice.value.n=0
# b[0][2] :

def _exec_one_ast(module, parsed):
    '''Execute one AST statement; on NameError inject a SignalUnspecified placeholder.

    ast별로 수행시키며, name error가 나는 경우, 자동으로 signal 선언한다.

    Returns True if the statement should be retried (a new placeholder was added),
    False if execution succeeded or an unrelated error occurred.

    The placeholder (SignalUnspecified) satisfies Python's name lookup so the
    statement can be re-executed. The caller retries until no new NameErrors
    appear.  After all retries the 2nd pass replaces each placeholder with the
    real signal object derived from the full sc file context.
    '''
    code = compile(ast.Module(body=[parsed], type_ignores=[]), module.fname, 'exec')

    exec_again = False

    try :
        exec(code, module.namespace)

    except NameError :
        o = re.search(r"NameError: name '(.*)' is not defined", traceback.format_exc())
        name = o.group(1)

        # Inject a placeholder so the statement can be re-executed with this
        # name resolved. SignalUnspecified behaves like a wide vector so that
        # slice/subscript operations on it do not raise secondary errors.
        module.namespace[name] = hs.SignalUnspecified(name)
        exec_again = True
        _s2.debug_view('NameError : %s' % name, exec_again, parsed)

    except Exception as e:
        _s2.raise_sc_source_error(e, e.__traceback__)

    return exec_again




if __name__ == '__main__' : 
    ''
    parsed = ast.parse('a=1')
    a = parsed.body[-1]


